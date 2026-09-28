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

Scope: the whole PDF body. Publication sections go to cv_publications.tex;
every other section is a macro in cv_generated.tex, which main.tex calls
under its \\section headers. main.tex keeps only the preamble, headers and
layout glue. Hand-maintained sections used to live in main.tex, and 2026
additions reached the web CV but never the PDF, so all of them moved here.

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
import datetime
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

# Second generated file. cv_publications.tex covers the publication lists; this
# one carries everything else main.tex used to hand-maintain in parallel with
# cv.yml — the "last updated" date and the three peer-review lists. Both the web
# CV and the PDF then read one source, so they cannot drift apart again.
OUT_GEN = REPO / "_generated" / "cv_generated.tex"
OVERLEAF_GEN = OVERLEAF_DROPBOX_DIR / "cv_generated.tex"


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

def normalize_doi(doi: str) -> str:
    """Zotero DOI fields arrive dirty: some hold a full https://doi.org/… URL,
    some a 'DOI: ' / 'doi:' prefix. Strip either so the href is not doubled."""
    return re.sub(r"^\s*(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi,
                  flags=re.IGNORECASE).strip()


def fmt_authors_latex(author_list, drop_last_name="erlich") -> str:
    """Drop Aaron, "Name1, Name2, and Name3" Oxford-comma style."""
    names = []
    for a in author_list or []:
        fam = (a.get("family") or "").strip()
        giv = (a.get("given") or "").strip()
        # Zotero sometimes stores a name in ONE field ("Erlich, Aaron") instead
        # of two. That lands in `family` whole, so a bare surname comparison
        # misses it and Aaron ends up listed as his own coauthor. Compare the
        # surname component, not the raw field.
        fam_surname = fam.split(",")[0].strip().lower()
        if drop_last_name and fam_surname == drop_last_name:
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

def _detect_tex_cv_latex(a: str):
    """Translate a raw Zotero `tex.cv-*` extra line into (label, latex_content).

    Mirrors _detect_tex_cv() in build-cv.py so the LaTeX CV and the web CV
    render the same annotations. Without this the raw line fell through the
    pattern table and printed verbatim in the PDF, e.g.
        ---tex.cv-media: news | The Guardian | https://...
    """
    body = a[len("tex.cv-"):]
    kind, _, rest = body.partition(":")
    kind, rest = kind.strip(), rest.strip()
    if kind == "award":
        sub, _, value = rest.partition("|")
        sub, value = sub.strip(), value.strip()
        if sub == "honorable-mention":
            return "Honourable Mention", value
        if sub == "top-cited":
            return "Top 10 Most Cited", value
        return "Winner", value
    if kind == "media":
        fields = [f.strip() for f in rest.split("|")]
        if len(fields) >= 3 and fields[2]:
            return "Media coverage", f"\\href{{{fields[2]}}}{{\\textit{{{fields[1]}}}}}"
        return "Media coverage", fields[-1]
    if kind == "press-release":
        content = f"\\href{{{rest}}}{{{rest}}}" if rest.startswith("http") else rest
        return "Press release", content
    if kind == "note":
        return None, rest
    return None, a


def split_annotation_latex(ann: str):
    """Return (label, content) for an annotation, handling both the legacy
    human-readable LaTeX form and the raw Zotero `tex.cv-*` form."""
    a = ann.strip().rstrip(".")
    if a.startswith("tex.cv-"):
        return _detect_tex_cv_latex(a)
    for pat, label in _ANNOT_PATTERNS:
        m = pat.match(a)
        if m:
            content = (m.group(1) or "").strip() if m.lastindex else ""
            return label, content
    return None, a


def group_annotations_latex(annotations) -> list:
    """Collapse annotations sharing a label onto one trailer line, so a paper
    with both a legacy `Media coverage:` line and a `tex.cv-media:` entry
    yields one line listing every outlet — matching the web CV's grouping."""
    grouped, pos = [], {}
    for ann in annotations or []:
        label, content = split_annotation_latex(ann)
        if label and label in pos:
            grouped[pos[label]][1].append(content)
        else:
            if label:
                pos[label] = len(grouped)
            grouped.append([label, [content]])
    out = []
    for label, contents in grouped:
        joined = ", ".join(c for c in contents if c)
        out.append(f"---{label}: {joined}" if label and joined
                   else (f"---{label}" if label else f"---{joined}"))
    return out


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

def render_publication_latex(item: dict, annotations: list | None,
                              status: str = "") -> str:
    """Emit one \\item block for a Zotero publication entry, matching the
    cv_source.tex style: linked title, year, italic venue, vol(issue) pages,
    (with Coauthors), optional annotation trailers. When `status` is given
    (e.g., "Forthcoming", "Online First") it replaces the year — used for
    accepted-but-undated papers. Sort to the top is handled section-side."""
    title = item.get("title") or "(untitled)"
    venue = item.get("container-title") or item.get("collection-title") or ""
    volume = item.get("volume") or ""
    issue = item.get("issue") or ""
    pages = item.get("page") or ""
    year = get_year(item)
    doi = normalize_doi(item.get("DOI") or "")
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    coauthors_str = fmt_authors_latex(item.get("author") or [])

    # Title — linked if we have a URL, quoted either way
    title_quoted = tex_quotes(tex_escape(title))
    if url:
        title_part = f"\\href{{{tex_url(url)}}}{{{title_quoted}}}"
    else:
        title_part = title_quoted

    parts = [title_part]
    if status:
        parts.append(f" {tex_escape(status)}.")
    elif year:
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
        trailers = group_annotations_latex(annotations)
        # Each annotation on its own line, preceded by \\ to force a line break
        # inside the enumerate item, as in _data/cv_source.tex.
        body += " \\\\\n    " + " \\\\\n    ".join(trailers)

    return f"  \\item {body}"


# ---------- stub renderer (for entries not yet in Zotero) ----------

def render_stub_latex(entry: dict) -> str:
    """Fallback when a cv-tag-proposal.yml row has no Zotero match — emit
    title + optional URL + year from the proposal fields alone. Honors
    `latex_status` the same way render_publication_latex does."""
    title = entry.get("latex_title") or "(untitled)"
    year = entry.get("latex_year") or ""
    status = entry.get("latex_status") or ""
    url = entry.get("latex_url") or ""
    title_quoted = tex_quotes(tex_escape(title))
    if url:
        title_part = f"\\href{{{tex_url(url)}}}{{{title_quoted}}}"
    else:
        title_part = title_quoted
    pieces = [title_part]
    if status:
        pieces.append(f" {tex_escape(status)}.")
    elif year:
        pieces.append(f" {year}.")
    body = "".join(pieces)
    if entry.get("latex_annotations"):
        trailers = group_annotations_latex(entry["latex_annotations"])
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

    def _year(e: dict) -> int:
        """Prefer Zotero `issued` year (authoritative), fall back to the
        proposal's `latex_year`, then 0."""
        ck = e.get("match_citekey")
        if ck and ck in by_citekey:
            parts = (by_citekey[ck].get("issued") or {}).get("date-parts") or [[None]]
            y = parts[0][0] if parts and parts[0] else None
            if y:
                try:
                    return int(y)
                except (TypeError, ValueError):
                    pass
        ly = e.get("latex_year")
        if ly:
            try:
                return int(ly)
            except (TypeError, ValueError):
                return 0
        return 0

    # Status entries pin to top; otherwise reverse-chronological.
    items = sorted(
        items,
        key=lambda e: (
            0 if e.get("latex_status") else 1,
            -_year(e),
        ),
    )
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
        status = entry.get("latex_status") or ""
        if ck and ck != "SKIP" and ck in by_citekey:
            out.append(render_publication_latex(by_citekey[ck], anns, status=status))
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
    """Index the full Zotero export by Better BibTeX citekey.

    `id` and `citation-key` usually agree, but not always — BBT can pin a
    citekey that differs from the CSL id (e.g. id 'erlich_CoverageCandour_2026'
    vs citekey 'erlichCoverageCandour2026'). cv-tag-proposal.yml pins the
    CITEKEY, so index on that first and keep `id` as an alias, otherwise the
    entry silently falls back to the LaTeX stub with a FIXME. build-cv.py
    keys on citation-key for the same reason."""
    if not ZOTERO_JSON.exists():
        sys.exit(f"Zotero export not found: {ZOTERO_JSON}")
    with ZOTERO_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for item in data:
        alias = item.get("id")
        if alias and alias not in out:
            out[alias] = item
    for item in data:                      # citekey wins on collision
        ck = item.get("citation-key") or item.get("citekey")
        if ck:
            out[ck] = item
    return out


_YEAR_SORT_RE = re.compile(r"(\d{4})")


def year_sort_key(value) -> int:
    """First 4-digit year in a free-form string ('2026', '2014–2015'), else 0.
    Same rule as build-cv.py's, so the PDF lists grants in the web CV's order."""
    m = _YEAR_SORT_RE.search(str(value or ""))
    return int(m.group(1)) if m else 0


def render_grant_rows(grants: list) -> str:
    """One `\\textline[t]{year}{description}{amount}` per grant, newest first.

    \\textline is main.tex's own three-parbox row macro, so column widths stay
    an Overleaf decision. The description follows the hand-typed rows this
    replaced — ``Title.'' Agency (Role, notes) when there is an agency,
    otherwise the bare title (fellowships, travel grants, scholarships).
    """
    rows = []
    # sorted() is stable, so same-year grants keep their cv.yml order — as on the web.
    for g in sorted(grants, key=lambda g: -year_sort_key(g.get("year"))):
        title = tex_escape((g.get("title") or {}).get("en") or "")
        if g.get("agency"):
            if not title.endswith(("?", "!", ".")):
                title += "."
            desc = f"{tex_quotes(title)} {tex_escape(g['agency'])}"
        else:
            desc = title
        paren = [x for x in ((g.get("role") or {}).get("en"),
                             (g.get("notes") or {}).get("en")) if x]
        if paren:
            desc += f" ({tex_escape(', '.join(paren))})"
        rows.append(f"\\textline[t]{{{tex_escape(g.get('year', ''))}}}"
                    f"{{{desc}}}{{{tex_escape(g.get('amount') or '')}}}")
    return "\n".join(rows)


def render_service_tabbing(entries: list) -> str:
    """A tabbing block of service roles by academic year, newest first:
    `year \\= role`, then `\\> role` for the rest of that year, as main.tex
    had them by hand. Entries sharing a year merge in list order, like
    build-cv.py's _group_by_year_and_render, so the web and PDF agree."""
    buckets: dict[str, list] = {}
    for e in entries:
        buckets.setdefault(str(e.get("year", "")), []).extend(e.get("roles") or [])
    lines = []
    for yr, roles in sorted(buckets.items(), key=lambda kv: -year_sort_key(kv[0])):
        for j, role in enumerate(roles):
            lead = f"{tex_escape(yr)} \\= " if j == 0 else "\\> "
            lines.append(lead + tex_squotes(tex_escape(role)))
    # No \\ after the last row: in tabbing it would add an empty line.
    return "\\begin{tabbing}\n" + " \\\\\n".join(lines) + "\n\\end{tabbing}"


# ---------- the rest of the PDF body ----------
#
# One renderer per remaining main.tex section. Each returns that section's
# body in the markup main.tex used when it was hand-typed (list1 / list2 are
# main.tex's own environments), with the fields and sort order of the matching
# render_* in build-cv.py, so the web CV and the PDF say the same thing.

def en(v) -> str:
    """cv.yml leaves are plain strings or {en: …, fr: …} language maps; the
    PDF is English-only."""
    if isinstance(v, dict):
        return str(v.get("en") or "")
    return "" if v is None else str(v)


def macro_url(u: str) -> str:
    """tex_url plus &: these hrefs sit inside \\newcommand bodies, where the
    URL is already tokenized and a bare & is an alignment tab."""
    return tex_url(u).replace("&", r"\&")


def with_list(names: list) -> str:
    """'A', 'A and B', 'A, B, and C'."""
    names = [tex_escape(n) for n in names]
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


_SQUOTE_RE = re.compile(r"(?<!\w)'([^']+)'(?!\w)")


def tex_squotes(s: str) -> str:
    """'Shadows of The Gulag' -> `Shadows of The Gulag'. A straight ' prints as a
    closing quote on both sides in LaTeX. Apostrophes (Kenya's, Ach'aran) are
    left alone because a letter precedes them."""
    return _SQUOTE_RE.sub(r"`\1'", s)


def dash_ranges(s: str) -> str:
    """Escape s, making year ranges en dashes: '2006-2010' -> 2006--2010, and an
    open '2013-' -> 2013-- rather than a stray hyphen."""
    return re.sub(r"(\d{4})\s*-\s*", r"\1--", tex_escape(s))


# Longest first, so "magna cum laude" isn't matched as "cum laude".
_HONOURS_RE = re.compile(r"\b(summa cum laude|magna cum laude|cum laude|with distinction)\b")


def fmt_date(v) -> str:
    """'2024-04-15' (or a YAML date) -> 'April 15, 2024'; anything else as-is."""
    if isinstance(v, datetime.date):
        d = v
    else:
        try:
            d = datetime.date.fromisoformat(str(v))
        except ValueError:
            return str(v or "")
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def render_contact(cv: dict) -> str:
    c = cv.get("contact") or {}
    left = [tex_escape(en(c.get(k))) for k in
            ("department", "institution", "address_line1", "address_line2", "country")]
    right = [
        f"{{\\it Voice:}} {tex_escape(c.get('phone'))}",
        f"{{\\it E-mail:}} \\texttt{{{tex_escape(c.get('email'))}}}",
        f"{{\\it web:}} \\url{{{c.get('web', '')}}}",
        f"{{\\it Office:}} {tex_escape(c.get('office'))}",
    ]
    right += [""] * (len(left) - len(right))
    rows = [f"{l} & {r} \\\\" for l, r in zip(left, right)]
    return "\\begin{tabular}{@{}p{3in}p{3in}}\n" + "\n".join(rows) + "\n\\end{tabular}"


def render_appointments(cv: dict) -> str:
    out = []
    for app in cv.get("academic_appointments") or []:
        out.append(f"{{\\bf {tex_escape(en(app.get('institution')))}}}, "
                   f"{tex_escape(en(app.get('department')))}, {tex_escape(en(app.get('location')))}")
        out.append("\\begin{list1}")
        for pos in app.get("positions") or []:
            line = f"\\item[] {tex_escape(en(pos.get('role')))}, {tex_escape(en(pos.get('dates')))}"
            if pos.get("notes"):
                line += f" {tex_escape(en(pos['notes']))}"
            out.append(line)
        out.append("\\end{list1}")
    return "\n".join(out)


def render_affiliations(cv: dict) -> str:
    out = ["\\begin{list1}"]
    for a in cv.get("affiliations") or []:
        org = tex_escape(en(a.get("org")))
        if a.get("url"):
            org = f"\\href{{{macro_url(a['url'])}}}{{{org}}}"
        out.append(f"\\item[] {tex_escape(en(a.get('role')))}, {org}, {tex_escape(en(a.get('dates')))}")
    out.append("\\end{list1}")
    return "\n".join(out)


def render_education(cv: dict) -> str:
    blocks = []
    for edu in cv.get("education") or []:
        out = [f"{{\\bf {tex_escape(en(edu.get('institution')))}}}, {tex_escape(en(edu.get('location')))}",
               "\\begin{list1}"]
        for d in edu.get("degrees") or []:
            line = _HONOURS_RE.sub(r"\\emph{\1}", tex_escape(en(d.get("degree"))))
            if d.get("year"):
                line += f", {tex_escape(d['year'])}"
            out.append(f"\\item[] {line}")
        out.append("\\end{list1}")
        blocks.append("\n".join(out))
    return "\n\n".join(blocks)


def render_software(cv: dict) -> str:
    out = []
    for s in cv.get("software") or []:
        name = f"\\texttt{{{tex_escape(s.get('name'))}}}"
        if s.get("url"):
            name = f"\\href{{{macro_url(s['url'])}}}{{{name}}}"
        line = f"{name}: {tex_escape(en(s.get('description')))}"
        if s.get("coauthors"):
            line += f" (with {with_list(s['coauthors'])})"
        out.append(line)
    return "\n\n".join(out)


def render_evaluations(cv: dict) -> str:
    out = []
    for e in cv.get("professional_evaluations") or []:
        title = tex_escape(en(e.get("title")))
        # The period goes inside the quotes unless a (with …) follows them.
        if e.get("coauthors"):
            line = f"{tex_quotes(title)} (with {with_list(e['coauthors'])})."
        else:
            line = tex_quotes(title if title.endswith(("?", "!", ".")) else title + ".")
        where = ", ".join(x for x in (tex_escape(en(e.get("submitted_to"))),
                                      tex_escape(e.get("year") or "")) if x)
        for seg in (tex_escape(en(e.get("notes"))), where):
            if seg:
                line += f" {seg}."
        out.append(line)
    return "\n\n".join(out)


def render_testimony(cv: dict) -> str:
    out = []
    for ti in cv.get("testimony") or []:
        title = tex_escape(en(ti.get("title")))
        if ti.get("url"):
            title = f"\\href{{{macro_url(ti['url'])}}}{{{title}}}"
        out.append(f"{title}. {tex_escape(en(ti.get('venue')))} ({tex_escape(fmt_date(ti.get('date')))}).")
    return "\n\n".join(out)


def render_presentations(cv: dict) -> str:
    out = ["* is an invited talk"]
    for p in sorted(cv.get("presentations") or [], key=lambda p: -year_sort_key(p.get("date"))):
        title = tex_escape(en(p.get("title")))
        if not title.endswith(("?", "!", ".")):
            title += "."
        mark = "* " if p.get("invited") else ""
        with_ = f" (with {with_list(p['coauthors'])})" if p.get("coauthors") else ""
        out.append(f"{mark}{tex_quotes(title)} {tex_squotes(tex_escape(en(p.get('venue'))))}, "
                   f"{tex_escape(en(p.get('date')))}{with_}.")
    return "\n\n".join(out)


def render_teaching(cv: dict) -> str:
    tc = cv.get("teaching") or {}
    out = []
    for key, label in (("instructor", "Instructor"), ("gsi", "Graduate Student Instructor")):
        out += [f"{{\\em {label}}}\\\\", "\\vspace{-.1in}", "\\begin{list1}"]
        for level, level_label in (("undergraduate", "Undergraduate"), ("graduate", "Graduate")):
            out += [f"\\item[] {level_label} courses:", "\\begin{list2}"]
            for c in (tc.get(key) or {}).get(level) or []:
                out.append(f"\\item[] {tex_escape(en(c.get('course')))} [{tex_escape(c.get('code'))}] "
                           f"({tex_escape(c.get('institution'))})")
            out.append("\\end{list2}")
        out += ["\\end{list1}", ""]
    return "\n".join(out)


LAB_PAGE_URL = "https://aaronerlich.com/lab.html"

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def md_links_to_tex(s: str) -> str:
    """Escape s, turning markdown links [text](url) (how cv.yml stores some
    placements) into \\href."""
    out, pos = [], 0
    for m in _MD_LINK_RE.finditer(s):
        out.append(tex_escape(s[pos:m.start()]))
        out.append(f"\\href{{{macro_url(m.group(2))}}}{{{tex_escape(m.group(1))}}}")
        pos = m.end()
    out.append(tex_escape(s[pos:]))
    return "".join(out)


def render_mentorship(cv: dict) -> str:
    """Year, name and roles. A placement is shown only when flagged
    `academic_placement: true` (PhD -> academic job, MA -> PhD program); every
    placement stays on the web, and the PDF points to the lab page for them."""
    ms = cv.get("mentorship") or {}
    lab_note = f"see \\href{{{LAB_PAGE_URL}}}{{lab page}} for others and placements"
    out = ["\\begin{list1}"]
    for level, label, note in (("phd", "Ph.D. in Political Science", f"year of graduation; {lab_note}"),
                               ("ma", "M.A. in Political Science", f"year of graduation; {lab_note}"),
                               ("undergraduate", "Undergraduate", "year of mentorship")):
        # Newest first; TBD (current students) sinks — as on the web.
        entries = sorted(ms.get(level) or [], key=lambda m: -year_sort_key(m.get("year")))
        if not entries:
            continue
        out += [f"\\item[] \\textbf{{{label}}} ({note})", "\\begin{list2}"]
        for m in entries:
            line = (f"\\item[{tex_escape(m.get('year', ''))}] {tex_escape(m.get('name'))}, "
                    f"{tex_escape(en(m.get('roles')))}")
            if m.get("academic_placement") and m.get("placement"):
                line += f"; {md_links_to_tex(en(m['placement']))}"
            out.append(line)
        out.append("\\end{list2}")
    out.append("\\end{list1}")
    return "\n".join(out)


def render_experience(cv: dict) -> str:
    blocks = []
    for e in sorted(cv.get("professional_experience") or [],
                    key=lambda e: -year_sort_key(e.get("dates"))):
        head = f"{{\\bf {tex_escape(en(e.get('employer')))}}}"
        if e.get("locations"):
            head += f", {tex_escape(en(e['locations']))}"
        out = [head, "", "\\vspace{-.3cm}",
               f"{{\\em {tex_escape(en(e.get('role')))}}} \\hfill {{\\bf {dash_ranges(en(e.get('dates')))}}}\\\\"]
        if e.get("bullets"):
            out.append("\\begin{list1}")
            out += [f"\\item[]-- {tex_escape(en(b))}" for b in e["bullets"]]
            out.append("\\end{list1}")
        blocks.append("\n".join(out))
    return "\n\n".join(blocks)


def render_skills(cv: dict) -> str:
    sk = cv.get("skills") or {}
    rows = []
    for label, key in (("Statistical Packages", "statistical_packages"),
                       ("Computer Languages", "computer_languages"),
                       ("Computer Applications", "computer_applications"),
                       ("Languages", "languages")):
        if sk.get(key):
            value = tex_escape(en(sk[key])).replace("LaTeX", "\\LaTeX{}")
            rows.append(f"\\textbf{{{label}:}} {value}")
    return " \\\\\n".join(rows)


def render_field_research(cv: dict) -> str:
    return " \\\\\n".join(f"{tex_escape(en(f.get('place')))}, {tex_escape(en(f.get('years')))}"
                          for f in cv.get("field_research") or [])


def render_other_service(cv: dict) -> str:
    os_data = cv.get("other_service") or {}
    out = []
    vols = os_data.get("volunteer") or []
    if vols:
        out.append("\\textbf{Volunteer}: \\\\")
        out.append(" \\\\\n".join(f"{tex_escape(v.get('org'))} ({dash_ranges(v.get('dates'))}): "
                                  f"{tex_escape(en(v.get('role')))}." for v in vols) + " \\\\")
    eo = os_data.get("election_observer") or []
    if eo:
        out.append("\\textbf{International Election Observer}, "
                   + ", ".join(tex_escape(en(e)) for e in eo) + ".")
    return "\n".join(out)


def build_cv_generated(cv: dict) -> str:
    """Emit cv_generated.tex: one macro per main.tex section body, plus
    \\cvname and \\cvlastupdated.

    main.tex \\input's this in its PREAMBLE, uses \\cvlastupdated in the footer,
    and calls each section's macro under that section's \\section header.
    Defining macros rather than emitting text directly is what lets one file
    serve every position in the document; main.tex keeps only headers and
    layout glue.
    """
    svc = cv.get("professional_service") or {}

    def emph_join(items):
        return ",\n".join("\\emph{" + tex_escape(str(i)) + "}" for i in items)

    def plain_join(items):
        return ", ".join(tex_escape(str(i)) for i in items)

    # meta.last_updated.en reads "Last updated June 25, 2026"; the footer supplies
    # its own "Last updated", so strip the prefix and keep just the date.
    raw = ((cv.get("meta") or {}).get("last_updated") or {}).get("en", "")
    date = re.sub(r"^\s*Last updated\s*", "", raw).strip() or raw

    parts = [
        "% ----------------------------------------------------------",
        "% Generated by scripts/build-cv-latex.py — do not hand-edit.",
        "% Source of truth: _data/cv.yml. Edit there, rebuild, and the web CV",
        "% and this PDF change together.",
        "%",
        "% main.tex \\input's this in its PREAMBLE, puts \\cvlastupdated in the",
        "% footer, and calls each macro below under its \\section header.",
        "% ----------------------------------------------------------",
        "",
        "\\newcommand{\\cvname}{" + tex_escape((cv.get("meta") or {}).get("name", "")) + "}",
        "",
        "\\newcommand{\\cvlastupdated}{" + tex_escape(date) + "}",
        "",
        "\\newcommand{\\cvservicelists}{%",
        "\\textbf{Journal \\& Press Peer Review}\\\\",
        emph_join(svc.get("journal_review") or []),
        "",
        "\\textbf{Grant Review}\\\\",
        plain_join(svc.get("grant_review") or []),
        "",
        "\\textbf{Government Agency Review}\\\\",
        plain_join(svc.get("government_review") or []),
        "}",
        "",
        "\\newcommand{\\cvgrants}{%",
        render_grant_rows(cv.get("grants") or []),
        "}",
        "",
        "\\newcommand{\\cvdeptservice}{%",
        render_service_tabbing(svc.get("departmental") or []),
        "}",
        "",
        "\\newcommand{\\cvuniversityservice}{%",
        render_service_tabbing((svc.get("university") or {}).get("entries") or []),
        "}",
        "",
        "\\newcommand{\\cvprofession}{%",
        render_service_tabbing(svc.get("profession") or []),
        "}",
        "",
        "\\newcommand{\\cvfoundernote}{"
        + tex_escape((svc.get("university") or {}).get("founder_note") or "") + "}",
        "",
    ]
    for name, render in (("cvcontact", render_contact),
                         ("cvappointments", render_appointments),
                         ("cvaffiliations", render_affiliations),
                         ("cveducation", render_education),
                         ("cvsoftware", render_software),
                         ("cvevaluations", render_evaluations),
                         ("cvtestimony", render_testimony),
                         ("cvpresentations", render_presentations),
                         ("cvteaching", render_teaching),
                         ("cvmentorship", render_mentorship),
                         ("cvexperience", render_experience),
                         ("cvskills", render_skills),
                         ("cvfieldresearch", render_field_research),
                         ("cvotherservice", render_other_service)):
        parts += [f"\\newcommand{{\\{name}}}{{%", render(cv), "}", ""]
    return "\n".join(parts)


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

    gen = build_cv_generated(cv)
    OUT_GEN.write_text(gen, encoding="utf-8")
    if OVERLEAF_DROPBOX_DIR.exists():
        OVERLEAF_GEN.write_text(gen, encoding="utf-8")

    svc = cv.get("professional_service") or {}
    print(f"  Wrote {OUT}", file=sys.stderr)
    print(f"  Wrote {OUT_GEN}", file=sys.stderr)
    print(f"  Journals reviewed: {len(svc.get('journal_review') or [])}", file=sys.stderr)
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
