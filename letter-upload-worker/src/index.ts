// letter-upload-worker
//
// GET  /upload/<token> — render upload form
// POST /upload/<token> — accept multipart files, write to OneDrive, notify Aaron
// GET  /                — health check

import { Hono } from "hono";
import { lookupToken, markTokenState, type LetterRequest } from "./tokens";
import { uploadToOneDrive, type GraphEnv } from "./graph";
import { sendNotificationEmail, type EmailEnv } from "./email";
import {
  renderUploadForm,
  renderSuccessPage,
  renderErrorPage,
} from "./html";

type Env = GraphEnv &
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
  const maxFiles = parseInt(c.env.MAX_FILES || "12", 10);

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

  const files: Array<{ name: string; data: ArrayBuffer; size: number }> = [];
  for (const value of formData.getAll("files")) {
    if (!(value instanceof File)) continue;
    if (value.size === 0) continue;
    if (value.size > maxFileSize) {
      return c.html(
        renderErrorPage(
          `File "${value.name}" exceeds the ${(maxFileSize / 1024 / 1024).toFixed(0)} MB limit.`,
        ),
        413,
      );
    }
    const data = await value.arrayBuffer();
    files.push({ name: value.name, data, size: value.size });
  }

  if (files.length === 0) {
    return c.html(renderErrorPage("No files were uploaded."), 400);
  }
  if (files.length > maxFiles) {
    return c.html(
      renderErrorPage(`Too many files — max is ${maxFiles}.`),
      400,
    );
  }

  // Upload each file to OneDrive
  const uploadedFiles: Array<{ name: string; size: number }> = [];
  try {
    for (const f of files) {
      await uploadToOneDrive(c.env, request.folder_path, f.name, f.data);
      uploadedFiles.push({ name: f.name, size: f.size });
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "unknown error";
    return c.html(
      renderErrorPage(`Upload failed while writing to OneDrive: ${msg}`),
      500,
    );
  }

  // Mark token as used
  await markTokenState(c.env.TOKENS, token, "uploaded");

  // Fire notification email (non-blocking — log failure but don't fail the request)
  try {
    await sendNotificationEmail(c.env, request, uploadedFiles);
  } catch (e) {
    console.error(
      "Notification email failed:",
      e instanceof Error ? e.message : e,
    );
  }

  return c.html(renderSuccessPage(request, uploadedFiles));
});

// Catch-all for unknown paths
app.notFound((c) => c.html(renderErrorPage("Page not found."), 404));

export default app;
