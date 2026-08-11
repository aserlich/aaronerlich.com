# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Aaron Erlich's academic website at https://aaronerlich.com. Quarto static site deployed via GitHub Pages (custom domain via `docs/CNAME` — **load-bearing, never delete**). Core feature: the CV page is generated from structured YAML + Zotero data and rendered in **7 languages** (en/fr/es/ru/uk/ka/de) with an in-page language toggle, no reload.

## Build & run

```bash
# Rebuild the CV page from YAML + Zotero
python3 scripts/build-cv.py

# Regenerate the LaTeX publication sections for the Overleaf CV
# (writes _generated/cv_publications.tex; paste into Overleaf manually)
python3 scripts/build-cv-latex.py

# Rebuild the lab page from _data/lab.yml
python3 scripts/build-lab.py

# Rebuild the global i18n partial (merges cv.yml + site-i18n.yml keys into one JSON blob loaded site-wide)
python3 scripts/build-i18n.py

# Render a single page
quarto render cv.qmd     # or index.qmd, lab.qmd

# Full render + local preview
quarto preview
# OR
quarto render && python3 -m http.server -d docs 8765

# Local admin Flask UI for editing content (runs at :5001; override with ADMIN_PORT)
python3 scripts/cv_admin.py
```

A typical edit-rebuild cycle: launch `cv_admin.py`, edit via the web UI, click **Rebuild & Preview** (runs `build-cv.py` + `build-lab.py` + `quarto render`), refresh the preview at `http://localhost:8765`.

## Architecture: two source-of-truth layers

### 1. Publications live in Zotero

- `~/Dropbox/research_projects/My Library.json` is a Better BibTeX CSL JSON export (~5k entries, ~65 Erlich-authored).
- Publications that appear in the CV are tagged in Zotero with `cv:include` + one of `cv:section/peer-reviewed | editor-reviewed | book-review | blog | working-paper` (under-review / in-prep / on-hold are **NOT** in Zotero — see below).
- Awards and media coverage live in the Zotero `extra` field as `tex.cv-*` lines (`tex.cv-award: winner | ...`, `tex.cv-media: news | Label | URL`, `tex.cv-press-release: URL`).
- `_data/cv-tag-proposal.yml` is the bridge file: it lists every publication by section with its citekey, LaTeX title, and extracted `latex_annotations`. It is edited by the Flask app and by `scripts/apply-tags.py`.
- Aaron's Zotero user ID: **38708**. API key at `~/.config/zotero/api_key` (never in repo).

### 2. Everything else lives in YAML files

- `_data/cv.yml` — non-publication CV content (contact, appointments, affiliations, education, grants, software, professional evaluations, testimony, field research, skills, presentations, teaching, mentorship, professional experience, service, other service). Plus `under_review`, `in_prep`, `on_hold` as plain-text lists (NOT in Zotero). Plus `section_headers` and `labels` for translatable UI strings.
- `_data/lab.yml` — lab page content: `pi`, `current_grad`, `current_undergrad`, `alumni`.
- `_data/site-i18n.yml` — translatable strings for the index and navbar (not the CV).
- `_data/institution-names.yml` — registry of institutions with **bespoke multilingual overrides** (e.g., CSDC ↔ CÉCD, Université McGill). See "Multilingualism" below.

## Multilingualism conventions

### Supported languages

`en fr es ru uk ka de` — English, French, Spanish, Russian, Ukrainian, Georgian (Mkhedruli), German.

English is the canonical source. Other languages are filled by `scripts/translate-cv.py` (Claude Sonnet 4.6 via the Anthropic API, key at `~/.config/anthropic/api_key`). Translations are content-hash cached in `_data/_translation_cache.json` — re-runs only translate changed English strings.

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
    de: "Außerordentlicher Professor"
```

The build scripts (`build-cv.py`, `build-i18n.py`) walk the YAML, detect these leaves, collect them into a merged JSON blob keyed by dotted path (`contact.title`), and wrap the English rendering in `<span data-i18n="contact.title">`.

### Two DOM attributes for the JS toggle

- `data-i18n="key"` — text-only, uses `textContent`. **Safe** (strips HTML). Use for everything by default.
- `data-i18n-html="key"` — HTML-allowed, uses `innerHTML`. Use when the translation must contain inline markup like `<em>` (e.g., italicized journal names). YAML values for these keys may contain HTML; since the source is trusted YAML (not user input), XSS isn't a concern.

The toggle lives in `scripts/build-i18n.py` as inline JS that walks both attribute sets on every `<select>` change and on initial page load.

### What gets translated vs. what doesn't

**Never translated:**
- Publication titles (journal articles, books, chapters)
- Journal names (wrapped in `<em>` via `data-i18n-html`; **italics convention applies in all 7 languages**)
- Person names
- DOIs, URLs, citekeys
- Program-name acronyms (CAnD3, SSHRC, FRQSC, etc.)
- Grant titles that are project acronyms

**Always translated:**
- Role titles ("Associate Professor" → "Professeur agrégé" etc.)
- Degree names ("Ph.D.", "M.A." → local equivalents where applicable)
- Section headers
- UI labels ("Download PDF", "Last updated", "with", "Winner")
- Narrative descriptions
- Country names ("Canada" → "Canadá", etc.)
- Generic words like "with" (coauthor connector) — see `labels.with` in `cv.yml`

**Special cases — institutions with official multilingual forms:**

Some institutions have a genuine local-language name and should use it. These live in `_data/institution-names.yml`. Examples:

- **Centre for the Study of Democratic Citizenship** (en) ↔ **Centre pour l'étude de la citoyenneté démocratique** (fr) — bilingual centre, CSDC ↔ CÉCD
- **McGill University** (en) ↔ **Université McGill** (fr) — officially bilingual
- **University of Washington** ↔ **Université de Washington / Universidad de Washington / Университет Вашингтона / etc.** — universities get their generic word ("University") translated even though it's the school's official English name
- **Caucasus Research Resource Centers** ↔ **კავკასიის კვლევითი რესურსების ცენტრი** (ka) — use Georgian form only in Georgian text

**When you encounter a new institution** that should have a bespoke translation, add it to `_data/institution-names.yml` and note the reason. The registry is currently reference-only (manual lookup during translation); if wired into `translate-cv.py` in the future, it'll be passed to Claude as a glossary.

### Translation-pipeline protocol

1. **Adding a new translatable string**: write the English value in `_data/cv.yml` or `_data/site-i18n.yml`. Run `python3 scripts/translate-cv.py` (defaults to `cv.yml`) or `python3 scripts/translate-cv.py --file _data/site-i18n.yml` to fill the other 6 languages. Cache hits are free; only new strings hit the API.
2. **Correcting a translation**: edit the specific language field by hand in the YAML. Do NOT re-run the translator on that string unless you want it overwritten — use `--force` to override cache, `--lang fr` to limit to one language.
3. **Adding a language**: add the code to `SUPPORTED` in `scripts/translate-cv.py` and `scripts/build-i18n.py`, then run `translate-cv.py --lang <new>`. Add a web font if the script isn't Latin or Cyrillic.
4. **Adding HTML to a translated string** (e.g., `<em>`): change the span from `data-i18n` to `data-i18n-html` in the source `.qmd` or build script. YAML values for that key may now contain inline HTML.

### Why under-review, in-prep, on-hold are plain text (not Zotero)

These papers don't have DOIs and don't belong in a citation manager. They're stored directly in `cv.yml` as `under_review: [...]`, `in_prep: [...]`, `on_hold: [...]` with fields `title`, `year`, `url?`, `coauthors?`, `status?`. They render with a dash bullet (`.cv-pub-list--dash`). The Flask admin has a **publish** button on under-review entries to promote them to a peer-reviewed Zotero-tracked publication.

## CV rendering conventions

Mirrors the original LaTeX CV layout:

- **Numbered (reverse, etaremune-style)**: peer-reviewed, under-review, editor-reviewed — use `.cv-pub-list.cv-pub-list--reverse` with `--cv-pub-start` CSS variable.
- **Dash bullets (em-dash marker)**: book-reviews, blogs, working papers, in-prep, on-hold, professional evaluations — use `.cv-pub-list.cv-pub-list--dash`.
- **Collapsible sections (HTML only, closed by default)**: everything after Testimony (presentations, teaching, mentorship, professional experience, skills, field research, professional service, other service). Wrapped in `<details class="cv-section-collapse">`. The PDF render shows them all — `<details>` is browser-only.
- **Title coloring**: maroon (`#6b1b1b`) **only** on `<a class="cv-pub-title">` — plain-text titles use `.cv-pub-title-plain` (no link styling).
- **Annotation lines under publications**: `<ul class="cv-pub-notes">` with `<li class="cv-pub-award">` or `<li class="cv-pub-media">`. Built by the renderer from `latex_annotations` in the proposal file, which itself comes from the `tex.cv-*` lines in Zotero's `extra` field.

## Lab ↔ CV mentorship sync

Lab alumni in `_data/lab.yml` and political-science mentees in `_data/cv.yml > mentorship` are two separate lists (lab has more people — not every alumnus is a PoliSci mentee). The Flask admin keeps the `placement` field in sync (lab `post_mcgill` ↔ cv `placement`) via `sync_placement_across_files()` when you edit either side. **Only the placement syncs** — bios, degrees, and years stay independent per file. Run `backfill_all_placements()` (inside `cv_admin.py`) one-time if you ever lose sync.

**BA mentees do NOT have a placement field** by convention. Don't add one.

## Flask admin app routes

`scripts/cv_admin.py` serves at `http://localhost:5001` (override with `ADMIN_PORT`; default moved off 5000 because macOS AirPlay Receiver squats on it):

- `/section/<name>` — generic CRUD for any simple section (presentations, grants, teaching, mentorship, etc.)
- `/section/under_review/publish/<idx>` — move an under-review entry to a published Zotero-tracked one
- `/publications` — list all tagged pubs
- `/publications/<citekey>/annotate` — add a `tex.cv-*` line directly to Zotero via the Web API; also mirrors it into the proposal's `latex_annotations` and auto-runs `build-cv.py` + `quarto render cv.qmd` so it shows in the preview immediately
- `/lab` — lab member management
- `/lab/<group>/promote/<idx>` — promote current member to alumni (also syncs placement back to cv.yml mentorship)
- `/rebuild` — runs `build-cv.py` + `build-lab.py` + `quarto render cv.qmd lab.qmd`

The Flask app **automatically bumps `meta.last_updated.en` to today's date** on every save to `cv.yml` (via `dump_yaml_with_header`).

## Dissemination pipeline (Bluesky + LinkedIn)

`_data/dissemination.yml` is the queue *and* the permanent record of what was announced where. `scripts/disseminate.py` drives it; `scripts/bluesky.py` is a stdlib-only AT Protocol client (no `atproto` dependency — `urllib`, like `sync-letter-tokens-to-kv.py`).

**Nothing reaches the public without an explicit `approve`.** `scan` only ever appends `status: new` rows, so it is safe to run unattended.

```bash
python3 scripts/disseminate.py scan            # detect new announceable things
python3 scripts/disseminate.py list --status new
python3 scripts/disseminate.py draft <id>      # [w] $EDITOR  [c] ask Claude  [s] skip
python3 scripts/disseminate.py approve <id>
python3 scripts/disseminate.py schedule --all-approved --starting "2026-08-13 09:30" --every 2d --weekdays-only
python3 scripts/disseminate.py queue           # the rollout, in time order
python3 scripts/disseminate.py post <id>       # or let the launchd job fire it
python3 scripts/disseminate.py mark-posted <id> --linkedin <url>
```

**Claude does the drafting — there is no API call in this pipeline.** The `[c]` branch of `draft` is a pointer: ask Claude in-session ("draft the announcement for `tool-citation-arcs`") and it composes the copy with full repo context and saves it via `disseminate.py set-draft <id> --bluesky … --linkedin …`. Adding an Anthropic API call here would be strictly worse — a cold call has none of the repo context.

**Eight kinds**, each with its own detection source: `publication` (Zotero via `cv-tag-proposal.yml`), `blog` (non-draft `posts/*/index.qmd`), `media` and `award` (the `tex.cv-*` lines already parsed into `latex_annotations`), `grant` and `talk` (`cv.yml`), `tool` (`cv.yml > software`, plus manual), `other` (manual only). Past-dated talks seed as `archived`, never queued.

**Rounds.** Each item keeps a list of announcement rounds (`drafted → approved → scheduled → posted`), so `reannounce <id>` resurfaces something months later without destroying the record of round 1.

**LinkedIn is deliberately manual** — its API needs a Developer app, OAuth consent, and a token refreshed every ~60 days. `post` puts the LinkedIn copy on the clipboard (`pbcopy`) and raises a macOS notification; you paste, then `mark-posted --linkedin <url>`. Bluesky posts automatically via an app password.

**The one non-obvious correctness trap:** Bluesky does not auto-link URLs — each needs a *facet* whose `byteStart`/`byteEnd` are offsets into the **UTF-8 encoding**, not character indices. Any non-ASCII character before a link (an em-dash, "Côte d'Ivoire", Cyrillic) shifts them. `bluesky.link_facets()` asserts the slice round-trips; `python3 scripts/bluesky.py` runs that check offline.

**Site coupling:** `_quarto.yml`'s `site-url` + `open-graph` are load-bearing here — without them Quarto emits no `og:` tags and no `docs/blog.xml`, and every shared link degrades to a bare URL. Post frontmatter must use `description:` (feeds og:description, the listing card, and the RSS feed), **not** `description-meta:` (feeds none of them).

**Credentials:** `~/.config/bluesky/credentials.env` (chmod 600) with `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` — an app password from bsky.app → Settings → Privacy and Security → App Passwords, never the account password. Env vars override the file.

**Background job:** `scripts/com.aaronerlich.dissemination.plist` runs `disseminate.py run --once` every 15 minutes — scans at most once a day (guarded by `meta.last_scan`) and fires due scheduled rounds. Secrets are not in the plist. launchd does not wake a sleeping Mac, so a post due while the laptop is shut fires on next wake.

> ⚠️ **This repo is public — commit `dissemination.yml` *after* posting, not while drafts are pending.** Unposted copy becomes visible on GitHub the moment you commit it, and a killed draft then lives in git history forever. (It is not served on the site: Quarto only copies `_data` files a page actually references.)

## Commit and push

All changes commit locally in the working tree; `git push` goes straight to `main`, which triggers GitHub Pages deploy from `docs/`. **The `docs/` directory is committed** (Quarto writes rendered HTML there; GH Pages serves from `/docs`). Always include the rendered `docs/*.html` files in commits that change content, otherwise the live site gets out of sync with the source.

Stage specifically (never `git add -A` — risk of committing `scripts/__pycache__/`, cache files, or API keys). The `.gitignore` excludes `__pycache__/`, `.DS_Store`, `*.api_key`, etc.

## Known gotchas

- **Auto-update of `last_updated`**: only bumps `en`. Other-language date strings stay stale until `translate-cv.py` is re-run. This is intentional (cheap).
- **Quarto section-divs**: `cv.qmd` disables `section-divs` because Quarto's auto-wrapping of `<h3>` in `<section>` elements adds unwanted padding. Keep `section-divs: false` in the cv frontmatter.
- **The `*` Markdown gotcha**: never use a literal `*` at the start of an `<li>` body (Pandoc interprets it as a nested bullet). Use `★` or wrap in a span.
- **Images in `.grid`**: the old `.grid img { border-radius: 50% }` rule was removed — rounding is now per-class (`.profile-photo`, `.headshot`). Don't re-add a generic rule.
- **`page-layout: full`** on index/cv requires content to be constrained via `body.cv-page` / `body.about-page` CSS max-width rules in `styles.css` (otherwise text spans the whole screen).
- **Fenced `:::` divs** around raw HTML blocks cause Pandoc to complain about "unclosed divs" — avoid wrapping build-script HTML output in `:::` column classes; use `page-layout: full` + CSS instead.

## Reference files

- `~/Dropbox/research_projects/My Library.json` — Zotero export
- `~/.config/zotero/api_key`, `~/.config/anthropic/api_key` — API keys (never in repo)
- `_data/cv_source.tex` — copy of Overleaf main.tex (reference, parser input)
- `_planning/letters-page-workplan.md` — standalone workplan for the letters page rewrite (blocked on Aaron's answers to 10 open questions)
