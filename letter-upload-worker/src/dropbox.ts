// Dropbox API client — writes uploaded student materials into Aaron's
// Dropbox App folder at /LORs/<category>/<LastName_FirstName_Year>/<filename>.
//
// The Cloudflare Worker writes to Dropbox via the /2/files/upload endpoint
// (single-POST, ≤150 MB). A launchd rsync job then mirrors the files to
// Aaron's McGill OneDrive archive. Dropbox is the ingestion tip; OneDrive
// is the canonical 834-file style corpus.
//
// Auth — two modes:
//
//   1. Short-lived token (testing only): set DROPBOX_ACCESS_TOKEN. Expires
//      in ~4 hours, fine for initial end-to-end verification.
//
//   2. Refresh-token flow (production): set DROPBOX_APP_KEY, DROPBOX_APP_SECRET,
//      DROPBOX_REFRESH_TOKEN. The worker exchanges the refresh token for a
//      short-lived access token on each request. Refresh tokens are
//      long-lived (no expiry unless revoked).
//
// One-time setup for refresh-token mode:
//   1. Create an app at https://www.dropbox.com/developers/apps
//      (Scoped access, App folder, name = letter-upload-worker)
//   2. Permissions tab: check files.content.write, files.content.read → Submit
//   3. Settings tab: note the App key and App secret
//   4. Run the OAuth offline flow once (see capture-dropbox-refresh-token.mjs)
//      to obtain a refresh_token
//   5. Store app_key, app_secret, refresh_token as Worker secrets

export type DropboxEnv = {
  DROPBOX_ACCESS_TOKEN?: string;    // short-lived, for initial testing
  DROPBOX_APP_KEY?: string;         // long-term refresh-flow fields
  DROPBOX_APP_SECRET?: string;
  DROPBOX_REFRESH_TOKEN?: string;
};

const UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload";
const TOKEN_URL = "https://api.dropboxapi.com/oauth2/token";
// Dropbox /2/files/upload is single-POST ≤150 MB. We enforce 50 MB/file at
// the Worker layer already (MAX_FILE_SIZE), so we never need the chunked
// upload_session endpoints.

/**
 * Resolve a bearer token for this request. Prefers the long-term
 * refresh-token flow when configured; falls back to the short-lived access
 * token for testing.
 */
async function resolveAccessToken(env: DropboxEnv): Promise<string> {
  if (env.DROPBOX_REFRESH_TOKEN && env.DROPBOX_APP_KEY && env.DROPBOX_APP_SECRET) {
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: env.DROPBOX_REFRESH_TOKEN,
    });
    const basic = btoa(`${env.DROPBOX_APP_KEY}:${env.DROPBOX_APP_SECRET}`);
    const resp = await fetch(TOKEN_URL, {
      method: "POST",
      headers: {
        Authorization: `Basic ${basic}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(
        `Dropbox refresh exchange failed (${resp.status}): ${text.slice(0, 300)}`,
      );
    }
    const data = (await resp.json()) as { access_token?: string };
    if (!data.access_token) {
      throw new Error("Dropbox refresh response missing access_token");
    }
    return data.access_token;
  }
  if (env.DROPBOX_ACCESS_TOKEN) {
    return env.DROPBOX_ACCESS_TOKEN;
  }
  throw new Error(
    "No Dropbox credentials configured — set DROPBOX_ACCESS_TOKEN (testing) or DROPBOX_APP_KEY/DROPBOX_APP_SECRET/DROPBOX_REFRESH_TOKEN (production).",
  );
}

/**
 * Build the Dropbox API path for a file under the app's LORs root.
 * For an "App folder" scoped app, paths are relative to /Apps/<AppName>/
 * in the user's Dropbox — so '/LORs/...' ends up at
 * '~/Dropbox/Apps/letter-upload-worker/LORs/...' on disk.
 */
function buildPath(folderPath: string, filename: string): string {
  // Dropbox paths must start with "/" and not contain encoded segments —
  // it accepts raw UTF-8 in the API-Arg JSON header.
  return `/LORs/${folderPath}/${filename}`.replace(/\/+/g, "/");
}

/**
 * Upload a single file to Dropbox. Creates any intermediate folders
 * automatically. Renames on conflict (autorename=true) so a returning
 * student's resubmitted file doesn't clobber their prior cycle.
 */
export async function uploadToDropbox(
  env: DropboxEnv,
  folderPath: string,
  filename: string,
  data: ArrayBuffer,
): Promise<void> {
  const accessToken = await resolveAccessToken(env);
  const dropboxPath = buildPath(folderPath, filename);

  const apiArg = JSON.stringify({
    path: dropboxPath,
    mode: "add",
    autorename: true,
    mute: false,
    strict_conflict: false,
  });

  const resp = await fetch(UPLOAD_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/octet-stream",
      "Dropbox-API-Arg": apiArg,
    },
    body: data,
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(
      `Dropbox upload failed for ${dropboxPath} (${resp.status}): ${text.slice(0, 300)}`,
    );
  }
}
