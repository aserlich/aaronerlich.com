#!/usr/bin/env python3
"""
build-cv-latex.py — LaTeX mirror generator for the Overleaf CV.

Reads the same sources as build-cv.py (cv.yml, cv-tag-proposal.yml, and
the Zotero CSL JSON) and emits LaTeX for the **publication sections** in
the exact style of _data/cv_source.tex (etaremune for numbered lists,
itemize with em-dash markers for dash lists, inline \\href{URL}{``title''}
pattern, \\textit{journal} italics, ``---Winner: …'' and
``---Media coverage: …'' annotation trailers).

Output: two copies of the same LaTeX fragment —
  1. `_generated/cv_publications.tex`   (tracked in this repo)
  2. `~/Dropbox/Apps/Overleaf/Erlich_CV_Version_Control/cv_publications.tex`
     (syncs to Overleaf automatically via Dropbox integration)

One-time wiring: in main.tex on Overleaf, replace the inline publication
sections (\\section{\\sc Peer-Reviewed Publications} through the end of
Working Papers) with a single line:

  \\input{cv_publications}

After that every re-run of build-cv-latex.py pushes a fresh version into
Overleaf with no hand-editing.

Scope v1: publication sections only. Non-publication content
(appointments, affiliations, education, grants, software, presentations,
teaching, mentorship, professional experience, skills, field research,
service) stays hand-maintained on Overleaf because it changes rarely
and full coverage would duplicate ~500 lines of build-cv.py without
much payoff. Add more sections here if the manual-edit burden ever
becomes annoying.

Sections emitted (in main.tex order):
  1. Peer-Reviewed Publications (etaremune)
  2. Editor-Reviewed Publications (etaremune)
  3. Under Review              (itemize + dash, plain text from cv.yml)
  4. In Preparation            (itemize + dash, plain text from cv.yml)
  5. On Hold                   (itemize + dash, plain text from cv.yml)
  6. Book Reviews              (itemize + dash, from Zotero)
  7. Blog Posts                (itemize + dash, from Zotero)
  8. Working Papers            (itemize + dash, from Zotero)

Usage:
  python3 scripts/build-cv-latex.py
  # inspect _generated/cv_publications.tex
  # copy/paste into Overleaf main.tex

Stdlib + PyYAML.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Install PyYAML: pip install pyyaml")

REPO = Path(__file__).resolve().parents[1]
CV_YAML = REPO / "_data" / "cv.yml"
PROPOSAL = REPO / "_data" / "cv-tag-proposal.yml"
ZOTERO_JSON = Path.home() / "Dropbox" / "research_projects" / "My Library.json"
OUT = REPO / "_generated" / "cv_publications.tex"

# Overleaf's Dropbox integration syncs this folder with the CV project.
# Writing here auto-propagates to the web editor. If this path doesn't
# exist on the current machine we just skip (e.g., running on a
# collaborator's machine where the Overleaf-Dropbox link isn't set up).
OVERLEAF_DROPBOX_DIR = (
    Path.home() / "Dropbox" / "Apps" / "Overleaf" / "Erlich_CV_Version_Control"
)
OVERLEAF_OUT = OVERLEAF_DROPBOX_DIR / "cv_publications.tex"


# ---------- LaTeX escape / helpers ----------

_LATEX_ESCAPES = {
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPES))

def tex_escape(s) -> str:
    """Escape the 10 LaTeX special characters. Safe on plain strings."""
    if s is None:
        return ""
    return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_ESCAPES[m.group(0)], str(s))


def tex_url(s) -> str:
    """URLs don't need full tex_escape — only # and % need backslashing
    (and & in some engines). hyperref tolerates most of them in \\href{}."""
    if not s:
        return ""
    return str(s).replace("\\", "\\\\").replace("%", r"\%").replace("#", r"\#")


def tex_quotes(s: str) -> str:
    """LaTeX open/close quote convention: ``text''."""
    return f"``{s}''"


# ---------- author formatting ----------

def fmt_authors_latex(author_list, drop_last_name="erlich") -> str:
    """Drop Aaron, "Name1, Name2, and Name3" Oxford-comma style."""
    names = []
    for a in author_list or []:
        fam = (a.get("family") or "").strip()
        giv = (a.get("given") or "").strip()
        if drop_last_name and fam.lower() == drop_last_name:
            continue
        if giv and fam:
            names.append(f"{giv} {fam}")
        elif fam:
            names.append(fam)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def get_year(item: dict) -> str:
    issued = item.get("issued") or {}
    parts = issued.get("date-parts") or []
    if parts and parts[0]:
        return str(parts[0][0])
    return ""


# ---------- annotation detection ----------

_ANNOT_PATTERNS = [
    (re.compile(r"(?i)^winner\s*[:\-]\s*(.+)"),                     "Winner"),
    (re.compile(r"(?i)^hono(?:u)?rable\s*mention\s*[:\-]\s*(.+)"),  "Honourable Mention"),
    (re.compile(r"(?i)^media\s*coverage\s*[:\-]?\s*(.+)"),          "Media coverage"),
    (re.compile(r"(?i)^press\s*release\s*[:\-]?\s*(.+)"),           "Press release"),
    (re.compile(r"(?i)^top\s+\d+\s+most\s+cited(?:\s+article\s+award)?\s*(.+)?"),
                                                                    "Top 10 Most Cited"),
]

def format_annotation_latex(ann: str) -> str:
    """Turn an annotation string into a LaTeX trailer line. The build-cv.py
    HTML version wraps these in <strong>; the Overleaf LaTeX convention is
    a leading em-dash without explicit labels:
        ---Winner: Best Paper on Political Institutions from …
        ---Media coverage: \\href{…}{\\textit{Maclean's}}
    We preserve any LaTeX markup already inside the annotation string."""
    a = ann.strip().rstrip(".")
    for pat, label in _ANNOT_PATTERNS:
        m = pat.match(a)
        if m:
            content = (m.group(1) or "").strip() if m.lastindex else ""
            # The content is already LaTeX source in most cases (hrefs,
            # textit, etc.) — do not double-escape.
            return f"---{label}: {content}" if content else f"---{label}"
    # Unknown annotation — pass through as-is (assume it's already well-formed)
    return f"---{a}"


# ---------- publication row renderer ----------

def render_publication_latex(item: dict, annotations: list | None) -> str:
    """Emit one \\item block for a Zotero publication entry, matching the
    cv_source.tex style: linked title, year, italic venue, vol(issue) pages,
    (with Coauthors), optional annotation trailers."""
    title = item.get("title") or "(untitled)"
    venue = item.get("container-title") or item.get("collection-title") or ""
    volume = item.get("volume") or ""
    issue = item.get("issue") or ""
    pages = item.get("page") or ""
    year = get_year(item)
    doi = item.get("DOI") or ""
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    coauthors_str = fmt_authors_latex(item.get("author") or [])

    # Title — linked if we have a URL, quoted either way
    title_quoted = tex_quotes(tex_escape(title))
    if url:
        title_part = f"\\href{{{tex_url(url)}}}{{{title_quoted}}}"
    else:
        title_part = title_quoted

    parts = [title_part]
    if year:
        parts.append(f" {year}.")
    if venue:
        parts.append(f" \\textit{{{tex_escape(venue)}}}")
    if volume:
        if issue:
            parts.append(f" {tex_escape(volume)}({tex_escape(issue)})")
        else:
            parts.append(f" {tex_escape(volume)}")
    if pages:
        parts.append(f" {tex_escape(pages)}.")
    if coauthors_str:
        parts.append(f" (with {tex_escape(coauthors_str)})")

    body = "".join(parts)

    if annotations:
        trailers = [format_annotation_latex(a) for a in annotations]
        # Each annotation on its own line, preceded by \\ to force a line break
        # inside the enumerate item, as in _data/cv_source.tex.
        body += " \\\\\n    " + " \\\\\n    ".join(trailers)

    return f"  \\item {body}"


# ---------- stub renderer (for entries not yet in Zotero) ----------

def render_stub_latex(entry: dict) -> str:
    """Fallback when a cv-tag-proposal.yml row has no Zotero match — emit
    title + optional URL + year from the proposal fields alone."""
    title = entry.get("latex_title") or "(untitled)"
    year = entry.get("latex_year") or ""
    url = entry.get("latex_url") or ""
    title_quoted = tex_quotes(tex_escape(title))
    if url:
        title_part = f"\\href{{{tex_url(url)}}}{{{title_quoted}}}"
    else:
        title_part = title_quoted
    pieces = [title_part]
    if year:
        pieces.append(f" {year}.")
    body = "".join(pieces)
    if entry.get("latex_annotations"):
        trailers = [format_annotation_latex(a) for a in entry["latex_annotations"]]
        body += " \\\\\n    " + " \\\\\n    ".join(trailers)
    return f"  \\item {body}"


# ---------- section renderers ----------

def render_zotero_section(proposal: dict, by_citekey: dict,
                          proposal_key: str, header: str,
                          numbered: bool) -> str:
    """Emit a LaTeX section populated from a cv-tag-proposal.yml section
    (peer-reviewed, editor-reviewed, book-review, blog, working-paper).
    `numbered=True` uses etaremune (reverse count); False uses itemize
    with em-dash markers, matching cv_source.tex."""
    items = (proposal.get("sections") or {}).get(proposal_key) or []
    out = [f"\\section{{\\sc {header}}}"]
    if not items:
        out.append("% (no entries)")
        return "\n".join(out) + "\n"

    if numbered:
        out.append("")
        out.append("\\renewcommand{\\labelenumi}{\\theenumi.}")
        out.append("\\begin{etaremune}")
        out.append("")
    else:
        out.append("")
        out.append("\\begin{itemize}[label={---},leftmargin=1.5em]")

    for entry in items:
        ck = entry.get("match_citekey")
        anns = entry.get("latex_annotations") or []
        if ck and ck != "SKIP" and ck in by_citekey:
            out.append(render_publication_latex(by_citekey[ck], anns))
        else:
            out.append(render_stub_latex(entry))
            if ck and ck != "SKIP" and ck not in by_citekey:
                out.append(f"  % FIXME: citekey '{ck}' not found in Zotero")
        out.append("")  # blank line between items for readability

    out.append("\\end{etaremune}" if numbered else "\\end{itemize}")
    return "\n".join(out) + "\n"


def render_plain_cv_section(entries: list, header: str) -> str:
    """Emit a dash-bulleted section from a list of dicts in cv.yml —
    under_review, in_prep, on_hold. Each entry has title, year?, url?,
    coauthors?, status?."""
    out = [f"\\section{{\\sc {header}}}"]
    if not entries:
        out.append("% (no entries)")
        return "\n".join(out) + "\n"
    out.append("")
    out.append("\\begin{itemize}[label={---},leftmargin=1.5em]")
    for e in entries:
        title = e.get("title") or "(untitled)"
        year = e.get("year") or ""
        url = e.get("url") or ""
        coauthors = e.get("coauthors") or []
        status = e.get("status") or ""

        title_quoted = tex_quotes(tex_escape(title))
        if url:
            title_part = f"\\href{{{tex_url(url)}}}{{{title_quoted}}}"
        else:
            title_part = title_quoted

        pieces = [title_part]
        if year:
            pieces.append(f" {year}.")

        if coauthors:
            if len(coauthors) == 1:
                ca = coauthors[0]
            elif len(coauthors) == 2:
                ca = f"{coauthors[0]} and {coauthors[1]}"
            else:
                ca = ", ".join(coauthors[:-1]) + f", and {coauthors[-1]}"
            pieces.append(f" (with {tex_escape(ca)})")

        if status:
            pieces.append(f" [{tex_escape(status)}]")

        out.append(f"  \\item {''.join(pieces)}")
    out.append("\\end{itemize}")
    return "\n".join(out) + "\n"


# ---------- main ----------

def load_zotero_by_citekey() -> dict:
    """Index the full Zotero export by Better BibTeX citekey. CSL JSON
    stores the citekey in the 'id' field."""
    if not ZOTERO_JSON.exists():
        sys.exit(f"Zotero export not found: {ZOTERO_JSON}")
    with ZOTERO_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data if "id" in item}


def main() -> int:
    cv = yaml.safe_load(CV_YAML.read_text(encoding="utf-8"))
    proposal = yaml.safe_load(PROPOSAL.read_text(encoding="utf-8")) or {}
    by_citekey = load_zotero_by_citekey()

    out_parts: list[str] = []
    out_parts.append(
        "% ----------------------------------------------------------\n"
        "% Generated by scripts/build-cv-latex.py — do not hand-edit.\n"
        "% Overleaf picks up changes here via Dropbox sync. main.tex\n"
        "% should have `\\input{cv_publications}` where the inline\n"
        "% publication sections used to live.\n"
        "%\n"
        "% Non-publication sections (appointments, education, grants,\n"
        "% teaching, mentorship, etc.) are NOT generated — they stay\n"
        "% hand-maintained in main.tex on Overleaf.\n"
        "% ----------------------------------------------------------\n"
    )

    # 1. Peer-reviewed (etaremune)
    out_parts.append(render_zotero_section(
        proposal, by_citekey, "peer-reviewed", "Peer-Reviewed Publications", numbered=True))

    # 2. Editor-reviewed (etaremune) — in the cv_source.tex order, this
    # comes BEFORE under-review/in-prep in some drafts, AFTER in others.
    # Following cv.yml's convention: publications numbered → then plain
    # lists (under review, in prep, on hold) → then book reviews/blogs.
    out_parts.append(render_zotero_section(
        proposal, by_citekey, "editor-reviewed", "Editor-Reviewed Publications", numbered=True))

    # 3–5. Plain-text lists from cv.yml
    out_parts.append(render_plain_cv_section(
        cv.get("under_review") or [], "Under Review"))
    out_parts.append(render_plain_cv_section(
        cv.get("in_prep") or [], "In Preparation"))
    out_parts.append(render_plain_cv_section(
        cv.get("on_hold") or [], "On Hold"))

    # 6–8. Dash-bulleted Zotero sections
    out_parts.append(render_zotero_section(
        proposal, by_citekey, "book-review", "Book Reviews", numbered=False))
    out_parts.append(render_zotero_section(
        proposal, by_citekey, "blog", "Blog Posts", numbered=False))
    out_parts.append(render_zotero_section(
        proposal, by_citekey, "working-paper", "Working Papers", numbered=False))

    text = "\n".join(out_parts)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")

    # Also write directly into the Overleaf-linked Dropbox folder so the
    # web editor picks it up via Overleaf's Dropbox integration — no
    # manual paste. main.tex needs a one-time edit to
    # `\input{cv_publications}` in place of the hand-coded publication
    # sections (see README block at the top of the generated file).
    if OVERLEAF_DROPBOX_DIR.exists():
        OVERLEAF_OUT.write_text(text, encoding="utf-8")
        print(f"  Also wrote {OVERLEAF_OUT}", file=sys.stderr)
    else:
        print(f"  (Overleaf Dropbox dir not present at {OVERLEAF_DROPBOX_DIR};"
              f" skipping direct Overleaf write)", file=sys.stderr)

    # Summary to stderr
    n_pr = len((proposal.get("sections") or {}).get("peer-reviewed") or [])
    n_er = len((proposal.get("sections") or {}).get("editor-reviewed") or [])
    n_br = len((proposal.get("sections") or {}).get("book-review") or [])
    n_bl = len((proposal.get("sections") or {}).get("blog") or [])
    n_wp = len((proposal.get("sections") or {}).get("working-paper") or [])
    n_ur = len(cv.get("under_review") or [])
    n_ip = len(cv.get("in_prep") or [])
    n_oh = len(cv.get("on_hold") or [])

    print(f"  Wrote {OUT}", file=sys.stderr)
    print(f"  Peer-reviewed:    {n_pr}", file=sys.stderr)
    print(f"  Editor-reviewed:  {n_er}", file=sys.stderr)
    print(f"  Under review:     {n_ur}", file=sys.stderr)
    print(f"  In preparation:   {n_ip}", file=sys.stderr)
    print(f"  On hold:          {n_oh}", file=sys.stderr)
    print(f"  Book reviews:     {n_br}", file=sys.stderr)
    print(f"  Blog posts:       {n_bl}", file=sys.stderr)
    print(f"  Working papers:   {n_wp}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
