#!/usr/bin/env python3
"""
build-cv.py — Generate cv.qmd from structured sources.

Reads:
  _data/cv.yml                                  non-publication content + i18n strings
  _data/cv-tag-proposal.yml                     publication assignments by section
  ~/Dropbox/research_projects/My Library.json   full Zotero CSL JSON

Writes:
  cv.qmd                                        the multilingual CV page

Architecture:
  - English is rendered into the page (so it works without JS).
  - Every translatable element is wrapped in <span data-i18n="key">English</span>.
  - All language values are inlined into a JSON blob in <script id="cv-i18n">.
  - The JS toggle (also inlined) reads the active language from URL ?lang= or
    localStorage, swaps each [data-i18n] textContent, and persists choice.
  - Publications are formatted directly from Zotero CSL JSON in the bespoke
    style (linked title, italic venue, vol(issue) pages, with co-authors,
    then —prefixed annotation lines beneath).

Currently English-only (Phase 2.0). The translation pipeline (Phase 2.5) will
fill in the other 6 language fields in cv.yml and re-run this script.

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
CV_OUT = REPO / "cv.qmd"

ACTIVE_LANG = "en"
SUPPORTED = ("en", "fr", "es", "ru", "uk", "ka", "de")

PUB_SECTIONS = [
    # (cv-tag-proposal key, cv.yml section_headers key, numbered)
    ("peer-reviewed",   "peer_reviewed",   True),
    # under_review is rendered between here and editor-reviewed, from cv.yml
    ("editor-reviewed", "editor_reviewed", True),
    ("book-review",     "book_reviews",    False),
    ("blog",            "blogs",           False),
    ("working-paper",   "working_papers",  False),
    # in-prep and on-hold also from cv.yml plain entries (after working papers)
]


# ---------- helpers ----------

_HREF_RE = re.compile(r"\\href\s*\{([^}]+)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}")


# Institution name overrides: loaded lazily, matched by exact English
# string including the parenthesized abbreviation. Used by render_affiliations
# (and future renderers) to emit <span data-i18n="institutions.<slug>">
# so the language toggle picks up the local form (e.g. CSDC → CÉCD in FR).
_INSTITUTION_INDEX_CACHE = None

def _institution_slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:60]


def _load_institution_index() -> dict:
    """Return {english_canonical_string: (slug, variant)} for overrides
    in institution-names.yml. variant is '' for plain name or 'combined'
    for the '<Name> (<Abbr>)' form."""
    global _INSTITUTION_INDEX_CACHE
    if _INSTITUTION_INDEX_CACHE is not None:
        return _INSTITUTION_INDEX_CACHE
    index = {}
    path = Path(__file__).resolve().parents[1] / "_data" / "institution-names.yml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for e in data.get("institutions") or []:
            en = e.get("en")
            if not en:
                continue
            slug = _institution_slug(en)
            # Plain English name → name-only key
            index[en] = (slug, "")
            # "Name (ABBR)" form → combined key
            if e.get("abbr_en"):
                index[f"{en} ({e['abbr_en']})"] = (slug, "combined")
    _INSTITUTION_INDEX_CACHE = index
    return index


def institution_span(org_string: str) -> str:
    """If org_string matches an entry in institution-names.yml, return an i18n
    span so the language toggle swaps to the local form. Otherwise return
    the plain escaped string."""
    idx = _load_institution_index()
    if org_string in idx:
        slug, variant = idx[org_string]
        key = f"institutions.{slug}.combined" if variant == "combined" else f"institutions.{slug}"
        return f'<span data-i18n="{key}">{html_escape(org_string)}</span>'
    return html_escape(org_string)


def latex_to_html(text: str) -> str:
    """Convert LaTeX \\href{url}{label} and inline markup to safe HTML."""
    def _href(m):
        url = m.group(1).strip()
        label = m.group(2)
        label = re.sub(r"\\textit\{([^{}]*)\}", r"<em>\1</em>", label)
        label = re.sub(r"\\emph\{([^{}]*)\}", r"<em>\1</em>", label)
        label = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", label)
        label = re.sub(r"[{}]", "", label).strip()
        return f'<a href="{html_escape(url)}" class="cv-pub-media-link">{label}</a>'
    text = _HREF_RE.sub(_href, text)
    text = re.sub(r"\\textit\{([^{}]*)\}", r"<em>\1</em>", text)
    text = re.sub(r"\\emph\{([^{}]*)\}", r"<em>\1</em>", text)
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"[{}]", "", text)
    return text.strip()


def html_escape(s) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def i18n_span(key: str, text: str, tag: str = "span") -> str:
    return f'<{tag} data-i18n="{key}">{html_escape(text)}</{tag}>'


def collect_i18n(node, prefix="") -> dict:
    """Walk the YAML and collect every multilingual leaf."""
    result = {}
    if isinstance(node, dict):
        keys = set(node.keys())
        if keys and keys.issubset(set(SUPPORTED)):
            result[prefix] = {k: node[k] for k in keys}
            return result
        for k, v in node.items():
            child_prefix = f"{prefix}.{k}" if prefix else k
            result.update(collect_i18n(v, child_prefix))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            child_prefix = f"{prefix}.{i}"
            result.update(collect_i18n(v, child_prefix))
    return result


def t(node, dotted: str, lang: str = ACTIVE_LANG) -> str:
    parts = dotted.split(".")
    cur = node
    for p in parts:
        if isinstance(cur, list):
            cur = cur[int(p)]
        else:
            cur = cur[p]
    if isinstance(cur, dict):
        return cur.get(lang, cur.get("en", ""))
    return str(cur)


def fmt_authors(author_list, drop_last_name="erlich") -> str:
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


_YEAR_SORT_RE = re.compile(r"(\d{4})")

def year_sort_key(value) -> int:
    """Extract the first 4-digit year from a free-form string like '2025',
    '2025-26', 'Fall 2024', 'April 2025', 'Aug 2023'. Returns 0 when no
    year is found, so unknown-year entries sink."""
    if value is None:
        return 0
    m = _YEAR_SORT_RE.search(str(value))
    return int(m.group(1)) if m else 0


def _detect_tex_cv(a: str):
    """Translate a raw Zotero `tex.cv-*` extra line into the same
    (label_key, label_text, content, css_class) shape the LaTeX patterns
    produce. These are written into the proposal's latex_annotations by the
    Flask admin (cv_admin.py) and cv-add.py."""
    body = a[len("tex.cv-"):]
    kind, _, rest = body.partition(":")
    kind, rest = kind.strip(), rest.strip()
    if kind == "award":
        sub, _, value = rest.partition("|")
        sub, value = sub.strip(), value.strip()
        if sub == "honorable-mention":
            return "labels.award_honorable_mention", "Honourable Mention", value, "cv-pub-award"
        if sub == "top-cited":
            return "labels.top_cited", "Top 10 Most Cited", value, "cv-pub-award"
        return "labels.award_winner", "Winner", value, "cv-pub-award"
    if kind == "media":
        fields = [p.strip() for p in rest.split("|")]
        # outlet-kind | label | url  (3 fields) or  other | text  (2 fields)
        if len(fields) >= 3 and fields[2]:
            content = f"\\href{{{fields[2]}}}{{\\textit{{{fields[1]}}}}}"
        else:
            content = fields[-1]
        return "labels.media_coverage", "Media coverage", content, "cv-pub-media"
    if kind == "press-release":
        content = f"\\href{{{rest}}}{{{rest}}}" if rest.startswith("http") else rest
        return "labels.press_release", "Press release", content, "cv-pub-pressrelease"
    if kind == "note":
        return None, None, rest, "cv-pub-note"
    return None, None, a, "cv-pub-note"


def detect_annotation(ann: str):
    """Return (label_key, label_text, content, css_class) for an annotation.

    Handles both the human-readable LaTeX form parsed from the original CV
    (e.g. "Media coverage: \\href{}{}") and the raw Zotero `tex.cv-*` form
    written into latex_annotations by the admin UI."""
    a = ann.strip().rstrip(".")
    if a.startswith("tex.cv-"):
        return _detect_tex_cv(a)
    patterns = [
        (r"(?i)^winner\s*[:\-]\s*(.+)",
         "labels.award_winner", "Winner", "cv-pub-award"),
        (r"(?i)^hono(?:u)?rable\s*mention\s*[:\-]\s*(.+)",
         "labels.award_honorable_mention", "Honourable Mention", "cv-pub-award"),
        (r"(?i)^media\s*coverage\s*[:\-]?\s*(.+)",
         "labels.media_coverage", "Media coverage", "cv-pub-media"),
        (r"(?i)^press\s*release\s*[:\-]?\s*(.+)",
         "labels.press_release", "Press release", "cv-pub-pressrelease"),
        (r"(?i)^top\s+\d+\s+most\s+cited\s*(?:article\s+award)?\s*(.+)?",
         "labels.top_cited", "Top 10 Most Cited", "cv-pub-award"),
    ]
    for pat, key, label, cls in patterns:
        m = re.match(pat, a)
        if m:
            content = (m.group(1) or "").strip() if m.lastindex else ""
            return key, label, content, cls
    return None, None, a, "cv-pub-note"


# ---------- publication renderer ----------

def render_publication(item: dict, citekey: str, annotations: list, label_with: str,
                        status: str = "") -> str:
    title = item.get("title") or "(untitled)"
    venue = item.get("container-title") or item.get("collection-title") or ""
    volume = item.get("volume") or ""
    issue = item.get("issue") or ""
    pages = item.get("page") or ""
    year = get_year(item)
    doi = item.get("DOI") or ""
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    coauthors_str = fmt_authors(item.get("author") or [])

    parts = [f'<li class="cv-pub" id="pub-{html_escape(citekey)}">']

    if url:
        parts.append(f'<a class="cv-pub-title" href="{html_escape(url)}">&ldquo;{html_escape(title)}.&rdquo;</a>')
    else:
        parts.append(f'<span class="cv-pub-title">&ldquo;{html_escape(title)}.&rdquo;</span>')

    # `status` (e.g., "Forthcoming", "Online First", "Accepted") takes precedence
    # over `year` — used for accepted-but-undated papers. Sort order handled at
    # the section level: papers with a status are pinned to the top.
    if status:
        parts.append(f' <span class="cv-pub-status">{html_escape(status)}.</span>')
    elif year:
        parts.append(f' <span class="cv-pub-year">{year}.</span>')
    if venue:
        parts.append(f' <em class="cv-pub-venue">{html_escape(venue)}</em>')
    if volume:
        if issue:
            parts.append(f' <span class="cv-pub-vol">{html_escape(volume)}({html_escape(issue)})</span>')
        else:
            parts.append(f' <span class="cv-pub-vol">{html_escape(volume)}</span>')
    if pages:
        parts.append(f' <span class="cv-pub-pages">{html_escape(pages)}</span>.')
    if coauthors_str:
        parts.append(
            f' <span class="cv-pub-coauthors">'
            f'(<span data-i18n="labels.with">{html_escape(label_with)}</span> '
            f'{html_escape(coauthors_str)})</span>'
        )

    if annotations:
        parts.append('<ul class="cv-pub-notes">')
        # Group annotations that share a label so e.g. the original multi-outlet
        # "Media coverage" line and any outlets added later via the admin render
        # on ONE "Media coverage:" line instead of repeating the label. Distinct
        # labels (Winner vs Honourable Mention) still get their own lines; unlabeled
        # notes never merge.
        grouped = []          # [ [key, label, cls, [content, ...]], ... ]
        pos = {}              # label_key -> index in grouped
        for ann in annotations:
            key, label, content, cls = detect_annotation(ann)
            if key and key in pos:
                grouped[pos[key]][3].append(content)
            else:
                if key:
                    pos[key] = len(grouped)
                grouped.append([key, label, cls, [content]])
        for key, label, cls, contents in grouped:
            joined = ", ".join(latex_to_html(c) for c in contents if c)
            if label and key:
                parts.append(
                    f'<li class="{cls}">'
                    f'<strong data-i18n="{key}">{html_escape(label)}</strong>: '
                    f'{joined}</li>'
                )
            else:
                parts.append(f'<li class="{cls}">{joined}</li>')
        parts.append('</ul>')

    parts.append('</li>')
    return "\n".join(parts)


# ---------- non-publication renderers ----------

def render_contact(cv: dict) -> str:
    c = cv["contact"]
    return f"""<header class="cv-header">
<h1>{html_escape(cv["meta"]["name"])}</h1>
<table class="cv-contact-table">
<tr>
  <td>{i18n_span("contact.title", c["title"]["en"])}<br/>
      {i18n_span("contact.department", c["department"]["en"])}<br/>
      {html_escape(c["institution"])}<br/>
      {html_escape(c["address_line1"])}<br/>
      {html_escape(c["address_line2"])}<br/>
      {i18n_span("contact.country", c["country"]["en"])}</td>
  <td><em>Office:</em> {html_escape(c["office"])}<br/>
      <em>Voice:</em> {html_escape(c["phone"])}<br/>
      <em>E-mail:</em> <a href="mailto:{c["email"]}">{c["email"]}</a><br/>
      <em>Web:</em> <a href="https://{c["web"]}">{c["web"]}</a></td>
</tr>
</table>
</header>"""


def render_appointments(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.academic_appointments", t(cv, "section_headers.academic_appointments"))}</h2>']
    for i, app in enumerate(cv["academic_appointments"]):
        out.append('<div class="cv-block">')
        out.append(
            f'<div class="cv-block-institution">'
            f'<strong>{html_escape(app["institution"])}</strong>, '
            f'{i18n_span(f"academic_appointments.{i}.department", app["department"]["en"])}, '
            f'{html_escape(app["location"])}</div>'
        )
        out.append('<ul class="cv-block-positions">')
        for j, pos in enumerate(app["positions"]):
            line = f'<li>{i18n_span(f"academic_appointments.{i}.positions.{j}.role", pos["role"]["en"])}, {html_escape(pos["dates"])}'
            if pos.get("notes"):
                line += f' <em>{i18n_span(f"academic_appointments.{i}.positions.{j}.notes", pos["notes"]["en"])}</em>'
            out.append(line + '</li>')
        out.append('</ul></div>')
    return "\n".join(out)


def render_affiliations(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.affiliations", t(cv, "section_headers.affiliations"))}</h2>',
           '<ul class="cv-affil-list">']
    for i, a in enumerate(cv["affiliations"]):
        url = a.get("url", "")
        org_inner = institution_span(a["org"])
        org = f'<a href="{html_escape(url)}">{org_inner}</a>' if url else org_inner
        out.append(
            f'<li>{i18n_span(f"affiliations.{i}.role", a["role"]["en"])}, {org}, {html_escape(a["dates"])}</li>'
        )
    out.append('</ul>')
    return "\n".join(out)


def render_education(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.education", t(cv, "section_headers.education"))}</h2>']
    for i, edu in enumerate(cv["education"]):
        out.append('<div class="cv-block">')
        out.append(
            f'<div class="cv-block-institution">'
            f'<strong>{html_escape(edu["institution"])}</strong>, {html_escape(edu["location"])}</div>'
        )
        out.append('<ul>')
        for j, deg in enumerate(edu["degrees"]):
            year = deg.get("year", "")
            out.append(
                f'<li>{i18n_span(f"education.{i}.degrees.{j}.degree", deg["degree"]["en"])}, {year}</li>'
            )
        out.append('</ul></div>')
    return "\n".join(out)


def render_publications_section(cv: dict, proposal: dict, by_citekey: dict, label_with: str,
                                proposal_key: str, header_key: str, numbered: bool) -> str:
    items = (proposal.get("sections") or {}).get(proposal_key) or []

    def _year(e: dict) -> int:
        """Sort key — prefer Zotero `issued` year (authoritative), fall back
        to proposal's `latex_year`, then 0 so unknown-year entries sink."""
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

    # Status entries (Forthcoming / Online First) pin to the top. Below
    # them, sort reverse-chronologically by year.
    items = sorted(
        items,
        key=lambda e: (
            0 if e.get("latex_status") else 1,  # status first
            -_year(e),                           # newest first
        ),
    )
    out = [f'<h2>{i18n_span(f"section_headers.{header_key}", t(cv, f"section_headers.{header_key}"))}</h2>']
    if not items:
        out.append('<p><em>(none)</em></p>')
        return "\n".join(out)
    if numbered:
        out.append(f'<ol class="cv-pub-list cv-pub-list--reverse" style="--cv-pub-start: {len(items) + 1}">')
    else:
        out.append('<ul class="cv-pub-list cv-pub-list--dash">')
    for entry in items:
        ck = entry.get("match_citekey")
        anns = entry.get("latex_annotations") or []
        status = entry.get("latex_status") or ""
        if ck and ck != "SKIP" and ck in by_citekey:
            out.append(render_publication(by_citekey[ck], ck, anns, label_with, status=status))
        else:
            # Fall back to LaTeX title + optional latex_url for a link
            title = entry.get("latex_title") or "(untitled)"
            year = entry.get("latex_year") or ""
            url = entry.get("latex_url") or ""
            year_html = f' <span class="cv-pub-year">{year}.</span>' if year else ''
            if url:
                title_html = f'<a class="cv-pub-title" href="{html_escape(url)}">&ldquo;{html_escape(title)}&rdquo;</a>'
            else:
                title_html = f'<span class="cv-pub-title">&ldquo;{html_escape(title)}&rdquo;</span>'
            note = ""
            if ck and ck != "SKIP" and ck not in by_citekey:
                note = f' <em class="cv-pub-stub">[citekey {html_escape(ck)} not in Zotero]</em>'
            # Render annotation lines if any
            ann_html = ""
            if entry.get("latex_annotations"):
                ann_parts = ['<ul class="cv-pub-notes">']
                for ann in entry["latex_annotations"]:
                    ann_parts.append(f'<li class="cv-pub-note">{html_escape(ann)}</li>')
                ann_parts.append('</ul>')
                ann_html = "".join(ann_parts)
            out.append(
                f'<li class="cv-pub cv-pub--stub">{title_html}{year_html}{note}{ann_html}</li>'
            )
    out.append('</ol>' if numbered else '</ul>')
    return "\n".join(out)


def render_grants(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.grants", t(cv, "section_headers.grants"))}</h2>']
    # Keep original index for i18n keys — sort indices by year desc.
    grants = cv["grants"]
    order = sorted(range(len(grants)), key=lambda i: -year_sort_key(grants[i].get("year")))
    for i in order:
        g = grants[i]
        title_html = i18n_span(f"grants.{i}.title", g["title"]["en"])
        if g.get("agency"):
            title_html += f' &mdash; {html_escape(g["agency"])}'
        if g.get("role"):
            title_html += f' (<span data-i18n="grants.{i}.role">{html_escape(g["role"]["en"])}</span>)'
        if g.get("notes"):
            title_html += f' <em>{i18n_span(f"grants.{i}.notes", g["notes"]["en"])}</em>'
        out.append(
            f'<div class="cv-grant">'
            f'<div class="cv-grant-year">{html_escape(g.get("year",""))}</div>'
            f'<div class="cv-grant-title">{title_html}</div>'
            f'<div class="cv-grant-amount">{html_escape(g.get("amount",""))}</div>'
            f'</div>'
        )
    return "\n".join(out)


def render_software(cv: dict, label_with: str) -> str:
    out = [f'<h2>{i18n_span("section_headers.software", t(cv, "section_headers.software"))}</h2>']
    for i, s in enumerate(cv["software"]):
        url = s.get("url", "")
        name_html = (
            f'<a href="{html_escape(url)}"><code>{html_escape(s["name"])}</code></a>'
            if url else f'<code>{html_escape(s["name"])}</code>'
        )
        line = (
            f'<p>{name_html}: '
            f'{i18n_span(f"software.{i}.description", s["description"]["en"])}'
        )
        if s.get("coauthors"):
            line += (
                f' (<span data-i18n="labels.with">{html_escape(label_with)}</span> '
                f'{html_escape(", ".join(s["coauthors"]))})'
            )
        line += '</p>'
        out.append(line)
    return "\n".join(out)


def render_professional_evals(cv: dict, label_with: str) -> str:
    out = [f'<h2>{i18n_span("section_headers.professional_evaluations", t(cv, "section_headers.professional_evaluations"))}</h2>',
           '<ul class="cv-pub-list cv-pub-list--dash">']
    for i, e in enumerate(cv["professional_evaluations"]):
        line = i18n_span(f"professional_evaluations.{i}.title", e["title"]["en"])
        if e.get("coauthors"):
            line += (
                f' (<span data-i18n="labels.with">{html_escape(label_with)}</span> '
                f'{html_escape(", ".join(e["coauthors"]))})'
            )
        if e.get("submitted_to"):
            line += f'. {i18n_span(f"professional_evaluations.{i}.submitted_to", e["submitted_to"]["en"])}'
        if e.get("year"):
            line += f', {e["year"]}'
        out.append(f'<li class="cv-pub">{line}.</li>')
    out.append('</ul>')
    return "\n".join(out)


def render_testimony(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.testimony", t(cv, "section_headers.testimony"))}</h2>']
    for i, ti in enumerate(cv["testimony"]):
        title_html = i18n_span(f"testimony.{i}.title", ti["title"]["en"])
        if ti.get("url"):
            title_html = f'<a href="{html_escape(ti["url"])}">{title_html}</a>'
        out.append(
            f'<p>{title_html}. '
            f'{i18n_span(f"testimony.{i}.venue", ti["venue"]["en"])} '
            f'({html_escape(ti.get("date",""))}).</p>'
        )
    return "\n".join(out)


def render_field_research(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.field_research", t(cv, "section_headers.field_research"))}</h2>',
           '<ul>']
    for f in cv["field_research"]:
        out.append(f'<li>{html_escape(f["place"])}, {html_escape(f["years"])}</li>')
    out.append('</ul>')
    return "\n".join(out)


def render_skills(cv: dict) -> str:
    sk = cv["skills"]
    return f"""<h2>{i18n_span("section_headers.skills", t(cv, "section_headers.skills"))}</h2>
<p><strong>Statistical Packages:</strong> {i18n_span("skills.statistical_packages", sk["statistical_packages"]["en"])}</p>
<p><strong>Computer Languages:</strong> {i18n_span("skills.computer_languages", sk["computer_languages"]["en"])}</p>
<p><strong>Computer Applications:</strong> {i18n_span("skills.computer_applications", sk["computer_applications"]["en"])}</p>
<p><strong>Languages:</strong> {i18n_span("skills.languages", sk["languages"]["en"])}</p>"""


def _format_coauthors(authors):
    """Render a list of coauthors as 'A, B, and C'."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return ", ".join(authors[:-1]) + f", and {authors[-1]}"


def render_simple_pubs(cv: dict, key: str, header_key: str, numbered: bool = False) -> str:
    """Render under_review / in_prep / on_hold entries from cv.yml.

    Format mirrors the original LaTeX:
        "Title." (with Co1 and Co2) <em>Status</em>

    Title is a clickable link only when entry has a 'url' field.
    If numbered=True, uses reverse-numbered list (etaremune-style)."""
    items = cv.get(key, []) or []
    out = [f'<h2>{i18n_span(f"section_headers.{header_key}", t(cv, f"section_headers.{header_key}"))}</h2>']
    if not items:
        return "\n".join(out)
    if numbered:
        out.append(f'<ol class="cv-pub-list cv-pub-list--reverse" style="--cv-pub-start: {len(items) + 1}">')
    else:
        out.append('<ul class="cv-pub-list cv-pub-list--dash">')
    for it in items:
        title = html_escape(it.get("title", ""))
        url = it.get("url") or ""
        year = it.get("year")
        status = it.get("status")
        coauthors = it.get("coauthors") or []
        # Title (link or plain)
        if url:
            title_html = f'<a class="cv-pub-title" href="{html_escape(url)}">&ldquo;{title}.&rdquo;</a>'
        else:
            title_html = f'<span class="cv-pub-title-plain">&ldquo;{title}.&rdquo;</span>'
        # Year (only if set)
        year_html = f' <span class="cv-pub-year">{year}.</span>' if year else ''
        # Coauthors
        co_html = ""
        if coauthors:
            co_html = f' (with {html_escape(_format_coauthors(coauthors))})'
        # Status (italicized — matches LaTeX \textit{...})
        status_html = f' <em class="cv-pub-status">{html_escape(status)}</em>' if status else ''
        out.append(f'<li class="cv-pub">{title_html}{year_html}{co_html}{status_html}</li>')
    out.append('</ol>' if numbered else '</ul>')
    return "\n".join(out)


def render_presentations(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.presentations", t(cv, "section_headers.presentations"))}</h2>',
           '<p><em>★ denotes invited talk</em></p>',
           '<ul class="cv-pub-list cv-pub-list--dash">']
    # Sort by the year parsed out of `date` (free-form, e.g.,
    # "April 2025" / "Fall 2023"), newest first.
    entries = sorted(cv.get("presentations", []),
                     key=lambda p: -year_sort_key(p.get("date")))
    for p in entries:
        invited_mark = '<span class="invited-mark">★</span> ' if p.get("invited") else ''
        title = html_escape(p.get("title", ""))
        venue = html_escape(p.get("venue", ""))
        date = html_escape(p.get("date", ""))
        out.append(
            f'<li class="cv-pub">{invited_mark}&ldquo;{title}.&rdquo; {venue}, {date}.</li>'
        )
    out.append('</ul>')
    return "\n".join(out)


def render_teaching(cv: dict) -> str:
    tc = cv.get("teaching", {})
    out = [f'<h2>{i18n_span("section_headers.teaching", t(cv, "section_headers.teaching"))}</h2>']
    # Instructor
    out.append(f'<h3>{i18n_span("section_headers.courses_taught", t(cv, "section_headers.courses_taught"))}</h3>')
    out.append('<p><em>Instructor</em></p>')
    out.append('<p><strong>Undergraduate:</strong></p><ul>')
    for c in tc.get("instructor", {}).get("undergraduate", []):
        out.append(f'<li>{html_escape(c["course"])} [{html_escape(c["code"])}] ({html_escape(c["institution"])})</li>')
    out.append('</ul><p><strong>Graduate:</strong></p><ul>')
    for c in tc.get("instructor", {}).get("graduate", []):
        out.append(f'<li>{html_escape(c["course"])} [{html_escape(c["code"])}] ({html_escape(c["institution"])})</li>')
    out.append('</ul>')
    # GSI
    out.append(f'<h3>{i18n_span("section_headers.graduate_student_instructor", t(cv, "section_headers.graduate_student_instructor"))}</h3>')
    out.append('<p><strong>Undergraduate:</strong></p><ul>')
    for c in tc.get("gsi", {}).get("undergraduate", []):
        out.append(f'<li>{html_escape(c["course"])} [{html_escape(c["code"])}] ({html_escape(c["institution"])})</li>')
    out.append('</ul><p><strong>Graduate:</strong></p><ul>')
    for c in tc.get("gsi", {}).get("graduate", []):
        out.append(f'<li>{html_escape(c["course"])} [{html_escape(c["code"])}] ({html_escape(c["institution"])})</li>')
    out.append('</ul>')
    return "\n".join(out)


def render_mentorship(cv: dict) -> str:
    ms = cv.get("mentorship", {})
    out = [f'<h3>{i18n_span("section_headers.mentorship_header", t(cv, "section_headers.mentorship_header"))}</h3>']
    for level, label, show_placement in [
        ("phd", "Ph.D. in Political Science", True),
        ("ma", "M.A. in Political Science", True),
        ("undergraduate", "Undergraduate", False),
    ]:
        entries = ms.get(level, [])
        if not entries:
            continue
        # Sort each cohort by graduation year, newest first
        entries = sorted(entries, key=lambda m: -year_sort_key(m.get("year")))
        out.append(f'<p><strong>{label}</strong> (year of graduation)</p>')
        if show_placement:
            out.append('<table><thead><tr><th>Year</th><th>Name</th><th>Roles</th><th>Placement</th></tr></thead><tbody>')
        else:
            out.append('<table><thead><tr><th>Year</th><th>Name</th><th>Roles</th></tr></thead><tbody>')
        for m in entries:
            yr = html_escape(str(m.get("year", "")))
            nm = html_escape(m.get("name", ""))
            rl = html_escape(m.get("roles", ""))
            if show_placement:
                pl = html_escape(m.get("placement", ""))
                out.append(f'<tr><td>{yr}</td><td>{nm}</td><td>{rl}</td><td>{pl}</td></tr>')
            else:
                out.append(f'<tr><td>{yr}</td><td>{nm}</td><td>{rl}</td></tr>')
        out.append('</tbody></table>')
    return "\n".join(out)


def render_professional_experience(cv: dict) -> str:
    out = [f'<h2>{i18n_span("section_headers.relevant_experience", t(cv, "section_headers.relevant_experience"))}</h2>']
    # Sort by the start year parsed out of `dates` (e.g., "2010 — 2012"),
    # newest first. Entries without a parseable date sink.
    entries = sorted(cv.get("professional_experience", []),
                     key=lambda e: -year_sort_key(e.get("dates")))
    for exp in entries:
        out.append('<div class="cv-block">')
        emp = html_escape(exp.get("employer", ""))
        loc = exp.get("locations", "")
        role = html_escape(exp.get("role", ""))
        dates = html_escape(exp.get("dates", ""))
        header = f'<div class="cv-block-institution"><strong>{emp}</strong>'
        if loc:
            header += f', {html_escape(loc)}'
        header += f'</div><p><em>{role}</em> &mdash; {dates}</p>'
        out.append(header)
        if exp.get("bullets"):
            out.append('<ul>')
            for b in exp["bullets"]:
                out.append(f'<li>{html_escape(b)}</li>')
            out.append('</ul>')
        out.append('</div>')
    return "\n".join(out)


def _group_by_year_and_render(entries: list, out: list) -> None:
    """Merge entries that share a `year` and render reverse-chronologically.
    Used by service subsections where multiple roles in the same year
    should appear on one line as `<year> — role1; role2; role3`."""
    # Preserve role order within each year by iterating entries in list order
    from collections import OrderedDict
    buckets: "OrderedDict[str, list[str]]" = OrderedDict()
    for entry in entries:
        yr = str(entry.get("year", ""))
        buckets.setdefault(yr, []).extend(entry.get("roles", []) or [])
    # Sort years reverse-chronologically; unknown years (0) sink to the bottom
    for yr, roles in sorted(buckets.items(), key=lambda kv: -year_sort_key(kv[0])):
        out.append(
            f'<p class="cv-service-year"><strong>{html_escape(yr)}</strong> &mdash; '
            f'{"; ".join(html_escape(r) for r in roles)}</p>'
        )


def render_professional_service(cv: dict) -> str:
    ps = cv.get("professional_service", {})
    out = [f'<h2>{i18n_span("section_headers.professional_service", t(cv, "section_headers.professional_service"))}</h2>']
    # Departmental — group by year, reverse-chron
    out.append('<h3>Departmental Service</h3>')
    _group_by_year_and_render(ps.get("departmental", []), out)
    # University — same
    out.append('<h3>University Service</h3>')
    uni = ps.get("university", {})
    if uni.get("founder_note"):
        out.append(f'<p><em>{html_escape(uni["founder_note"])}</em></p>')
    _group_by_year_and_render(uni.get("entries", []), out)
    # Profession — same
    out.append('<h3>Profession</h3>')
    _group_by_year_and_render(ps.get("profession", []), out)
    # Journal review
    jrl = ps.get("journal_review", [])
    if jrl:
        out.append(f'<h3>{i18n_span("section_headers.journal_review", t(cv, "section_headers.journal_review"))}</h3>')
        out.append('<p>' + ", ".join(f"<em>{html_escape(j)}</em>" for j in jrl) + '</p>')
    # Grant review
    grl = ps.get("grant_review", [])
    if grl:
        out.append(f'<h3>{i18n_span("section_headers.grant_review_header", t(cv, "section_headers.grant_review_header"))}</h3>')
        out.append('<p>' + ", ".join(html_escape(g) for g in grl) + '</p>')
    # Government review
    gov = ps.get("government_review", [])
    if gov:
        out.append(f'<h3>{i18n_span("section_headers.government_review", t(cv, "section_headers.government_review"))}</h3>')
        out.append('<p>' + ", ".join(html_escape(g) for g in gov) + '</p>')
    return "\n".join(out)


def render_other_service(cv: dict) -> str:
    os_data = cv.get("other_service", {})
    out = [f'<h2>{i18n_span("section_headers.other_service", t(cv, "section_headers.other_service"))}</h2>']
    # Volunteer
    vols = os_data.get("volunteer", [])
    if vols:
        out.append(f'<h3>{i18n_span("section_headers.volunteer", t(cv, "section_headers.volunteer"))}</h3>')
        out.append('<ul>')
        for v in vols:
            out.append(f'<li><strong>{html_escape(v["org"])}</strong>, {html_escape(v["dates"])} &mdash; {html_escape(v["role"])}</li>')
        out.append('</ul>')
    # Election observer
    eo = os_data.get("election_observer", [])
    if eo:
        out.append(f'<h3>{i18n_span("section_headers.election_observer", t(cv, "section_headers.election_observer"))}</h3>')
        out.append('<p>' + "; ".join(html_escape(e) for e in eo) + '</p>')
    return "\n".join(out)


# ---------- inline JS toggle ----------

JS_TOGGLE = r"""
(function () {
  var STORAGE_KEY = "cv_lang";
  var DEFAULT_LANG = "en";
  var SUPPORTED = ["en", "fr", "es", "ru", "uk", "ka", "de"];
  var LANG_NAMES = {
    en: "English", fr: "Français", es: "Español",
    ru: "Русский", uk: "Українська", ka: "ქართული", de: "Deutsch"
  };

  // Apply pending class as early as possible to suppress flicker
  document.documentElement.classList.add("cv-i18n-pending");

  function getLang() {
    try {
      var url = new URL(window.location.href);
      var fromUrl = url.searchParams.get("lang");
      if (fromUrl && SUPPORTED.indexOf(fromUrl) !== -1) return fromUrl;
      var stored = localStorage.getItem(STORAGE_KEY);
      if (stored && SUPPORTED.indexOf(stored) !== -1) return stored;
    } catch (e) {}
    return DEFAULT_LANG;
  }

  function applyTranslations(lang) {
    var blob = document.getElementById("cv-i18n");
    if (!blob) return;
    var i18n;
    try { i18n = JSON.parse(blob.textContent); }
    catch (e) { console.error("cv-i18n parse failed", e); return; }
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute("data-i18n");
      var entry = i18n[key];
      if (!entry) continue;
      var text = entry[lang] || entry.en || "";
      if (text) el.textContent = text;
    }
    document.documentElement.lang = lang;
    document.documentElement.classList.remove("cv-i18n-pending");
    document.documentElement.classList.add("cv-i18n-ready");
  }

  function setLang(lang) {
    if (SUPPORTED.indexOf(lang) === -1) return;
    try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    applyTranslations(lang);
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("lang", lang);
      history.replaceState(null, "", url.toString());
    } catch (e) {}
    var sel = document.getElementById("cv-lang-select");
    if (sel) sel.value = lang;
  }

  function buildToggle() {
    if (document.getElementById("cv-lang-toggle")) return;
    var wrapper = document.createElement("div");
    wrapper.id = "cv-lang-toggle";
    wrapper.style.cssText = "position:fixed;top:0.6em;right:0.8em;z-index:1000;background:#fff;border:1px solid #ccc;border-radius:4px;padding:0.2em 0.4em;font-size:0.85em;box-shadow:0 1px 4px rgba(0,0,0,0.08)";
    var label = document.createElement("label");
    label.setAttribute("for", "cv-lang-select");
    label.textContent = "🌐 ";
    var sel = document.createElement("select");
    sel.id = "cv-lang-select";
    sel.style.cssText = "border:0;background:transparent;font-size:inherit;cursor:pointer";
    for (var i = 0; i < SUPPORTED.length; i++) {
      var opt = document.createElement("option");
      opt.value = SUPPORTED[i];
      opt.textContent = LANG_NAMES[SUPPORTED[i]];
      sel.appendChild(opt);
    }
    sel.addEventListener("change", function () { setLang(sel.value); });
    wrapper.appendChild(label);
    wrapper.appendChild(sel);
    document.body.appendChild(wrapper);
  }

  function init() {
    buildToggle();
    setLang(getLang());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
"""


# ---------- main ----------

def main():
    cv = yaml.safe_load(CV_YAML.read_text(encoding="utf-8"))
    proposal = yaml.safe_load(PROPOSAL.read_text(encoding="utf-8"))
    zotero = json.loads(ZOTERO_JSON.read_text(encoding="utf-8"))

    by_citekey = {}
    for item in zotero:
        ck = item.get("citation-key") or item.get("citekey")
        if ck:
            by_citekey[ck] = item

    label_with = cv["labels"]["with"]["en"]

    pdf_url_active = cv["meta"]["pdf_url"][ACTIVE_LANG]
    last_updated = cv["meta"]["last_updated"]["en"]
    download_label = cv["labels"]["download_pdf"]["en"]

    body_parts = []
    body_parts.append(
        f'<div class="cv-toolbar">'
        f'<a href="{html_escape(pdf_url_active)}" class="btn btn-primary" '
        f'data-i18n="labels.download_pdf">{html_escape(download_label)}</a> &nbsp; '
        f'<em><span data-i18n="meta.last_updated">{html_escape(last_updated)}</span></em>'
        f'</div>'
    )
    body_parts.append(render_contact(cv))
    body_parts.append(render_appointments(cv))
    body_parts.append(render_affiliations(cv))
    body_parts.append(render_education(cv))

    # Peer-reviewed (numbered)
    body_parts.append(
        render_publications_section(cv, proposal, by_citekey, label_with,
                                    "peer-reviewed", "peer_reviewed", True)
    )
    # Under review (numbered, from cv.yml)
    body_parts.append(render_simple_pubs(cv, "under_review", "under_review", numbered=True))
    # Editor-reviewed (numbered)
    body_parts.append(
        render_publications_section(cv, proposal, by_citekey, label_with,
                                    "editor-reviewed", "editor_reviewed", True)
    )
    # Book reviews / blogs / working papers (dash, from Zotero)
    for proposal_key, header_key, numbered in [
        ("book-review",   "book_reviews",   False),
        ("blog",          "blogs",          False),
        ("working-paper", "working_papers", False),
    ]:
        body_parts.append(
            render_publications_section(cv, proposal, by_citekey, label_with,
                                        proposal_key, header_key, numbered)
        )
    # In prep / on hold (dash, from cv.yml)
    body_parts.append(render_simple_pubs(cv, "in_prep", "in_prep", numbered=False))
    body_parts.append(render_simple_pubs(cv, "on_hold", "on_hold", numbered=False))
    body_parts.append(render_grants(cv))
    body_parts.append(render_software(cv, label_with))
    body_parts.append(render_professional_evals(cv, label_with))
    body_parts.append(render_testimony(cv))

    # Sections after Testimony are wrapped in collapsible <details> (closed by
    # default in HTML; PDF rendering ignores <details> and shows everything).
    def collapsible(label, content):
        return (
            f'<details class="cv-section-collapse">'
            f'<summary>{html_escape(label)}</summary>'
            f'{content}'
            f'</details>'
        )
    body_parts.append(collapsible("Recent Presentations", render_presentations(cv)))
    body_parts.append(collapsible("Teaching", render_teaching(cv)))
    body_parts.append(collapsible("Mentorship", render_mentorship(cv)))
    body_parts.append(collapsible("Relevant Professional Experience", render_professional_experience(cv)))
    body_parts.append(collapsible("Skills", render_skills(cv)))
    body_parts.append(collapsible("Field Research", render_field_research(cv)))
    body_parts.append(collapsible("Professional Service", render_professional_service(cv)))
    body_parts.append(collapsible("Other Service", render_other_service(cv)))

    # The i18n JSON blob + toggle JS are now loaded globally via
    # _generated/i18n-toggle.html (built by scripts/build-i18n.py and
    # included site-wide from _quarto.yml). No per-page inline needed.

    qmd = [
        "---",
        'title: "Curriculum Vitae"',
        "page-layout: full",
        "body-classes: cv-page",
        "format:",
        "  html:",
        "    toc: true",
        "    toc-location: left",
        "    section-divs: false",
        "---",
        "",
        "\n".join(body_parts),
    ]
    CV_OUT.write_text("\n".join(qmd), encoding="utf-8")

    print(f"  Wrote {CV_OUT}", file=sys.stderr)
    print(f"  Publications by section:", file=sys.stderr)
    total_match = 0
    total_items = 0
    for proposal_key, header_key, _ in PUB_SECTIONS:
        items = (proposal.get("sections") or {}).get(proposal_key) or []
        rendered = sum(
            1 for e in items
            if e.get("match_citekey") and e["match_citekey"] != "SKIP" and e["match_citekey"] in by_citekey
        )
        total_match += rendered
        total_items += len(items)
        print(f"    {header_key}: {rendered}/{len(items)}", file=sys.stderr)
    print(f"  Total: {total_match}/{total_items} entries rendered from Zotero (rest fall back to LaTeX titles)", file=sys.stderr)


if __name__ == "__main__":
    main()
