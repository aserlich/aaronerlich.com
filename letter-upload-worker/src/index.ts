// letter-upload-worker
//
// GET  /upload/<token> — render submission form: structured program rows + file upload
// POST /upload/<token> — parse + validate programs JSON, write files to Dropbox
//                       (App folder sandbox), update KV entry with programs +
//                       state, notify Aaron via Resend. A separate launchd rsync
//                       mirrors the Dropbox folder into his OneDrive archive.
// GET  /                — health check

import { Hono } from "hono";
import { lookupToken, type LetterRequest } from "./tokens";
import { uploadToDropbox, type DropboxEnv } from "./dropbox";
import { sendNotificationEmail, type EmailEnv } from "./email";
import {
  renderUploadForm,
  renderSuccessPage,
  renderErrorPage,
} from "./html";
import { parsePrograms } from "./validation";

type Env = DropboxEnv &
  EmailEnv & {
    TOKENS: KVNamespace;
    ENVIRONMENT: string;
    MAX_FILE_SIZE: string;
    MAX_FILES: string;
  };

const app = new Hono<{ Bindings: Env }>();

app.get("/", (c) =>
  c.json({ status: "ok", service: "letter-upload-worker", env: c.env.ENVIRONMENT }),
);

app.get("/upload/:token", async (c) => {
  const token = c.req.param("token");
  const request = await lookupToken(c.env.TOKENS, token);
  if (!request) {
    return c.html(renderErrorPage("This link is not valid or has expired."), 404);
  }
  if (request.state !== "pending_upload") {
    return c.html(
      renderErrorPage(
        "This link has already been used. If you need to re-send materials, email Aaron for a new link.",
      ),
      410,
    );
  }
  return c.html(renderUploadForm(request));
});

app.post("/upload/:token", async (c) => {
  const token = c.req.param("token");
  const request = await lookupToken(c.env.TOKENS, token);
  if (!request) {
    return c.html(renderErrorPage("This link is not valid or has expired."), 404);
  }
  if (request.state !== "pending_upload") {
    return c.html(
      renderErrorPage("This link has already been used."),
      410,
    );
  }

  const maxFileSize = parseInt(c.env.MAX_FILE_SIZE || "52428800", 10);

  // Collect files from multipart form data
  let formData: FormData;
  try {
    formData = await c.req.formData();
  } catch (e: unknown) {
    return c.html(
      renderErrorPage(
        `Could not parse upload: ${e instanceof Error ? e.message : "unknown error"}`,
      ),
      400,
    );
  }

  // Parse + validate the structured programs blob (hidden field emitted by
  // the form's inline JS). Must have at least one fully-valid program row.
  const programsRaw = formData.get("programs_json");
  const programsJson =
    typeof programsRaw === "string" ? programsRaw : null;
  const programs = parsePrograms(programsJson);
  if (programs === null) {
    return c.html(
      renderErrorPage(
        "Could not parse the programs data. Please go back and re-fill the form.",
      ),
      400,
    );
  }
  if (programs.length === 0) {
    return c.html(
      renderErrorPage(
        "Please fill in at least one program with name, institution, deadline, and submission method (and a URL if using an online portal).",
      ),
      400,
    );
  }

  // Four required, slot-tagged file inputs. Filename prefixes (`01-statement_…`,
  // etc.) make the slot identity durable in Dropbox / OneDrive / the
  // letter-draft skill, regardless of what the student named the original file.
  const SLOTS = [
    { key: "file_statement",  label: "Statement of purpose", prefix: "01-statement"   },
    { key: "file_transcript", label: "Transcript",           prefix: "02-transcript"  },
    { key: "file_cv",         label: "CV / résumé",          prefix: "03-cv"          },
    { key: "file_selfbrief",  label: "Self-brief",           prefix: "04-self-brief"  },
  ] as const;

  const files: Array<{ name: string; data: ArrayBuffer; size: number; slot: string }> = [];
  for (const slot of SLOTS) {
    const value = formData.get(slot.key);
    if (!(value instanceof File) || value.size === 0) {
      return c.html(
        renderErrorPage(
          `Missing required file: ${slot.label}. Please go back and attach all four documents.`,
        ),
        400,
      );
    }
    if (value.size > maxFileSize) {
      return c.html(
        renderErrorPage(
          `File "${value.name}" (${slot.label}) exceeds the ${(maxFileSize / 1024 / 1024).toFixed(0)} MB limit.`,
        ),
        413,
      );
    }
    // Sanitize the original filename: keep only word chars, dot, hyphen.
    // Anything else collapses to underscore. Preserves the extension.
    const safe = value.name.replace(/[^\w.\-]+/g, "_").replace(/^_+|_+$/g, "");
    const data = await value.arrayBuffer();
    files.push({
      name: `${slot.prefix}_${safe || "file"}`,
      data,
      size: value.size,
      slot: slot.label,
    });
  }

  // Upload each file to Dropbox
  const uploadedFiles: Array<{ name: string; size: number; slot: string }> = [];
  try {
    for (const f of files) {
      await uploadToDropbox(c.env, request.folder_path, f.name, f.data);
      uploadedFiles.push({ name: f.name, size: f.size, slot: f.slot });
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown error";
    return c.html(
      renderErrorPage(`Upload failed while writing to Dropbox: ${msg}`),
      500,
    );
  }

  // Write the updated LetterRequest back to KV: populated programs array
  // + advanced state + an appended state_log entry. The Python pull-script
  // will later mirror this back into _data/letter-requests.yml.
  const nowIso = new Date().toISOString();
  const stateLog = [
    ...(request.state_log ?? []),
    { state: "uploaded" as const, at: nowIso },
  ];
  const updatedRequest: LetterRequest = {
    ...request,
    programs,
    state: "uploaded",
    state_log: stateLog,
  };
  try {
    await c.env.TOKENS.put(token, JSON.stringify(updatedRequest));
  } catch (e) {
    console.error(
      "KV write-back failed:",
      e instanceof Error ? e.message : e,
    );
  }

  // Fire notification email (non-blocking — log failure but don't fail the request)
  try {
    await sendNotificationEmail(c.env, updatedRequest, uploadedFiles);
  } catch (e) {
    console.error(
      "Notification email failed:",
      e instanceof Error ? e.message : e,
    );
  }

  return c.html(renderSuccessPage(updatedRequest, uploadedFiles));
});

// Catch-all for unknown paths
app.notFound((c) => c.html(renderErrorPage("Page not found."), 404));

export default app;
