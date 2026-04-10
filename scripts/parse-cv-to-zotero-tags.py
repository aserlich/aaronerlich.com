#!/usr/bin/env python3
"""
parse-cv-to-zotero-tags.py

Parse the LaTeX CV (_data/cv_source.tex) and produce a Zotero tag proposal
YAML by fuzzy-matching each LaTeX entry against the user's Zotero library
via Better BibTeX's local JSON-RPC search.

Output: _data/cv-tag-proposal.yml — review and correct, then run apply-tags.py.

Requires: Zotero running locally with Better BibTeX (port 23119).
Stdlib only.
"""

from __future__ import annotations
import json
import re
import sys
import unicodedata
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LATEX = REPO / "_data" / "cv_source.tex"
OUTPUT = REPO / "_data" / "cv-tag-proposal.yml"
BBT_RPC = "http://localhost:23119/better-bibtex/json-rpc"

# LaTeX section header → CV section tag value
SECTION_TAG = {
    "Peer-Reviewed Publications": "peer-reviewed",
    "Under Review/To Resubmit": "under-review",
    "Editor-Reviewed Publications": "editor-reviewed",
    "Book Reviews": "book-review",
    "Blogs and Popular Press": "blog",
    "Published Working Papers": "working-paper",
    "Manuscripts in Preparation": "in-prep",
    "On Hold": "on-hold",
    "Software": "software",
    "Professional Evaluations and Reports": "professional-eval",
    "Testimony": "testimony",
}

HIGH_THRESHOLD = 0.90
LOW_THRESHOLD = 0.75


# ---------- BBT search ----------

def bbt_search(query: str) -> list:
    body = json.dumps({
        "jsonrpc": "2.0",
        "method": "item.search",
        "params": [query],
        "id": 1,
    }).encode("utf-8")
    req = urllib.request.Request(
        BBT_RPC, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        return data.get("result", []) or []
    except Exception as e:
        print(f"  ! BBT search failed for {query[:60]!r}: {e}", file=sys.stderr)
        return []


# ---------- normalization ----------

def normalize(s: str) -> str:
    s = s.lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # strip LaTeX commands like \emph{...} keeping content
    s = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r"[\u2018\u2019\u201c\u201d`'\"]+", "", s)
    s = re.sub(r"[.,;:!?()\[\]\\/\u2014\u2013-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------- LaTeX parsing ----------

def parse_sections(text: str) -> dict:
    section_re = re.compile(r"\\section\{\\sc\s*([^}]+?)\s*\}")
    matches = list(section_re.finditer(text))
    sections = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[name] = text[start:end]
    return sections


def split_items(body: str) -> list:
    """Split a section body into individual entries.

    If the section uses \\item markers, split on those. Otherwise split on
    blank lines (used for Book Reviews, Software, Professional Evals, Testimony).
    """
    if re.search(r"\\item\b", body):
        positions = [m.start() for m in re.finditer(r"\\item\b", body)]
        items = []
        for i, pos in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(body)
            chunk = body[pos:end]
            chunk = re.sub(r"^\\item\b\s*", "", chunk).strip()
            chunk = re.sub(r"\\end\{[^}]+\}.*$", "", chunk, flags=re.DOTALL).strip()
            if chunk:
                items.append(chunk)
        return items
    # No \item markers — split on blank lines
    clean = body.strip()
    clean = re.sub(r"\\begin\{[^}]+\}", "", clean)
    clean = re.sub(r"\\end\{[^}]+\}", "", clean)
    chunks = re.split(r"\n\s*\n", clean)
    return [c.strip() for c in chunks if c.strip() and len(c.strip()) > 20]


def extract_title(item_text: str) -> str:
    t = re.sub(r"\s+", " ", item_text)
    # Try ``...'', `...', "...", then bare \href{}{TITLE}
    patterns = [
        r"``\s*([\s\S]*?)\s*''",
        r"`\s*([\s\S]*?)\s*'",
        r'"\s*([\s\S]*?)\s*"',
    ]
    for p in patterns:
        m = re.search(p, t)
        if m:
            title = m.group(1)
            href_inner = re.search(r"\\href\{[^}]+\}\{([\s\S]*)\}", title)
            if href_inner:
                title = href_inner.group(1)
            title = re.sub(r"\\href\{[^}]+\}\{([^{}]*)\}", r"\1", title)
            title = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", title)
            title = re.sub(r"[{}]", "", title)
            title = re.sub(r"\s+", " ", title).strip()
            return title
    # Fallback: first \href{}{...} second arg
    m = re.search(r"\\href\{[^}]+\}\s*\{([\s\S]*?)\}", t)
    if m:
        title = m.group(1)
        title = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", title)
        title = re.sub(r"[{}]", "", title)
        return re.sub(r"\s+", " ", title).strip()
    return ""


def extract_year(item_text: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", item_text)
    return int(m.group(0)) if m else None


def extract_annotations(item_text: str) -> list:
    """Find ---/-- prefixed annotation lines."""
    notes = []
    parts = re.split(r"\\\\|\\newline", item_text)
    for part in parts:
        part = part.strip()
        if re.match(r"^-{2,}", part):
            note = re.sub(r"^-{2,}\s*", "", part).strip()
            if note and len(note) > 3:
                notes.append(note)
    return notes


# ---------- matching ----------

def best_match(latex_title: str) -> tuple:
    if not latex_title:
        return None, 0.0
    norm_lt = normalize(latex_title)
    candidates = bbt_search(latex_title[:120])
    if not candidates:
        words = latex_title.split()[:6]
        if words:
            candidates = bbt_search(" ".join(words))
    best = None
    best_score = 0.0
    for c in candidates:
        zt = c.get("title", "")
        score = SequenceMatcher(None, norm_lt, normalize(zt)).ratio()
        if score > best_score:
            best = c
            best_score = score
    return best, best_score


# ---------- YAML output (manual, no PyYAML dep) ----------

def yaml_str(s: str) -> str:
    if s is None:
        return "~"
    s = str(s)
    if any(c in s for c in ":#'\"\n[]{},|>&*!%@`") or s.strip() != s or not s:
        return json.dumps(s, ensure_ascii=False)
    return s


def write_yaml(proposal: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# CV → Zotero tag proposal (auto-generated)\n")
        f.write("# Review unmatched + low-score items, edit citekeys as needed,\n")
        f.write("# then run scripts/apply-tags.py to write to Zotero.\n")
        f.write(f"#\n# Generated: {len(proposal['sections'])} sections, ")
        f.write(f"{proposal['summary']['total']} entries, ")
        f.write(f"{proposal['summary']['no_match']} need review.\n\n")
        f.write("summary:\n")
        for k, v in proposal["summary"].items():
            f.write(f"  {k}: {v}\n")
        f.write("\nsections:\n")
        for tag, items in proposal["sections"].items():
            f.write(f"  {tag}:\n")
            if not items:
                f.write("    []\n")
                continue
            for it in items:
                f.write(f"    - latex_title: {yaml_str(it['latex_title'])}\n")
                f.write(f"      latex_year: {it['latex_year'] if it['latex_year'] else '~'}\n")
                f.write(f"      match_citekey: {yaml_str(it['match_citekey'])}\n")
                f.write(f"      match_zotero_title: {yaml_str(it['match_zotero_title'])}\n")
                f.write(f"      match_score: {it['match_score']}\n")
                f.write(f"      proposed_tags: {json.dumps(it['proposed_tags'])}\n")
                if it["latex_annotations"]:
                    f.write(f"      latex_annotations:\n")
                    for a in it["latex_annotations"]:
                        f.write(f"        - {yaml_str(a)}\n")
                f.write("\n")
        f.write("unmatched:\n")
        if not proposal["unmatched"]:
            f.write("  []\n")
        else:
            for u in proposal["unmatched"]:
                f.write(f"  - section: {u['section']}\n")
                f.write(f"    title: {yaml_str(u['title'])}\n")
                f.write(f"    year: {u['year'] if u['year'] else '~'}\n")
                f.write(f"    score: {u['score']}\n")


# ---------- main ----------

def main():
    if not LATEX.exists():
        print(f"Missing: {LATEX}", file=sys.stderr)
        sys.exit(1)
    text = LATEX.read_text(encoding="utf-8")
    sections = parse_sections(text)

    proposal = {
        "summary": {"total": 0, "matched_high": 0, "matched_low": 0, "no_match": 0},
        "sections": {},
        "unmatched": [],
    }

    for sec_name, tag in SECTION_TAG.items():
        body = sections.get(sec_name, "")
        if not body:
            print(f"  - {sec_name}: NOT FOUND in tex", file=sys.stderr)
            proposal["sections"][tag] = []
            continue
        items = split_items(body)
        out_items = []
        print(f"  - {sec_name} → cv:section/{tag}: {len(items)} items", file=sys.stderr)
        for raw in items:
            title = extract_title(raw)
            if not title:
                continue
            year = extract_year(raw)
            anns = extract_annotations(raw)
            match, score = best_match(title)
            score_pct = round(score * 100)
            citekey = None
            ztitle = None
            tags = []
            if match:
                citekey = match.get("citekey") or match.get("citation-key")
                ztitle = match.get("title")
            if citekey and score_pct >= int(LOW_THRESHOLD * 100):
                tags = ["cv:include", f"cv:section/{tag}"]
            entry = {
                "latex_title": title,
                "latex_year": year,
                "latex_annotations": anns,
                "match_citekey": citekey,
                "match_zotero_title": ztitle,
                "match_score": score_pct,
                "proposed_tags": tags,
            }
            out_items.append(entry)
            proposal["summary"]["total"] += 1
            if not tags:
                proposal["unmatched"].append({
                    "section": tag, "title": title, "year": year, "score": score_pct,
                })
                proposal["summary"]["no_match"] += 1
            elif score_pct >= int(HIGH_THRESHOLD * 100):
                proposal["summary"]["matched_high"] += 1
            else:
                proposal["summary"]["matched_low"] += 1
        proposal["sections"][tag] = out_items

    write_yaml(proposal, OUTPUT)
    print(file=sys.stderr)
    print(f"  Wrote {OUTPUT}", file=sys.stderr)
    s = proposal["summary"]
    print(f"  total: {s['total']}", file=sys.stderr)
    print(f"  high-confidence (>={int(HIGH_THRESHOLD*100)}): {s['matched_high']}", file=sys.stderr)
    print(f"  low-confidence ({int(LOW_THRESHOLD*100)}-{int(HIGH_THRESHOLD*100)-1}): {s['matched_low']}", file=sys.stderr)
    print(f"  unmatched (<{int(LOW_THRESHOLD*100)}): {s['no_match']}", file=sys.stderr)


if __name__ == "__main__":
    main()
