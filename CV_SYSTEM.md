# CV Pipeline — Operations Manual

This document is the reference for how the multilingual CV at
`aaronerlich.com/cv.html` (and the Overleaf LaTeX CV) is built. It
covers: the source-of-truth architecture, the daily workflow, how to
handle accepted/forthcoming papers, how to run the Python tools
**without Claude**, multilingual conventions, and troubleshooting.

Your future self is the intended reader.

Last substantive update: 2026-04-20.

---

## What the CV pipeline does

Two rendered outputs from a single source of truth:

1. **Web CV** — `aaronerlich.com/cv.html`, 7 languages (en/fr/es/ru/uk/ka/de)
   with an in-page language toggle. Built from Quarto.
2. **LaTeX CV** — Overleaf project `Erlich_CV_Version_Control`,
   English only, traditional academic PDF. Built from LaTeX via
   Overleaf's auto-compile.

Both outputs read from the **same three sources**:

- `_data/cv.yml` — all non-publication content (contact, appointments,
  affiliations, education, grants, software, teaching, mentorship,
  etc.), plus `under_review`, `in_prep`, `on_hold` as plain-text lists.
  Multilingual — every translatable string has 7 language fields.
- `_data/cv-tag-proposal.yml` — the bridge file between Zotero and the
  CV. Lists each publication by section (`peer-reviewed`,
  `editor-reviewed`, `book-review`, `blog`, `working-paper`) with its
  Zotero citekey, LaTeX title, extracted annotations (awards, media
  coverage, press releases), and optionally a `latex_status` field
  (see "Forthcoming papers" below).
- `~/Dropbox/research_projects/My Library.json` — Better BibTeX CSL
  JSON export of Zotero. Full metadata for each publication
  (authors, DOI, venue, volume, issue, pages, year). Publications
  selected for the CV are tagged in Zotero with `cv:include` plus a
  section tag like `cv:section/peer-reviewed`.

---

## End-to-end architecture

```
  Zotero (~/Dropbox/research_projects/My Library.json)
      │ cv:include + cv:section/<name> tags
      ▼
  _data/cv-tag-proposal.yml  ←── scripts/apply-tags.py
      │ (citekey → section, annotations, latex_status?)
      ▼
  ┌──────────────────────┐      ┌──────────────────────────┐
  │  scripts/build-cv.py │      │ scripts/build-cv-latex.py│
  │  YAML + Zotero → HTML│      │ YAML + Zotero → LaTeX    │
  └──────────┬───────────┘      └──────────┬───────────────┘
             │                             │
             ▼                             ▼
      cv.qmd                       _generated/cv_publications.tex
      │  (quarto render)           │
      ▼                            ▼
      docs/cv.html          ~/Dropbox/Apps/Overleaf/
      │                     Erlich_CV_Version_Control/
      │                     cv_publications.tex
      │                            │
      │                            ▼
      │                     Overleaf auto-compile
      │                            │
      ▼                            ▼
  aaronerlich.com/cv.html   Overleaf PDF

  _data/cv.yml ─────────────────┐
      │ non-publication content │ (appointments, education, grants,
      │                         │  testimony, teaching, mentorship, …)
      └─────────────────────────┘
                │
                ├──▶ build-cv.py (HTML)
                └──▶ main.tex on Overleaf (hand-maintained; issue #4
                     tracks extending build-cv-latex.py to cover these)

  _data/site-i18n.yml ─▶ scripts/build-i18n.py ─▶ _generated/i18n-toggle.html
                                                   (loaded site-wide
                                                    via _quarto.yml
                                                    include-after-body)
```

---

## Where each piece lives

### Build scripts (`scripts/`)

| Script | What it does |
|---|---|
| `build-cv.py` | Reads cv.yml + cv-tag-proposal.yml + Zotero JSON → writes `cv.qmd`. This is the Quarto source for the web CV. |
| `build-cv-latex.py` | Same inputs → writes `_generated/cv_publications.tex` AND copies to `~/Dropbox/Apps/Overleaf/Erlich_CV_Version_Control/cv_publications.tex`. Overleaf picks up the change via its Dropbox sync. |
| `build-lab.py` | Reads lab.yml → writes `lab.qmd`. |
| `build-i18n.py` | Walks cv.yml + site-i18n.yml, emits JSON blob for the language toggle. |
| `translate-cv.py` | Fills missing-language fields in cv.yml via Claude Sonnet 4.6. Hash-cached in `_data/_translation_cache.json`. |
| `apply-tags.py` | Writes `cv:include` + `cv:section/*` tags to Zotero via the Web API. Adds `tex.cv-*` annotation lines to the Zotero `extra` field (for archival parallel — the build pipeline reads annotations from cv-tag-proposal.yml, not from Zotero extra). |
| `cv-add.py` | CLI for adding a new publication by citekey/DOI. |
| `cv_admin.py` | Flask web app at `http://localhost:5000` — edits most sections with a UI. |
| `parse-cv-to-zotero-tags.py` | One-time bootstrap parser that reads `_data/cv_source.tex` and proposes tags. Mostly historical. |

### Data (`_data/`)

| File | Role |
|---|---|
| `cv.yml` | Non-publication CV content, 7-language. Source of truth for contact, appointments, affiliations, education, grants, software, professional evaluations, testimony, field research, skills, presentations, teaching, mentorship, professional experience, professional service, other service, plus the `under_review` / `in_prep` / `on_hold` plain-text lists and the `section_headers` / `labels` translation strings. |
| `cv-tag-proposal.yml` | Publication roster — one entry per CV publication with `match_citekey`, `latex_title`, `latex_annotations`, optional `latex_status`. |
| `site-i18n.yml` | Translatable strings for index/navbar (not CV). |
| `institution-names.yml` | Registry of institutions with bespoke multilingual overrides (CSDC ↔ CÉCD, Université McGill, etc.), plus a `titles:` registry for academic ranks. |
| `_translation_cache.json` | Content-hash cache for the translation pipeline. Regenerating is cheap — blow it away if corruption suspected. |
| `cv_source.tex` | Copy of the Overleaf main.tex — the **format specification** for the LaTeX CV. Do NOT edit as content; it's the blueprint that build-cv-latex.py mirrors. |

### Generated outputs

| Path | Written by | Lifespan |
|---|---|---|
| `cv.qmd` | `build-cv.py` | Regenerated on every CV edit |
| `docs/cv.html` | `quarto render cv.qmd` | Committed for GitHub Pages |
| `_generated/cv_publications.tex` | `build-cv-latex.py` | Committed to the repo |
| `~/Dropbox/Apps/Overleaf/Erlich_CV_Version_Control/cv_publications.tex` | Same run | Lives outside the repo; syncs to Overleaf |
| `_generated/i18n-toggle.html` | `build-i18n.py` | Committed; loaded site-wide |

### External resources

| Thing | Where |
|---|---|
| Zotero library | `~/Dropbox/research_projects/My Library.json` (Better BibTeX CSL JSON export) |
| Zotero web API key | `~/.config/zotero/api_key` (mode 600) |
| Zotero user ID | `38708` |
| Anthropic API key (for translate-cv.py) | `~/.config/anthropic/api_key` (mode 600) |
| Overleaf CV project folder | `~/Dropbox/Apps/Overleaf/Erlich_CV_Version_Control/` |

---

## Running the tools WITHOUT Claude

Every command below is copy-pasteable. Run them from the repo root:

```bash
cd ~/Dropbox/admin_projects/aaronerlich.com
```

### Starter: rebuild everything and preview locally

```bash
python3 scripts/build-cv.py          # cv.yml + Zotero → cv.qmd
python3 scripts/build-lab.py         # lab.yml → lab.qmd
python3 scripts/build-i18n.py        # cv.yml + site-i18n.yml → i18n JSON blob
python3 scripts/build-cv-latex.py    # → _generated/cv_publications.tex + Overleaf folder
quarto render                        # all .qmd → docs/*.html

# Serve locally so you can eyeball changes before pushing
python3 -m http.server -d docs 8765  # → http://localhost:8765/cv.html
```

### Flask admin (point-and-click editor for most sections)

```bash
python3 scripts/cv_admin.py          # → http://localhost:5000
```

Open the URL in a browser. Sections editable through the UI:
presentations, grants, teaching, mentorship, professional experience,
service, other service, under_review, in_prep, on_hold, lab members,
letter-of-rec requests. Each has a "Rebuild & Preview" button that
runs `build-cv.py` + `build-lab.py` + `quarto render` for you.

### Translate new or edited strings

```bash
# Fill all 6 non-English fields for any strings that are blank or changed
python3 scripts/translate-cv.py

# Limit to one language
python3 scripts/translate-cv.py --lang fr

# Force-translate even if the cache already has an entry for this string
python3 scripts/translate-cv.py --force

# Translate site-i18n.yml instead of cv.yml
python3 scripts/translate-cv.py --file _data/site-i18n.yml
```

The script is content-hash cached — re-runs are free for unchanged
strings; only new/changed English strings hit the Claude API.

### Add a new publication

**If the paper is already in Zotero:**

1. Open Zotero, find the item, right-click → **Add Tags** → type
   `cv:include` and one of:
   `cv:section/peer-reviewed`,
   `cv:section/editor-reviewed`,
   `cv:section/book-review`,
   `cv:section/blog`,
   `cv:section/working-paper`
2. Export the updated library:
   - Zotero → right-click "My Library" → **Export Library**
   - Format: **Better BibTeX CSL JSON**
   - Save as `~/Dropbox/research_projects/My Library.json` (overwrite)
3. Sync the proposal bridge from your Zotero tags:
   ```bash
   python3 scripts/sync-proposal-from-zotero.py            # preview
   python3 scripts/sync-proposal-from-zotero.py --commit   # apply
   ```
   This reads Zotero's Web API, finds every item tagged `cv:include`,
   matches citekeys against your local BBT export, and updates
   `_data/cv-tag-proposal.yml` — adds new entries, moves between
   sections when the section tag changes, preserves any curated
   fields (`latex_annotations`, `latex_status`, etc.) on existing
   entries.
4. Rebuild:
   ```bash
   python3 scripts/build-cv.py && python3 scripts/build-cv-latex.py && quarto render cv.qmd
   ```
5. Commit and push.

**Alternative**: skip steps 1-3 and hand-edit `_data/cv-tag-proposal.yml`
directly. The sync is a convenience — the yml file is the
authoritative source for the build.

**If the paper is NOT yet in Zotero:**

1. Add it to Zotero first (via DOI lookup, manual entry, or a PDF import).
2. Tag it as above and follow the rest of the flow.

**Zotero hygiene notes:**

- The sync script expects each paper to have **one** Zotero entry
  with a proper BBT citekey. Duplicates (same title, multiple
  entries) confuse the matcher, which falls back to title-lookup
  against the BBT export.
- If you see weird citekeys like `__b` or `_ElderAm_` showing up in
  the sync preview, those are stub entries in Zotero (no author or
  year set). Fill them in or delete the duplicates in Zotero, then
  re-export the BBT JSON and re-sync.
- BBT needs to be configured with `Citation Key: <ck>` lines in the
  Extra field to make the matcher reliable; without it the fallback
  is title-based (works for unique titles, breaks for dup titles).

### Handle an accepted / forthcoming paper

When a paper is accepted but has no publication date yet, it should
appear at the **top** of its section in the CV, with "Forthcoming."
(or "Accepted" / "In Press" / "Online First") in place of the year.

**Convention:**

1. In `_data/cv-tag-proposal.yml`, find the paper's entry (or add a
   new one per the "Add a new publication" flow above) and add a
   single line:
   ```yaml
   - match_citekey: smith_FuturePaper_2026
     latex_title: "Title of the Accepted Paper"
     proposed_tags: [cv:include, cv:section/peer-reviewed]
     latex_status: Forthcoming   # ← this line pins to top + prints "Forthcoming."
   ```
   Values you can use for `latex_status` (all render as-is with a
   trailing period):
   - `Forthcoming` — safe default
   - `Accepted` — after acceptance notice, before any official listing
   - `In Press` — after copy-edit / typesetting, before issue assignment
   - `Online First` — journal convention for early online publication
     (AJPS uses this; match what your journal says)
2. Optional: in the Zotero `Extra` field on the same item, add a line
   `tex.cv-status: Forthcoming` for archival parallel. The build
   pipeline doesn't read this — the proposal yml entry is authoritative
   — but it keeps Zotero internally consistent with the CV if you ever
   look at the item there.
3. Rebuild and push:
   ```bash
   python3 scripts/build-cv.py && python3 scripts/build-cv-latex.py && quarto render cv.qmd
   git add _data/cv-tag-proposal.yml cv.qmd docs/cv.html _generated/cv_publications.tex
   git commit -m "Add forthcoming paper: smith_FuturePaper_2026"
   git push
   ```

**Once the paper has a real date:**

1. Update the Zotero item: set the `Date` field, fill in volume/issue/
   pages.
2. Re-export Zotero library to `My Library.json`.
3. **Remove** `latex_status` from the cv-tag-proposal.yml entry.
4. Rebuild and push — the paper now slots into normal chronological
   position.

### Daily workflow (typical edit cycle)

```bash
cd ~/Dropbox/admin_projects/aaronerlich.com
python3 scripts/cv_admin.py &          # Flask UI on :5000
python3 -m http.server -d docs 8765 &  # preview on :8765

# Edit via the Flask UI (or edit cv.yml / cv-tag-proposal.yml by hand)

# When ready, from the Flask UI click "Rebuild & Preview".
# Or from terminal:
python3 scripts/build-cv.py
python3 scripts/build-lab.py
python3 scripts/build-cv-latex.py
python3 scripts/build-i18n.py    # only if cv.yml translatable strings changed
quarto render

# Review at http://localhost:8765/cv.html
# When satisfied:
git add _data/ cv.qmd lab.qmd _generated/ docs/ _data/cv-tag-proposal.yml
git commit -m "CV update: <what changed>"
git push    # → GitHub Pages redeploys within ~60 seconds
```

---

## Multilingual conventions

### Supported languages

`en fr es ru uk ka de` — English, French, Spanish, Russian, Ukrainian,
Georgian (Mkhedruli), German.

English is canonical. Other languages are filled in by
`scripts/translate-cv.py` (Claude Sonnet 4.6). Translations are
content-hash cached so re-runs only hit the API for new/changed strings.

### YAML schema for translatable nodes

A translatable leaf is any dict whose keys are all language codes:

```yaml
contact:
  title:
    en: "Associate Professor"
    fr: "Professeur agrégé"
    es: "Profesor agregado"
    ru: "Доцент"
    uk: "Доцент"
    ka: "ასოცირებული პროფესორი"
    de: "Professor"
```

`build-cv.py` detects these, wraps the English rendering in
`<span data-i18n="contact.title">` so the JS toggle can swap text on
the fly without a reload.

### DOM attributes

- `data-i18n="key"` — text-only, uses `textContent`. Safe default.
- `data-i18n-html="key"` — HTML-allowed, uses `innerHTML`. Use when
  the translation must contain inline markup like `<em>` (e.g.,
  italicized journal names). YAML values for these keys may contain
  HTML; since the source is trusted YAML, XSS isn't a concern.

### What NEVER gets translated

- Publication titles (journal articles, books)
- Journal names (italicized via `data-i18n-html` but always in English)
- Person names
- DOIs, URLs, citekeys
- Program-name acronyms (CAnD3, SSHRC, FRQSC)
- Project-acronym grant titles

### What ALWAYS gets translated

- Role titles, degree names, section headers, UI labels
- Narrative descriptions (welcome paragraph, lab bio)
- Country names
- Generic connector words ("with" for coauthor attributions, "Winner"
  award label, etc.)

### Institution names with bespoke multilingual forms

Some institutions have a genuine local-language name that should be
used instead of the English one. These live in
`_data/institution-names.yml`. Examples:

- **Centre for the Study of Democratic Citizenship** (en) ↔
  **Centre pour l'étude de la citoyenneté démocratique** (fr) —
  bilingual centre, CSDC ↔ CÉCD
- **McGill University** (en) ↔ **Université McGill** (fr) —
  officially bilingual
- **University of Washington** (en) ↔ **Université de Washington /
  Universidad de Washington / Университет Вашингтона / …** —
  universities get their generic word translated

When you encounter a new institution with an official multilingual
form, add it to `institution-names.yml` and re-run
`translate-cv.py --force`.

---

## CV rendering conventions

Web CV matches the LaTeX CV layout:

- **Numbered (reverse, etaremune-style)**: peer-reviewed, under-review,
  editor-reviewed — `.cv-pub-list.cv-pub-list--reverse` with
  `--cv-pub-start` CSS variable.
- **Dash bullets (em-dash)**: book-reviews, blogs, working papers,
  in-prep, on-hold, professional evaluations — `.cv-pub-list--dash`.
- **Collapsible sections** (HTML-only, closed by default): everything
  after Testimony (presentations, teaching, mentorship, professional
  experience, skills, field research, professional service, other
  service). Wrapped in `<details class="cv-section-collapse">`. The
  PDF render shows everything.
- **Title coloring**: maroon `#6b1b1b` only on `<a class="cv-pub-title">`
  (linked titles). Plain-text titles use `.cv-pub-title-plain`.
- **Annotation lines under publications**: `<ul class="cv-pub-notes">`
  with `<li class="cv-pub-award">` or `<li class="cv-pub-media">`.
  Built by the renderer from `latex_annotations` in the proposal file.
- **Forthcoming / Accepted status**: rendered as
  `<span class="cv-pub-status">Forthcoming.</span>` instead of the
  year. Sorts to top of section.

---

## Flask admin routes

`scripts/cv_admin.py` serves at `http://localhost:5000`:

- `/section/<name>` — generic CRUD for any simple section (grants,
  teaching, mentorship, presentations, etc.)
- `/section/under_review/publish/<idx>` — promote an under-review entry
  to a published Zotero-tracked publication
- `/publications` — list all tagged pubs
- `/publications/<citekey>/annotate` — add a `tex.cv-*` annotation
  line directly to Zotero via the Web API
- `/lab` — lab member management
- `/lab/<group>/promote/<idx>` — promote current lab member to alumni
  (also syncs `placement` field back to cv.yml mentorship for PoliSci
  students)
- `/letters` — letter-of-rec dashboard (see `LETTER_SYSTEM.md`)
- `/rebuild` — runs `build-cv.py` + `build-lab.py` +
  `quarto render cv.qmd lab.qmd`

The Flask app **auto-bumps `meta.last_updated.en`** to today's date on
every save to cv.yml. Other-language dates stay stale until
`translate-cv.py` is re-run (cheap, usually done as a batch).

---

## Commit and deploy

```bash
git push origin main
```

pushes to `main`, which triggers GitHub Pages to redeploy from `docs/`
within ~60 seconds. **The `docs/` directory is committed** — Quarto
writes rendered HTML there, and GH Pages serves from `/docs`.

Always include rendered `docs/*.html` files in commits that change
content, otherwise the live site drifts from the source.

Stage specifically — **never `git add -A`**. Risks accidentally
committing `scripts/__pycache__/`, `*.api_key`, `_translation_cache.json`
backup files, etc. The `.gitignore` excludes the common hazards.

The load-bearing file `docs/CNAME` (contains `aaronerlich.com`) is
cleared by `quarto render` and needs restoring after every full render:

```bash
quarto render
git checkout HEAD -- docs/CNAME   # restore the custom-domain marker
```

---

## Troubleshooting

### "quarto render wiped my docs/ folder"

Quarto clears `docs/` on each full render. `docs/CNAME` (the custom
domain marker for GitHub Pages) is the only file you'll notice missing.
Restore with `git checkout HEAD -- docs/CNAME`.

### "The CV still shows my old title"

The page uses a client-side language toggle — check which language the
browser picked. The English source is in `cv.yml`; translations are in
cv.yml too. If you edited the English, the i18n JSON blob needs
regenerating: `python3 scripts/build-i18n.py`. If the browser is
caching an old version, hard-reload (Cmd-Shift-R).

### "A publication I tagged in Zotero isn't showing up"

The build pipeline reads from `_data/cv-tag-proposal.yml`, not directly
from Zotero. Tagging in Zotero alone isn't enough. You need to either:

1. Re-export `~/Dropbox/research_projects/My Library.json` AND edit
   cv-tag-proposal.yml by hand to add the new entry under the right
   section, OR
2. Use `python3 scripts/cv-add.py --citekey <citekey> --section <name>`
   which does both in one step, OR
3. Use the Flask admin's publication tools (browse `/publications`,
   add tags through the UI).

### "The Overleaf LaTeX CV didn't update"

1. Verify the generator wrote into the Overleaf folder:
   `ls -lh ~/Dropbox/Apps/Overleaf/Erlich_CV_Version_Control/cv_publications.tex`
   — mtime should be recent.
2. Check that Dropbox is syncing — the Dropbox menu-bar icon should
   say "Up to date". If paused, resume it.
3. Reload the Overleaf web editor. Overleaf should detect the file
   change and offer to compile. If not, force a compile.
4. The one-time requirement: `main.tex` on Overleaf must contain
   `\input{cv_publications}` where the inline publication sections
   used to live. If you haven't done that yet, the regenerated
   `cv_publications.tex` is just sitting in the project tree unused.

### "Translation cache is corrupted / translations look wrong"

Blow the cache:

```bash
rm _data/_translation_cache.json
python3 scripts/translate-cv.py --force
```

Runs every non-English string through the API. Takes a few minutes
and costs a few cents.

### "The language toggle is gone"

`_generated/i18n-toggle.html` has to exist and be referenced in
`_quarto.yml` under `include-after-body`. If either is missing,
regenerate with `python3 scripts/build-i18n.py`.

### "Forthcoming paper sorted to the bottom instead of the top"

Check the cv-tag-proposal.yml entry — `latex_status` must be a
non-empty string. Empty string `""` is treated as no-status. Also
check that you actually rebuilt after editing
(`python3 scripts/build-cv.py && python3 scripts/build-cv-latex.py`).

---

## Reference files

- `CLAUDE.md` — overall website architecture notes (separate from
  this CV-focused doc)
- `LETTER_SYSTEM.md` — documentation for the letter-of-rec intake
  system (separate pipeline)
- `_planning/` — stray planning docs kept for historical reference;
  not authoritative
- `_data/cv_source.tex` — copy of Overleaf main.tex, kept as a format
  spec / diff target
