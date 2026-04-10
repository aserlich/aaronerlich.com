// HTML templates for the upload form and response pages.
// Styled to match the aaronerlich.com aesthetic (Space Mono typography,
// maroon accent, minimal chrome).

import type { LetterRequest } from "./tokens";

const commonStyles = `
  @import url("https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap");
  :root { --maroon: #6b1b1b; }
  * { box-sizing: border-box; }
  body {
    font-family: "Space Mono", ui-monospace, Menlo, monospace;
    max-width: 680px;
    margin: 2.5em auto;
    padding: 0 1.2em;
    color: #222;
    background: #fafafa;
    line-height: 1.55;
  }
  h1 {
    color: var(--maroon);
    border-bottom: 2px solid var(--maroon);
    padding-bottom: 0.3em;
    margin-bottom: 1em;
  }
  h2 { color: var(--maroon); font-size: 1.1em; margin-top: 1.5em; }
  p { margin: 0.8em 0; }
  ul, ol { padding-left: 1.5em; }
  li { margin: 0.3em 0; }
  form {
    background: #fff;
    padding: 1.5em;
    border: 1px solid #ddd;
    border-radius: 4px;
    margin: 1.5em 0;
  }
  label {
    display: block;
    margin: 1em 0 0.4em;
    font-weight: 700;
  }
  input[type=file] {
    margin: 0.3em 0 1em;
    width: 100%;
    padding: 0.5em;
    background: #f7f7f7;
    border: 1px dashed #aaa;
    border-radius: 3px;
  }
  button {
    background: var(--maroon);
    color: #fff;
    border: 0;
    padding: 0.8em 1.8em;
    border-radius: 3px;
    font-family: inherit;
    font-size: 1em;
    font-weight: 700;
    cursor: pointer;
  }
  button:hover { background: #8a2828; }
  .checklist {
    background: #fff8e1;
    padding: 1em 1.5em;
    border-left: 4px solid #e0c060;
    margin: 1em 0;
  }
  .meta {
    color: #666;
    font-size: 0.9em;
    margin-top: 2em;
    border-top: 1px solid #ddd;
    padding-top: 1em;
  }
  .error { background: #fde8e8; border-left: 4px solid #c44; padding: 1em 1.5em; }
`;

function wrap(title: string, inner: string): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>${escapeHtml(title)}</title>
  <style>${commonStyles}</style>
</head>
<body>
${inner}
</body>
</html>`;
}

export function renderUploadForm(req: LetterRequest): string {
  const programs =
    (req.programs ?? [])
      .map(
        (p) =>
          `<li><strong>${escapeHtml(p.name)}</strong>${
            p.deadline ? ` — deadline ${escapeHtml(p.deadline)}` : ""
          }</li>`,
      )
      .join("") || "<li><em>No specific programs listed</em></li>";

  const returningNote = req.returning
    ? `<p><em>This is a re-upload for materials building on my prior letter for you. New files will land alongside the previous cycle's materials.</em></p>`
    : "";

  const inner = `
<h1>Letter of Recommendation — Material Upload</h1>

<p>Hi ${escapeHtml(req.first_name)},</p>

<p>This is your personalized upload link for the letter of recommendation I'm writing on your behalf. Please upload the materials below in a single submission — the link is single-use and tied to your application.</p>

${returningNote}

<h2>Programs I'm writing for</h2>
<ul>${programs}</ul>

<div class="checklist">
<strong>Please upload (one submission, ideally):</strong>
<ol>
  <li><strong>Statement of purpose</strong> — one per program if they differ</li>
  <li><strong>Unofficial transcript</strong></li>
  <li><strong>Your CV / résumé</strong></li>
  <li><strong>A "self-brief"</strong>: a short document (1–2 pages) with specific anecdotes from our interactions, career goals, and anything you'd like me to highlight. See <a href="https://aaronerlich.com/resources/letters.html" target="_blank">my letters page</a> for details on what to include.</li>
  <li><strong>A list of programs + deadlines</strong> (spreadsheet or document) — so I submit to the right places by the right dates</li>
</ol>
</div>

<form method="post" enctype="multipart/form-data">
  <label for="files">Select files (up to 12, 50 MB each):</label>
  <input type="file" name="files" id="files" multiple required>
  <button type="submit">Upload materials</button>
</form>

<p class="meta">This link is unique to you and can only be used once. Materials go directly to my secure OneDrive and are never visible publicly. If you run into trouble, email <a href="mailto:aaron.erlich@mcgill.ca">aaron.erlich@mcgill.ca</a>.</p>`;

  return wrap(`Letter upload — ${req.first_name} ${req.last_name}`, inner);
}

export function renderSuccessPage(
  req: LetterRequest,
  files: Array<{ name: string; size: number }>,
): string {
  const fileList = files
    .map(
      (f) =>
        `<li>${escapeHtml(f.name)} <small style="color:#777">(${formatSize(f.size)})</small></li>`,
    )
    .join("");

  const inner = `
<h1>Thank you, ${escapeHtml(req.first_name)}</h1>

<p>I've received your materials:</p>
<ul>${fileList}</ul>

<p>I'll reach out when I have a draft ready or if I need anything else. Best of luck with your applications.</p>

<p>— Aaron Erlich</p>

<p class="meta">You can close this tab. A confirmation has been logged — I don't send automated replies, but I'll email you personally when the letters are on their way.</p>`;

  return wrap("Upload received — thank you", inner);
}

export function renderErrorPage(message: string, status = 400): string {
  const inner = `
<h1>Something went wrong</h1>
<div class="error">
  <p>${escapeHtml(message)}</p>
</div>
<p>Please email <a href="mailto:aaron.erlich@mcgill.ca">aaron.erlich@mcgill.ca</a> with the message above. Status code: ${status}.</p>`;

  return wrap("Upload error", inner);
}

function escapeHtml(s: string): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
