"""Shared publication loader for the dissemination pipeline.

Reads the same two sources the CV build reads and returns plain dicts:

  1. ~/Dropbox/research_projects/My Library.json — Better BibTeX CSL JSON export.
  2. _data/cv-tag-proposal.yml — the bridge file. Section membership *is* the YAML
     key under `sections:`. CSL JSON drops Zotero tags entirely, so the
     `cv:include` / `cv:section/*` filtering happens upstream in
     sync-proposal-from-zotero.py against the Zotero Web API, not here.

This deliberately duplicates ~30 lines of field extraction from build-cv.py rather
than refactoring that file: build-cv.py is 1000+ lines and generates the live CV,
and a shared-module refactor there is a far bigger change than this pipeline
warrants. If build-cv.py is ever reworked, it should adopt these functions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PROPOSAL = REPO / "_data" / "cv-tag-proposal.yml"
ZOTERO_JSON = Path.home() / "Dropbox" / "research_projects" / "My Library.json"

# Proposal section key -> human label used in generated copy.
SECTION_LABELS = {
    "peer-reviewed": "peer-reviewed article",
    "editor-reviewed": "editor-reviewed article",
    "book-review": "book review",
    "blog": "blog / popular press",
    "working-paper": "working paper",
}


# ---------- loading ----------

def load_zotero(path: Path | None = None) -> dict:
    """Index the CSL JSON export by Better BibTeX citekey."""
    path = path or ZOTERO_JSON
    items = json.loads(path.read_text(encoding="utf-8"))
    by_citekey = {}
    for item in items:
        ck = item.get("citation-key") or item.get("citekey")
        if ck:
            by_citekey[ck] = item
    return by_citekey


def load_proposal(path: Path | None = None) -> dict:
    return yaml.safe_load((path or PROPOSAL).read_text(encoding="utf-8")) or {}


# ---------- field extraction (mirrors build-cv.py) ----------

def fmt_authors(author_list, drop_last_name: str = "erlich") -> list:
    """Coauthor names with Aaron dropped. Returns a list; callers join it."""
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
    return names


def get_year(item: dict) -> str:
    parts = (item.get("issued") or {}).get("date-parts") or []
    if parts and parts[0]:
        return str(parts[0][0])
    return ""


def normalize(item: dict, citekey: str) -> dict:
    """CSL JSON entry -> the flat shape the dissemination pipeline stores."""
    doi = item.get("DOI") or ""
    # Some Zotero DOI fields hold a full https://doi.org/… URL; strip the
    # resolver prefix so we don't double it when building the href.
    doi = re.sub(r"^\s*https?://(dx\.)?doi\.org/", "", doi).strip()
    return {
        "citekey": citekey,
        "title": (item.get("title") or "").strip(),
        "venue": (item.get("container-title") or item.get("collection-title") or "").strip(),
        "year": get_year(item),
        "doi": doi,
        "url": (item.get("URL") or (f"https://doi.org/{doi}" if doi else "")).strip(),
        "coauthors": fmt_authors(item.get("author") or []),
        "abstract": (item.get("abstract") or "").strip(),
    }


# ---------- annotations (tex.cv-* / legacy LaTeX) ----------

# \href{URL}{LABEL} where LABEL may contain one level of nesting, e.g. {\textit{X}}
_HREF_RE = re.compile(r"\\href\{([^{}]*)\}\{((?:[^{}]|\{[^{}]*\})*)\}")
_TEXIT_RE = re.compile(r"\\(?:textit|emph|textbf)\{([^{}]*)\}")


def _strip_tex(s: str) -> str:
    s = _TEXIT_RE.sub(r"\1", s)
    s = s.replace("\\&", "&").replace("\\_", "_").replace("\\%", "%")
    return re.sub(r"[{}]", "", s).strip().rstrip(",").strip()


def parse_media(annotations: list) -> list:
    """Extract [{outlet, url}] from a publication's latex_annotations.

    Handles both stored forms: the raw Zotero line
    `tex.cv-media: kind | Label | URL`, and the legacy LaTeX form
    `Media coverage: \\href{URL}{\\textit{Label}}, \\href{URL2}{Label2}`.
    """
    out = []
    for ann in annotations or []:
        a = str(ann).strip()
        if a.startswith("tex.cv-media:"):
            fields = [p.strip() for p in a[len("tex.cv-media:"):].split("|")]
            if len(fields) >= 3 and fields[2]:
                out.append({"outlet": _strip_tex(fields[1]), "url": fields[2]})
            elif fields:
                out.append({"outlet": _strip_tex(fields[-1]), "url": ""})
        elif re.match(r"(?i)^media\s*coverage", a):
            for url, label in _HREF_RE.findall(a):
                out.append({"outlet": _strip_tex(label), "url": url.strip()})
    # de-dupe on url, preserving order
    seen, deduped = set(), []
    for m in out:
        key = m["url"] or m["outlet"]
        if key and key not in seen:
            seen.add(key)
            deduped.append(m)
    return deduped


def parse_awards(annotations: list) -> list:
    """Extract [{kind, text}] where kind is winner | honorable-mention | top-cited."""
    out = []
    for ann in annotations or []:
        a = str(ann).strip().rstrip(".")
        if a.startswith("tex.cv-award:"):
            rest = a[len("tex.cv-award:"):].strip()
            sub, _, value = rest.partition("|")
            sub, value = sub.strip(), _strip_tex(value.strip())
            kind = sub if sub in ("honorable-mention", "top-cited") else "winner"
            out.append({"kind": kind, "text": value or sub})
        elif re.match(r"(?i)^winner\s*[:\-]", a):
            out.append({"kind": "winner", "text": _strip_tex(a.split(":", 1)[-1])})
        elif re.match(r"(?i)^hono(?:u)?rable\s*mention\s*[:\-]", a):
            out.append({"kind": "honorable-mention", "text": _strip_tex(a.split(":", 1)[-1])})
        elif re.match(r"(?i)^top\s+\d+\s+most\s+cited", a):
            out.append({"kind": "top-cited", "text": _strip_tex(a)})
    return out


# ---------- the joined view ----------

def iter_publications(proposal: dict | None = None, zotero: dict | None = None) -> list:
    """Every publication in the proposal, joined to its Zotero record.

    Entries whose citekey is absent from the Zotero export fall back to the
    proposal's own latex_* fields (the same stub behaviour build-cv.py uses),
    and are flagged `in_zotero: False`.
    """
    proposal = proposal if proposal is not None else load_proposal()
    zotero = zotero if zotero is not None else load_zotero()

    pubs = []
    for section, entries in (proposal.get("sections") or {}).items():
        for entry in entries or []:
            citekey = entry.get("match_citekey")
            if not citekey:
                continue
            item = zotero.get(citekey)
            if item:
                rec = normalize(item, citekey)
                rec["in_zotero"] = True
            else:
                rec = {
                    "citekey": citekey,
                    "title": (entry.get("latex_title") or "").strip().rstrip("."),
                    "venue": "",
                    "year": str(entry.get("latex_year") or ""),
                    "doi": "",
                    "url": (entry.get("latex_url") or "").strip(),
                    "coauthors": [],
                    "abstract": "",
                    "in_zotero": False,
                }
            if not rec["year"]:
                rec["year"] = str(entry.get("latex_year") or "")
            if not rec["url"]:
                rec["url"] = (entry.get("latex_url") or "").strip()
            if not rec["title"]:
                rec["title"] = (entry.get("latex_title") or "").strip().rstrip(".")

            anns = entry.get("latex_annotations") or []
            rec.update({
                "section": section,
                "section_label": SECTION_LABELS.get(section, section),
                "status": (entry.get("latex_status") or "").strip(),
                "annotations": anns,
                "media": parse_media(anns),
                "awards": parse_awards(anns),
            })
            pubs.append(rec)
    return pubs


if __name__ == "__main__":  # smoke test
    pubs = iter_publications()
    print(f"{len(pubs)} publications")
    missing = [p["citekey"] for p in pubs if not p["in_zotero"]]
    print(f"{len(missing)} not in Zotero: {missing[:5]}")
    print(f"{sum(len(p['media']) for p in pubs)} media mentions, "
          f"{sum(len(p['awards']) for p in pubs)} awards")
    for p in pubs[:2]:
        print(json.dumps(p, indent=2, ensure_ascii=False)[:500])
