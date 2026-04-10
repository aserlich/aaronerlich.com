# Workplan: Letter of Recommendation page

**Target**: `resources/letters.qmd`
**Current state**: 26-line stub (materials list + example spreadsheet table)
**Not yet**: linked in navbar, translated, or aligned with the lab page

---

## Why improve it

A well-built letter-request page saves you time per student and produces better letters:

1. **Reduces back-and-forth email** — every clarifying question ("what should my SoP include?", "what format for the spreadsheet?", "when do you need this by?") is a question you shouldn't have to answer twice.
2. **Filters self-eligibility** — students who shouldn't ask you can self-select out, sparing you the awkward "I can't write you a strong letter" conversation.
3. **Improves letter quality** — you get the raw material you need (specific anecdotes, goals, coursework) in a structured form instead of whatever the student thinks to include.
4. **Sets expectations on lead time** — reduces last-minute panic requests.
5. **Signals care** — students notice when a page is thoughtful, and treat the request with corresponding seriousness.

---

## Target audiences (in priority order)

1. **Undergraduates applying to graduate school** (the main case — McGill undergrads you've had in POLI 311/421/422 or who worked as lab RAs)
2. **M.A. students applying to Ph.D. programs** (secondary — lab members, thesis supervisees)
3. **Former lab members / mentees applying to fellowships, postdocs, or jobs years later**
4. **Non-academic letters** (rare — policy internships, think-tank jobs) — worth a one-line mention so they don't wonder if it's appropriate

---

## Proposed page structure

Each section below is what I'd draft; substance requires your input where marked **[needs Aaron]**.

### 1. When and how to ask
- Minimum lead time **[needs Aaron: 3 weeks? 4? 6 for fellowships?]**
- How to make the initial inquiry (one-paragraph email with X, Y, Z)
- What you'll respond with if you agree
- Seasonal capacity signal ("I am at capacity during October–December; plan accordingly")

### 2. Am I the right letter writer for you?
A self-assessment section that helps students decide whether you're a strong choice, framed as questions:

- Have you taken a course with me and received a grade I can reference substantively?
- Have we had substantive interactions beyond class (office hours, research work, thesis)?
- Does the program care about the skills I can speak to (quant methods, post-Soviet politics, misinformation, field research)?
- Do you have at least one stronger option (e.g., your honours supervisor, someone with whom you've done sustained research)?

Optional: a short "I will probably not be your strongest writer if..." list — **[needs Aaron: do you want to include this? The alternative is letting students figure it out themselves, which is what most pages do but leads to more letters-of-convenience]**

### 3. Materials needed — with *why*

The current list is just materials. Each should come with 1-2 sentences on **why** you need it, so students see the point:

- **Statement of purpose** — so I can tie my letter to the specific story you're telling admissions committees, not a generic "good student" letter
- **Unofficial transcript** — so I can anchor specific grades / courses I can speak to
- **Program spreadsheet** — so I submit through the right portals on the right dates without asking you twice
- **Self-brief** (or "what to include") — a short doc (≤2 pages) with:
  - Three specific moments in class/lab/office hours you want me to reference
  - Your career goals and how this program fits
  - What about you I should emphasize that the SoP doesn't cover
  - Any weaknesses to pre-empt (a dropped grade, a gap year, an unusual path)
  - Your cumulative GPA + any specific courses you want highlighted
- **CV / résumé** — current one-pager
- **Deadlines in UTC or your local time** with explicit time-of-day (not just the date)

### 4. Spreadsheet template — downloadable, not just a markdown table

Current page shows a markdown table. Much better: a downloadable `.xlsx` or CSV template in `files/` with columns pre-filled for:

| Program | Institution | City | Type | Deadline (date + time + TZ) | Submission method | Portal URL | Portal email | Letter upload link | Portal opens | Materials needed | Notes |

**[needs Aaron: do you want me to ship a filled-in example template with the page?]**

### 5. Process and timeline
A clear sequence:

1. Initial inquiry (minimum N weeks before first deadline)
2. Aaron agrees / declines (within 3 business days)
3. Student sends materials (by date X)
4. Aaron drafts letter (Y days before first deadline)
5. Aaron submits (or the student uploads if portal permits)
6. Student confirms receipt (and thanks)
7. Student reports outcomes

### 6. Post-submission responsibilities (the student's side)
Students often don't know these norms. Spell them out:

- Reply confirming each submission has gone through
- Send a brief outcome update (accepted / rejected / waitlisted) — not for ego reasons, but because it helps Aaron write better letters for future students
- Send a thank-you note (not a gift — just a note)
- Add Aaron to LinkedIn / keep in touch years later; professors like hearing what happened to people

### 7. FAQ
Anticipate: *How many letters are too many?* *Can you write me letters in French?* *Can I reuse the same letter for multiple programs?* *What if I forgot to list a program?* *Can you write a non-academic letter?* *What if my deadline is in < 2 weeks?* *Can I see the letter?* *Do you write waiver-not-signed letters?*

### 8. What makes a strong letter (optional, educational)

A short honest section explaining what a letter actually contains — specific evidence, concrete anecdotes, comparative claims ("top 5% I've supervised"). Helps students understand why "I had Prof. X for one course and got an A-" is not enough on its own.

---

## Open questions only you can answer

1. **Lead time**: minimum weeks for grad school vs. fellowships? Any hard cut-off below which you decline?
2. **Self-brief format**: do you want it as a freeform document, a structured template (Word / Google Doc), or a form (Typeform / Google Form)? The form has the advantage of forced-structured input.
3. **"Don't ask me if…" section**: include it, or leave students to self-filter? (Including it is more honest but can come across as gatekeeping.)
4. **French version**: McGill is bilingual and francophone students might want a letter in French. Do you write letters in French? If so, mention it on the page. If not, also worth saying (so francophone students know to ask someone else).
5. **Programs you don't know**: any programs or fields you'd prefer not to write for (e.g., pure economics PhDs, JDs, unfamiliar area studies)?
6. **Rate limiting**: do you have a cap (e.g., "I take no more than 10 letter-students per cycle")? Worth stating.
7. **Lab member distinction**: should lab members have a different (faster / less formal) process than cold-course-student requests?
8. **Template statement of purpose**: do you want to include an example (anonymized) of a strong SoP? Or link to one?
9. **Integration with lab page**: should the `lab.qmd` mentee list link back to this page for former members who need letters years later?
10. **Downloadable materials**: happy to ship `files/letter-request-template.xlsx`, a `letter-request-self-brief.docx` template, and possibly a sample CV. Do you have existing templates you've been sharing by email that I should work from?

---

## Proposed implementation steps

1. **You answer the 10 open questions above** (~30 min, ideally just as bullet points in a follow-up)
2. **I draft the new `resources/letters.qmd`** incorporating your answers — single-page, clear sectioning, downloadable assets
3. **I create template files** in `files/`:
   - `letter-request-programs.xlsx` (spreadsheet template)
   - `letter-request-self-brief.docx` (self-brief template, if you want structured)
4. **I add a structured Google Form** as an *optional* alternative for students who prefer that over email — form output lands in your inbox in a predictable format **[needs Aaron: only if you want this]**
5. **I wire the page into the navbar** under a "Resources" dropdown (restore the commented entry in `_quarto.yml`)
6. **I add i18n markers** so the translation pipeline can produce a French version — same mechanism as the CV page
7. **I link from `lab.qmd`** with a short note for alumni ("if you need a letter later, start here")
8. **I run `quarto render` and verify** the page renders cleanly

## Success criteria

- A student can read the page once and have everything they need to make a complete submission
- You receive zero "what exactly do you mean by…" emails after a student reads the page
- The page handles 90% of the "can you write me a letter" email traffic without you having to respond beyond "yes/no + go to the page"
- Former lab members years out know where to start
- French-speaking students know whether to ask you

## Nice-to-haves (later)

- Letter-tracking spreadsheet template for **you** (not the student) — keeps track of "who asked, what I agreed to, deadlines, whether I've submitted"
- Obsidian template for per-student letter notes (linked to the lab member note if applicable)
- Anonymized sample letter sections (the kind of sentences you include, with identifying info stripped) so students understand the level of specificity a good letter requires
- A "letters I've written" internal stat for your annual review reporting

---

## Not in scope

- The page will not promise specific outcomes
- The page will not include specific grade thresholds (too legally fraught)
- The page will not publicly list students who've received letters (privacy)
- The page will not include a "rate my chances" section (not your job to predict admissions outcomes)
