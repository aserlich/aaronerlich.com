// Microsoft Graph API client — writes uploaded student materials into
// Aaron's OneDrive at LORs/<category>/<LastName_FirstName_Year>/<filename>.
//
// Auth flow: OAuth 2.0 refresh-token exchange.
// One-time setup:
//   1. In the Microsoft Entra admin center, register a new application
//      under Aaron's McGill tenant.
//   2. Grant delegated scope Files.ReadWrite and offline_access.
//   3. Add a client secret, note the value.
//   4. Run the interactive auth code flow once (e.g., via
//      `npx @azure/identity get-token`) to obtain a refresh token with
//      consent to those scopes.
//   5. Store tenant ID, client ID, client secret, and refresh token as
//      Worker secrets (see wrangler.toml).
//
// The Worker exchanges the refresh token for an access token on each request.
// Access tokens are short-lived (~1 hour) but refresh tokens last 90 days.

export type GraphEnv = {
  GRAPH_CLIENT_ID: string;
  GRAPH_CLIENT_SECRET: string;
  GRAPH_TENANT_ID: string;
  GRAPH_REFRESH_TOKEN: string;
};

const GRAPH_BASE = "https://graph.microsoft.com/v1.0";
const SIMPLE_UPLOAD_THRESHOLD = 4 * 1024 * 1024; // 4 MB
const CHUNK_SIZE = 4 * 1024 * 1024;

async function getAccessToken(env: GraphEnv): Promise<string> {
  const tokenUrl = `https://login.microsoftonline.com/${env.GRAPH_TENANT_ID}/oauth2/v2.0/token`;
  const body = new URLSearchParams({
    client_id: env.GRAPH_CLIENT_ID,
    client_secret: env.GRAPH_CLIENT_SECRET,
    refresh_token: env.GRAPH_REFRESH_TOKEN,
    grant_type: "refresh_token",
    scope: "https://graph.microsoft.com/Files.ReadWrite offline_access",
  });

  const resp = await fetch(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!resp.ok) {
    const errText = await resp.text();
    throw new Error(
      `Graph token exchange failed (${resp.status}): ${errText.slice(0, 300)}`,
    );
  }

  const data = (await resp.json()) as {
    access_token?: string;
    error?: string;
    error_description?: string;
  };

  if (!data.access_token) {
    throw new Error(
      `No access_token in Graph response: ${data.error ?? "unknown"} ${
        data.error_description ?? ""
      }`,
    );
  }
  return data.access_token;
}

/**
 * Build the OneDrive API path for a file under LORs/.
 * category/folder_name/filename -> encoded for the Graph path.
 */
function buildPath(folderPath: string, filename: string): string {
  const segments = `LORs/${folderPath}/${filename}`
    .split("/")
    .filter(Boolean)
    .map(encodeURIComponent);
  return segments.join("/");
}

/** Simple upload (PUT) for files ≤4 MB. */
async function simpleUpload(
  accessToken: string,
  folderPath: string,
  filename: string,
  data: ArrayBuffer,
): Promise<void> {
  const path = buildPath(folderPath, filename);
  const url = `${GRAPH_BASE}/me/drive/root:/${path}:/content`;

  const resp = await fetch(url, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/octet-stream",
    },
    body: data,
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(
      `OneDrive simple upload failed (${resp.status}): ${text.slice(0, 300)}`,
    );
  }
}

/** Resumable upload session for files >4 MB. */
async function chunkedUpload(
  accessToken: string,
  folderPath: string,
  filename: string,
  data: ArrayBuffer,
): Promise<void> {
  const path = buildPath(folderPath, filename);
  const sessionUrl = `${GRAPH_BASE}/me/drive/root:/${path}:/createUploadSession`;

  const sessionResp = await fetch(sessionUrl, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      item: { "@microsoft.graph.conflictBehavior": "rename" },
    }),
  });

  if (!sessionResp.ok) {
    const text = await sessionResp.text();
    throw new Error(
      `createUploadSession failed (${sessionResp.status}): ${text.slice(0, 300)}`,
    );
  }

  const session = (await sessionResp.json()) as { uploadUrl: string };
  const total = data.byteLength;
  let offset = 0;

  while (offset < total) {
    const end = Math.min(offset + CHUNK_SIZE, total);
    const chunk = data.slice(offset, end);
    const chunkResp = await fetch(session.uploadUrl, {
      method: "PUT",
      headers: {
        "Content-Length": String(chunk.byteLength),
        "Content-Range": `bytes ${offset}-${end - 1}/${total}`,
      },
      body: chunk,
    });
    // 202 = chunk accepted, 200/201 = final chunk accepted
    if (!chunkResp.ok && chunkResp.status !== 202) {
      const text = await chunkResp.text();
      throw new Error(
        `Chunk upload failed at offset ${offset} (${chunkResp.status}): ${text.slice(0, 300)}`,
      );
    }
    offset = end;
  }
}

/** Upload a single file into Aaron's OneDrive LORs tree. */
export async function uploadToOneDrive(
  env: GraphEnv,
  folderPath: string,
  filename: string,
  data: ArrayBuffer,
): Promise<void> {
  const accessToken = await getAccessToken(env);
  if (data.byteLength <= SIMPLE_UPLOAD_THRESHOLD) {
    await simpleUpload(accessToken, folderPath, filename, data);
  } else {
    await chunkedUpload(accessToken, folderPath, filename, data);
  }
}
