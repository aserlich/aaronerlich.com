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
    max-width: 920px;
    margin: 2.5em auto;
    padding: 0 1.5em;
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
  input[type=text], input[type=url], input[type=date], input[type=time],
  select, textarea {
    width: 100%;
    padding: 0.5em 0.6em;
    font-family: inherit;
    font-size: 0.95em;
    border: 1px solid #ccc;
    border-radius: 3px;
    background: #fff;
    margin-top: 0.2em;
  }
  textarea { resize: vertical; min-height: 3em; }
  input:focus, select:focus, textarea:focus {
    outline: 2px solid var(--maroon);
    outline-offset: 0;
    border-color: var(--maroon);
  }
  fieldset.program-row {
    border: 1px solid var(--maroon);
    border-radius: 3px;
    padding: 0.8em 1.2em 1em;
    margin: 1em 0;
    background: #fff;
  }
  fieldset.program-row legend {
    color: var(--maroon);
    font-weight: 700;
    padding: 0 0.5em;
  }
  .program-row label {
    font-size: 0.9em;
    margin-top: 0.7em;
  }
  .program-row label.inline {
    display: inline-flex;
    align-items: center;
    gap: 0.4em;
    font-weight: 400;
  }
  .program-row label.inline input[type=checkbox] {
    width: auto;
    margin: 0;
  }
  .program-row .row-controls {
    margin-top: 1em;
    text-align: right;
  }
  .program-row button.remove-row {
    background: #fff;
    color: var(--maroon);
    border: 1px solid var(--maroon);
    padding: 0.4em 1em;
    font-size: 0.85em;
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
  button.add-program {
    background: #fff;
    color: var(--maroon);
    border: 1px dashed var(--maroon);
    padding: 0.6em 1.2em;
    font-size: 0.9em;
    margin-bottom: 1.2em;
  }
  button.add-program:hover { background: #fdf4f4; }
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
  const returningNote = req.returning
    ? `<p><em>This submission is for a new cycle of applications. Files will land alongside your previous cycle's materials, and I'll reuse what I remember about you from last time.</em></p>`
    : "";

  const inner = `
<h1>Letter of Recommendation — Submission</h1>

<p>Hi ${escapeHtml(req.first_name)},</p>

<p>This is your personalized submission link for the letter of recommendation I'm writing on your behalf. Please fill in the programs you're applying to and upload your materials below in a single submission — the link is single-use and tied to your application.</p>

${returningNote}

<form method="post" enctype="multipart/form-data" id="letter-form">
  <h2>Programs you're applying to</h2>
  <p>Fill in one section per program. Click "Add another program" if you're applying to more than one.</p>

  <div id="programs-container">
    ${renderProgramRow(0)}
  </div>

  <button type="button" class="add-program" id="add-program">+ Add another program</button>

  <h2>Materials to upload</h2>
  <p>All four documents below are required. PDF preferred (DOCX accepted). Max 50 MB per file. You don't need a separate "list of programs" file — the form above captures everything I need.</p>

  <fieldset class="program-row">
    <legend>1. Statement of purpose *</legend>
    <label>If you have <strong>different statements per program</strong>, combine them into a single ZIP file (or merge into one PDF labeled by program section). One file per slot.<input type="file" name="file_statement" accept=".pdf,.docx,.zip" required></label>
  </fieldset>

  <fieldset class="program-row">
    <legend>2. Transcript *</legend>
    <label>If you have <strong>multiple transcripts</strong> (e.g., undergrad + grad, or transcripts from multiple universities), combine them into a single PDF before uploading.<input type="file" name="file_transcript" accept=".pdf" required></label>
  </fieldset>

  <fieldset class="program-row">
    <legend>3. CV / résumé *</legend>
    <label>One page for undergraduates, up to two pages for MA students.<input type="file" name="file_cv" accept=".pdf,.docx" required></label>
  </fieldset>

  <fieldset class="program-row">
    <legend>4. Self-brief *</legend>
    <label>A 1–2 page document with specific anecdotes from our interactions, your career goals, and anything you'd like me to highlight. See <a href="https://aaronerlich.com/resources/letters.html" target="_blank">my letters page</a> for the full description of what to include.<input type="file" name="file_selfbrief" accept=".pdf,.docx" required></label>
  </fieldset>

  <input type="hidden" name="programs_json" id="programs_json" value="">

  <button type="submit" id="submit-btn">Submit programs + materials</button>
</form>

<p class="meta">This link is unique to you and can only be used once. Materials go directly to my secure OneDrive and are never visible publicly. If you run into trouble, email <a href="mailto:aaron.erlich@mcgill.ca">aaron.erlich@mcgill.ca</a>.</p>

<script>
(function () {
  var container = document.getElementById("programs-container");
  var addBtn = document.getElementById("add-program");
  var form = document.getElementById("letter-form");
  var rowTemplate = container.querySelector("fieldset.program-row").outerHTML;

  function renumberRows() {
    var rows = container.querySelectorAll("fieldset.program-row");
    rows.forEach(function (row, idx) {
      row.setAttribute("data-row", String(idx));
      var legend = row.querySelector("legend");
      if (legend) legend.textContent = "Program " + (idx + 1);
      var removeBtn = row.querySelector("button.remove-row");
      if (removeBtn) removeBtn.style.display = rows.length > 1 ? "" : "none";
    });
  }

  addBtn.addEventListener("click", function () {
    var wrapper = document.createElement("div");
    wrapper.innerHTML = rowTemplate;
    var fresh = wrapper.firstElementChild;
    // Clear any values carried over from the template HTML
    fresh.querySelectorAll("input, textarea, select").forEach(function (el) {
      if (el.type === "checkbox") {
        el.checked = false;
      } else if (el.tagName === "SELECT") {
        el.selectedIndex = 0;
      } else {
        el.value = "";
      }
    });
    container.appendChild(fresh);
    renumberRows();
  });

  container.addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.classList && t.classList.contains("remove-row")) {
      var rows = container.querySelectorAll("fieldset.program-row");
      if (rows.length > 1) {
        t.closest("fieldset.program-row").remove();
        renumberRows();
      }
    }
  });

  form.addEventListener("submit", function (e) {
    var rows = container.querySelectorAll("fieldset.program-row");
    var programs = [];
    rows.forEach(function (row) {
      var get = function (name) {
        var el = row.querySelector("[name='" + name + "']");
        return el ? el.value.trim() : "";
      };
      var checked = function (name) {
        var el = row.querySelector("[name='" + name + "']");
        return !!(el && el.checked);
      };
      programs.push({
        name: get("program_name"),
        institution: get("program_institution"),
        city: get("program_city"),
        deadline: get("program_deadline"),
        submission_method: get("program_submission_method"),
        portal_url: get("program_portal_url"),
        waived_right: checked("program_waived"),
        notes: get("program_notes")
      });
    });
    document.getElementById("programs_json").value = JSON.stringify(programs);
    // Validation: at least one program with required fields
    var hasValid = programs.some(function (p) {
      return p.name && p.institution && p.deadline && p.submission_method;
    });
    if (!hasValid) {
      e.preventDefault();
      alert("Please fill in at least one program with its name, institution, deadline, and submission method.");
      return false;
    }
    // Disable submit to prevent double-submission
    var btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "Uploading — please wait…";
  });

  renumberRows();
})();
</script>`;

  return wrap(`Letter submission — ${req.first_name} ${req.last_name}`, inner);
}

function renderProgramRow(idx: number): string {
  return `<fieldset class="program-row" data-row="${idx}">
    <legend>Program ${idx + 1}</legend>
    <label>Program name *<input type="text" name="program_name" required placeholder="e.g. DPhil in Politics"></label>
    <label>Institution *<input type="text" name="program_institution" required placeholder="e.g. University of Oxford"></label>
    <label>City / location<input type="text" name="program_city" placeholder="e.g. Oxford, UK"></label>
    <label>Deadline *<input type="date" name="program_deadline" required></label>
    <label>Submission method *
      <select name="program_submission_method" required>
        <option value="portal">Online portal — I already have the URL</option>
        <option value="portal_emailed">Online portal — Prof. Erlich will be emailed a link</option>
        <option value="email">Email (I'll give Prof. Erlich the address)</option>
        <option value="mail">Postal mail</option>
      </select>
    </label>
    <label>Portal URL (only if you already have it)<input type="url" name="program_portal_url" placeholder="https://…"></label>
    <label class="inline"><input type="checkbox" name="program_waived" value="1"> I waived my right to access this letter</label>
    <label>Program-specific requirements / notes<textarea name="program_notes" rows="2" placeholder="e.g. letter must be on letterhead, 1-page cap, submitted via Interfolio…"></textarea></label>
    <div class="row-controls">
      <button type="button" class="remove-row">Remove this program</button>
    </div>
  </fieldset>`;
}

export function renderSuccessPage(
  req: LetterRequest,
  files: Array<{ name: string; size: number; slot?: string }>,
): string {
  const fileList = files
    .map(
      (f) => {
        const tag = f.slot ? `<strong>${escapeHtml(f.slot)}:</strong> ` : "";
        return `<li>${tag}${escapeHtml(f.name)} <small style="color:#777">(${formatSize(f.size)})</small></li>`;
      },
    )
    .join("");

  const programList = (req.programs ?? [])
    .map(
      (p) =>
        `<li><strong>${escapeHtml(p.name)}</strong> — ${escapeHtml(p.institution)}, deadline ${escapeHtml(p.deadline)}</li>`,
    )
    .join("");

  const inner = `
<h1>Thank you, ${escapeHtml(req.first_name)}</h1>

<p>I've received your submission.</p>

<h2>Programs</h2>
<ul>${programList}</ul>

<h2>Files uploaded</h2>
<ul>${fileList}</ul>

<p>I'll reach out when I have a draft ready or if I need anything else. Best of luck with your applications.</p>

<p>— Prof. Erlich</p>

<p class="meta">You can close this tab. A confirmation has been logged — I don't send automated replies, but I'll email you personally when the letters are on their way.</p>`;

  return wrap("Submission received — thank you", inner);
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
