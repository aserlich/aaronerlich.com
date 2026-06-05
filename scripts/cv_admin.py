#!/usr/bin/env python3
"""
cv_admin.py — Local Flask web app for managing aaronerlich.com CV content.

Run:
  python3 scripts/cv_admin.py
  # then open http://localhost:5000

Features:
- Add / edit / delete entries in any cv.yml section via web forms
- Plain-text sections (in-prep, on-hold) — no Zotero needed
- Rebuild button runs build-cv.py + quarto render and shows result
- Saves directly to _data/cv.yml (preserves header comments)

Requirements:
  pip3 install --user --break-system-packages flask pyyaml
"""
from __future__ import annotations
import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

try:
    from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
except ImportError:
    sys.exit("pip3 install --user --break-system-packages flask")

try:
    import yaml
except ImportError:
    sys.exit("pip3 install --user --break-system-packages pyyaml")


REPO = Path(__file__).resolve().parents[1]
CV_PATH = REPO / "_data" / "cv.yml"
LAB_PATH = REPO / "_data" / "lab.yml"
PROPOSAL_PATH = REPO / "_data" / "cv-tag-proposal.yml"
LETTERS_PATH = REPO / "_data" / "letter-requests.yml"
BUILD_SCRIPT = REPO / "scripts" / "build-cv.py"
BUILD_LAB_SCRIPT = REPO / "scripts" / "build-lab.py"
CV_QMD = REPO / "cv.qmd"

DOCS = REPO / "docs"
PREVIEW_PORT = 8765
PREVIEW_URL = f"http://localhost:{PREVIEW_PORT}"


def preview_status():
    """Return ('ok'|'wrong'|'free', message) for the preview server on PREVIEW_PORT.

    'ok'    -> something is serving docs/cv.html (200)
    'wrong' -> port is occupied but cv.html is not found (wrong directory)
    'free'  -> nothing is listening on the port
    """
    try:
        with urllib.request.urlopen(f"{PREVIEW_URL}/cv.html", timeout=1.5) as r:
            if r.status == 200:
                return "ok", f"Preview server serving docs/ at {PREVIEW_URL}"
            return "wrong", f"Port {PREVIEW_PORT} returned HTTP {r.status} for cv.html"
    except urllib.error.HTTPError:
        # Port answers HTTP but cv.html 404s -> a server for a *different* directory.
        return "wrong", (
            f"Port {PREVIEW_PORT} is in use by a server that is NOT serving this "
            f"site's docs/ (cv.html 404s). Stop that server, then restart this admin."
        )
    except (urllib.error.URLError, OSError):
        return "free", f"Nothing listening on port {PREVIEW_PORT}"


def ensure_preview_server():
    """Start the docs/ preview server if the port is free; warn if it's misused."""
    state, msg = preview_status()
    if state == "ok":
        print(f"✓ {msg}", file=sys.stderr)
        return
    if state == "wrong":
        print(f"⚠ {msg}", file=sys.stderr)
        return
    # free -> launch our own, detached so it outlives a quick restart of this loop
    subprocess.Popen(
        [sys.executable, "-m", "http.server", "-d", str(DOCS), str(PREVIEW_PORT)],
        cwd=str(REPO),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"✓ Started preview server: {PREVIEW_URL} (serving docs/)", file=sys.stderr)

# Letters of recommendation — OneDrive folder where the archive lives.
LORS_ROOT = Path.home() / "Library" / "CloudStorage" / "OneDrive-McGillUniversity" / "LORs"
LETTER_CATEGORIES = [
    "Undergrad_LORs",
    "MA_toPHDJOB_LORs",
    "McGillPHD_LORs",
    "Colleagues_LORs",
]
LETTER_TYPES = [
    ("ma", "MA / grad school application (target: 1 page, 2 only for exceptional)"),
    ("phd", "PhD program / fellowship (length as needed)"),
    ("job_or_internship", "Job / internship (target: 1 page, never more)"),
]
LETTER_STATES = [
    "pending_upload",
    "uploaded",
    "drafting",
    "draft_ready",
    "approved",
    "sent",
    "closed",
]

ZOTERO_USER_ID = 38708
ZOTERO_API = f"https://api.zotero.org/users/{ZOTERO_USER_ID}"
ZOTERO_KEY_FILE = Path.home() / ".config" / "zotero" / "api_key"
BBT_RPC = "http://localhost:23119/better-bibtex/json-rpc"

PUB_SECTIONS = [
    "peer-reviewed", "editor-reviewed", "book-review",
    "blog", "working-paper",
]

ANNOTATION_TYPES = [
    ("award_winner",            "Award — Winner"),
    ("award_honorable_mention", "Award — Honourable Mention"),
    ("award_top_cited",         "Award — Top Cited"),
    ("media_news",              "Media — News"),
    ("media_blog",              "Media — Blog"),
    ("media_magazine",          "Media — Magazine"),
    ("media_podcast",           "Media — Podcast"),
    ("media_press_release",     "Media — Press Release"),
]


def _zotero_api_key():
    if not ZOTERO_KEY_FILE.exists():
        return None
    return ZOTERO_KEY_FILE.read_text().strip()


def _bbt_search(query: str):
    import json as _j, urllib.request as _r
    body = _j.dumps({"jsonrpc": "2.0", "method": "item.search", "params": [query], "id": 1}).encode()
    req = _r.Request(BBT_RPC, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _r.urlopen(req, timeout=10) as resp:
            return _j.load(resp).get("result", []) or []
    except Exception:
        return []


def _citekey_to_itemkey(citekey: str):
    import re as _re
    for r in _bbt_search(citekey):
        ck = r.get("citekey") or r.get("citation-key")
        if ck == citekey:
            m = _re.search(r"/items/([A-Z0-9]+)$", r.get("id", ""))
            if m:
                return m.group(1)
    return None


def _zotero_get(item_key: str, api_key: str):
    import json as _j, urllib.request as _r
    req = _r.Request(f"{ZOTERO_API}/items/{item_key}", headers={"Zotero-API-Key": api_key})
    with _r.urlopen(req, timeout=15) as resp:
        return _j.load(resp)


def _zotero_patch(item_key: str, version: int, body: dict, api_key: str):
    import json as _j, urllib.request as _r
    req = _r.Request(
        f"{ZOTERO_API}/items/{item_key}",
        data=_j.dumps(body).encode("utf-8"),
        headers={
            "Zotero-API-Key": api_key,
            "Content-Type": "application/json",
            "If-Unmodified-Since-Version": str(version),
        },
        method="PATCH",
    )
    try:
        with _r.urlopen(req, timeout=15) as resp:
            return resp.status, ""
    except Exception as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return getattr(e, "code", 0), body_text


def _normalize_name(name: str) -> str:
    return (name or "").strip().lower()


def _degree_to_mentorship_group(degree: str) -> str | None:
    """Map a free-text degree string to a mentorship subsection."""
    d = (degree or "").lower()
    if "ph" in d or "phd" in d:
        return "phd"
    if "m.a" in d or "ma" in d or "master" in d:
        return "ma"
    if "b.a" in d or "ba" in d or "undergrad" in d:
        return "undergraduate"
    return None


def sync_placement_across_files(name: str, placement: str):
    """If a student exists in both lab.yml alumni AND cv.yml mentorship,
    keep the placement field aligned. ONLY syncs the placement; other fields
    are independent in each file."""
    if not name or not placement:
        return None
    n_norm = _normalize_name(name)
    placement = placement.strip()

    # --- update cv.yml mentorship ---
    cv_header, cv = load_yaml_with_header(CV_PATH)
    cv_changed = False
    for group in ("phd", "ma", "undergraduate"):
        for m in (cv.get("mentorship") or {}).get(group, []) or []:
            if _normalize_name(m.get("name", "")) == n_norm:
                if m.get("placement") != placement:
                    m["placement"] = placement
                    cv_changed = True
    if cv_changed:
        dump_yaml_with_header(CV_PATH, cv_header, cv)

    # --- update lab.yml alumni ---
    lab_header, lab = load_yaml_with_header(LAB_PATH)
    lab_changed = False
    for a in lab.get("alumni", []) or []:
        if _normalize_name(a.get("name", "")) == n_norm:
            if a.get("post_mcgill") != placement:
                a["post_mcgill"] = placement
                lab_changed = True
    if lab_changed:
        dump_yaml_with_header(LAB_PATH, lab_header, lab)

    return {"cv_updated": cv_changed, "lab_updated": lab_changed}


def backfill_all_placements() -> dict:
    """One-time pass: for every student that appears in BOTH files, align their
    placement so both files agree. Lab.yml wins when both have a value (since
    lab.yml is the more user-facing source); otherwise the non-empty value
    propagates to the empty side."""
    cv_header, cv = load_yaml_with_header(CV_PATH)
    lab_header, lab = load_yaml_with_header(LAB_PATH)

    # Build name → placement maps from each file
    cv_map = {}  # normalized_name → (group, idx, placement)
    for group in ("phd", "ma", "undergraduate"):
        for i, m in enumerate((cv.get("mentorship") or {}).get(group, []) or []):
            n = _normalize_name(m.get("name", ""))
            if n:
                cv_map.setdefault(n, []).append((group, i, m.get("placement", "")))

    lab_map = {}  # normalized_name → (idx, post_mcgill)
    for i, a in enumerate(lab.get("alumni", []) or []):
        n = _normalize_name(a.get("name", ""))
        if n:
            lab_map[n] = (i, a.get("post_mcgill", ""))

    aligned = []
    cv_changed = False
    lab_changed = False
    for n_norm, lab_entry in lab_map.items():
        if n_norm not in cv_map:
            continue
        lab_idx, lab_pl = lab_entry
        cv_entries = cv_map[n_norm]

        # Decide canonical placement: lab wins if non-empty, else cv
        canonical = (lab_pl or "").strip()
        if not canonical:
            for _g, _i, p in cv_entries:
                if (p or "").strip():
                    canonical = p.strip()
                    break
        if not canonical:
            continue

        # Apply to lab
        if (lab["alumni"][lab_idx].get("post_mcgill") or "").strip() != canonical:
            lab["alumni"][lab_idx]["post_mcgill"] = canonical
            lab_changed = True
        # Apply to all matching cv entries
        for group, idx, _p in cv_entries:
            if (cv["mentorship"][group][idx].get("placement") or "").strip() != canonical:
                cv["mentorship"][group][idx]["placement"] = canonical
                cv_changed = True

        aligned.append((lab["alumni"][lab_idx].get("name", n_norm), canonical))

    if cv_changed:
        dump_yaml_with_header(CV_PATH, cv_header, cv)
    if lab_changed:
        dump_yaml_with_header(LAB_PATH, lab_header, lab)

    return {"aligned": aligned, "cv_changed": cv_changed, "lab_changed": lab_changed}


def _annotation_to_extra_line(ann_type: str, value: str, label: str = "", url: str = "") -> str | None:
    """Build a tex.cv-* line from form fields."""
    if ann_type == "award_winner":
        return f"tex.cv-award: winner | {value}"
    if ann_type == "award_honorable_mention":
        return f"tex.cv-award: honorable-mention | {value}"
    if ann_type == "award_top_cited":
        return f"tex.cv-award: top-cited | {value}"
    if ann_type.startswith("media_"):
        kind = ann_type.split("_", 1)[1].replace("_", "-")
        if kind == "press-release":
            if url:
                return f"tex.cv-press-release: {url}"
            return None
        if label and url:
            return f"tex.cv-media: {kind} | {label} | {url}"
        return None
    return None

# ---------- YAML I/O preserving header comments ----------

def load_yaml_with_header(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header, i = [], 0
    while i < len(lines) and (lines[i].lstrip().startswith("#") or lines[i].strip() == ""):
        header.append(lines[i])
        i += 1
    header_text = ("\n".join(header).rstrip() + "\n\n") if header else ""
    return header_text, yaml.safe_load("\n".join(lines[i:]))


def dump_yaml_with_header(path: Path, header_text: str, data: dict):
    # When saving cv.yml, auto-bump the English last_updated timestamp.
    # Other-language values are left alone (regenerate via translate-cv.py if needed).
    if path.name == "cv.yml" and isinstance(data, dict):
        from datetime import date
        today = date.today().strftime("%B %-d, %Y")  # e.g., "April 10, 2026"
        meta = data.setdefault("meta", {})
        last = meta.setdefault("last_updated", {})
        if isinstance(last, dict):
            last["en"] = f"Last updated {today}"
    with open(path, "w", encoding="utf-8") as f:
        if header_text:
            f.write(header_text)
        yaml.safe_dump(
            data, f, allow_unicode=True, sort_keys=False, width=120, default_flow_style=False
        )


# ---------- section definitions ----------
# Each section maps to a sub-tree in cv.yml. Field types:
#   text       — single-line input
#   textarea   — multi-line
#   number     — int input
#   checkbox   — bool
#   list       — comma-separated values, stored as a list
#   ml         — multilingual: stored as {en, fr, ...} but only EN edited here
# `path` is a dot-list path into cv.yml. `nested` describes sub-sections.

SECTIONS = {
    "under_review": {
        "label": "Under Review / R&R",
        "path": ["under_review"],
        "fields": [
            {"name": "title", "label": "Title", "type": "text", "required": True},
            {"name": "year", "label": "Year (optional)", "type": "number"},
            {"name": "url", "label": "URL (optional — only adds a link if set)", "type": "text"},
            {"name": "status", "label": "Status (e.g., 'R&R at CPS', 'Under Review')", "type": "text"},
            {"name": "coauthors", "label": "Coauthors (comma-separated)", "type": "list"},
        ],
        "summary": lambda e: e.get("title", "?")[:80],
    },
    "in_prep": {
        "label": "Manuscripts in Preparation",
        "path": ["in_prep"],
        "fields": [
            {"name": "title", "label": "Title", "type": "text", "required": True},
            {"name": "year", "label": "Year (optional)", "type": "number"},
            {"name": "url", "label": "URL (optional)", "type": "text"},
            {"name": "coauthors", "label": "Coauthors (comma-separated)", "type": "list"},
        ],
        "summary": lambda e: e.get("title", "?")[:80],
    },
    "on_hold": {
        "label": "On Hold",
        "path": ["on_hold"],
        "fields": [
            {"name": "title", "label": "Title", "type": "text", "required": True},
            {"name": "year", "label": "Year (optional)", "type": "number"},
            {"name": "coauthors", "label": "Coauthors (comma-separated)", "type": "list"},
        ],
        "summary": lambda e: e.get("title", "?")[:80],
    },
    "presentations": {
        "label": "Recent Presentations",
        "path": ["presentations"],
        "fields": [
            {"name": "title", "label": "Title", "type": "text", "required": True},
            {"name": "venue", "label": "Venue", "type": "text"},
            {"name": "date", "label": "Date", "type": "text"},
            {"name": "invited", "label": "Invited talk?", "type": "checkbox"},
        ],
        "summary": lambda e: f"{e.get('title','?')[:60]} ({e.get('date','?')})",
    },
    "phd_mentees": {
        "label": "Ph.D. Mentees",
        "path": ["mentorship", "phd"],
        "fields": [
            {"name": "year", "label": "Graduation Year", "type": "text", "required": True},
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "roles", "label": "Roles", "type": "text"},
            {"name": "placement", "label": "Placement", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('name','?')} ({e.get('year','?')})",
    },
    "ma_mentees": {
        "label": "M.A. Mentees",
        "path": ["mentorship", "ma"],
        "fields": [
            {"name": "year", "label": "Graduation Year", "type": "text", "required": True},
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "roles", "label": "Roles", "type": "text"},
            {"name": "placement", "label": "Placement (optional)", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('name','?')} ({e.get('year','?')})",
    },
    "undergrad_mentees": {
        "label": "Undergraduate Mentees",
        "path": ["mentorship", "undergraduate"],
        "fields": [
            {"name": "year", "label": "Year", "type": "text", "required": True},
            {"name": "name", "label": "Name", "type": "text", "required": True},
            {"name": "roles", "label": "Roles", "type": "text"},
            # No placement field for undergrads
        ],
        "summary": lambda e: f"{e.get('name','?')} ({e.get('year','?')})",
    },
    "grants": {
        "label": "Grants & Scholarships",
        "path": ["grants"],
        "fields": [
            {"name": "year", "label": "Year", "type": "text", "required": True},
            {"name": "title.en", "label": "Title (English)", "type": "text", "required": True},
            {"name": "agency", "label": "Agency", "type": "text"},
            {"name": "role.en", "label": "Role (English, optional)", "type": "text"},
            {"name": "amount", "label": "Amount (e.g., 'CAD 70,413')", "type": "text"},
            {"name": "notes.en", "label": "Notes (English, optional)", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('year','?')} — {(e.get('title') or {}).get('en','?')[:60]}",
    },
    "field_research": {
        "label": "Field Research",
        "path": ["field_research"],
        "fields": [
            {"name": "place", "label": "Place", "type": "text", "required": True},
            {"name": "years", "label": "Years", "type": "text", "required": True},
        ],
        "summary": lambda e: f"{e.get('place','?')} ({e.get('years','?')})",
    },
    "instructor_undergrad": {
        "label": "Courses (Instructor, Undergraduate)",
        "path": ["teaching", "instructor", "undergraduate"],
        "fields": [
            {"name": "course", "label": "Course Name", "type": "text", "required": True},
            {"name": "code", "label": "Course Code", "type": "text"},
            {"name": "institution", "label": "Institution", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('course','?')[:50]} [{e.get('code','?')}]",
    },
    "instructor_grad": {
        "label": "Courses (Instructor, Graduate)",
        "path": ["teaching", "instructor", "graduate"],
        "fields": [
            {"name": "course", "label": "Course Name", "type": "text", "required": True},
            {"name": "code", "label": "Course Code", "type": "text"},
            {"name": "institution", "label": "Institution", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('course','?')[:50]} [{e.get('code','?')}]",
    },
    "professional_evaluations": {
        "label": "Professional Evaluations",
        "path": ["professional_evaluations"],
        "fields": [
            {"name": "title.en", "label": "Title (English)", "type": "text", "required": True},
            {"name": "coauthors", "label": "Coauthors (comma-separated)", "type": "list"},
            {"name": "submitted_to.en", "label": "Submitted to (English)", "type": "text"},
            {"name": "year", "label": "Year", "type": "text"},
        ],
        "summary": lambda e: (e.get("title") or {}).get("en", "?")[:70],
    },
    "testimony": {
        "label": "Testimony",
        "path": ["testimony"],
        "fields": [
            {"name": "title.en", "label": "Title (English)", "type": "text", "required": True},
            {"name": "venue.en", "label": "Venue (English)", "type": "text"},
            {"name": "date", "label": "Date", "type": "text"},
            {"name": "url", "label": "URL", "type": "text"},
        ],
        "summary": lambda e: (e.get("title") or {}).get("en", "?")[:70],
    },
    "affiliations": {
        "label": "Affiliations",
        "path": ["affiliations"],
        "fields": [
            {"name": "role.en", "label": "Role (English)", "type": "text", "required": True},
            {"name": "org", "label": "Organization", "type": "text", "required": True},
            {"name": "url", "label": "URL", "type": "text"},
            {"name": "dates", "label": "Dates", "type": "text"},
        ],
        "summary": lambda e: f"{e.get('org','?')[:50]} ({e.get('dates','?')})",
    },
    # ----- string-list sections (peer review, grant review, etc.) -----
    "journal_review": {
        "label": "Journal Peer Review",
        "path": ["professional_service", "journal_review"],
        "stringlist": True,
        "summary": lambda e: e if isinstance(e, str) else "?",
    },
    "grant_review": {
        "label": "Grant Review",
        "path": ["professional_service", "grant_review"],
        "stringlist": True,
        "summary": lambda e: e if isinstance(e, str) else "?",
    },
    "government_review": {
        "label": "Government Agency Review",
        "path": ["professional_service", "government_review"],
        "stringlist": True,
        "summary": lambda e: e if isinstance(e, str) else "?",
    },
    # ----- structured service entries -----
    "service_departmental": {
        "label": "Departmental Service",
        "path": ["professional_service", "departmental"],
        "fields": [
            {"name": "year", "label": "Year (e.g., '2025-26')", "type": "text", "required": True},
            {"name": "roles", "label": "Roles (comma-separated)", "type": "list", "required": True},
        ],
        "summary": lambda e: f"{e.get('year','?')}: {(e.get('roles') or [''])[0][:60]}",
    },
    "service_university": {
        "label": "University Service",
        "path": ["professional_service", "university", "entries"],
        "fields": [
            {"name": "year", "label": "Year", "type": "text", "required": True},
            {"name": "roles", "label": "Roles (comma-separated)", "type": "list", "required": True},
        ],
        "summary": lambda e: f"{e.get('year','?')}: {(e.get('roles') or [''])[0][:60]}",
    },
    "service_profession": {
        "label": "Profession Service",
        "path": ["professional_service", "profession"],
        "fields": [
            {"name": "year", "label": "Year", "type": "text", "required": True},
            {"name": "roles", "label": "Roles (comma-separated)", "type": "list", "required": True},
        ],
        "summary": lambda e: f"{e.get('year','?')}: {(e.get('roles') or [''])[0][:60]}",
    },
}


# ---------- helpers for nested key access ----------

def get_at_path(data, path):
    cur = data
    for p in path:
        if cur is None:
            return None
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def ensure_at_path(data, path):
    cur = data
    for p in path[:-1]:
        if p not in cur or cur[p] is None:
            cur[p] = {}
        cur = cur[p]
    if path[-1] not in cur or cur[path[-1]] is None:
        cur[path[-1]] = []
    return cur[path[-1]]


def parse_form_value(field, raw_value):
    """Convert form input to the right type."""
    if field["type"] == "checkbox":
        return raw_value == "on" or raw_value is True
    if field["type"] == "number":
        try:
            return int(raw_value) if raw_value else None
        except ValueError:
            return None
    if field["type"] == "list":
        if not raw_value:
            return []
        return [s.strip() for s in raw_value.split(",") if s.strip()]
    return raw_value if raw_value else None


def set_nested(entry, dotted_name, value):
    """Set entry[a][b] given dotted name 'a.b'."""
    parts = dotted_name.split(".")
    cur = entry
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def get_nested(entry, dotted_name):
    parts = dotted_name.split(".")
    cur = entry
    for p in parts:
        if cur is None:
            return None
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur


def build_entry_from_form(form, fields):
    entry = {}
    for f in fields:
        raw = form.get(f["name"])
        value = parse_form_value(f, raw)
        if value is None or value == "" or value == []:
            continue
        set_nested(entry, f["name"], value)
    return entry


# ---------- Flask app ----------

app = Flask(__name__)
app.secret_key = "cv-admin-local"


PAGE_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{{ title }} — CV Admin</title>
<style>
body { font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #222; background: #fafafa; }
h1 { border-bottom: 2px solid #6b1b1b; padding-bottom: 0.3em; color: #6b1b1b; }
h2 { color: #6b1b1b; margin-top: 2em; }
nav a { display: inline-block; margin: 0 0.6em 0.4em 0; padding: 0.3em 0.6em; background: #fff; border: 1px solid #ccc; border-radius: 3px; text-decoration: none; color: #333; font-size: 0.85em; }
nav a:hover { background: #6b1b1b; color: #fff; }
table { width: 100%; border-collapse: collapse; background: #fff; margin: 1em 0; }
th, td { padding: 0.5em 0.7em; border-bottom: 1px solid #eee; text-align: left; vertical-align: top; font-size: 0.9em; }
th { background: #f0f0f0; font-weight: 700; }
.actions a { margin-right: 0.5em; }
.actions a.del { color: #c00; }
form { background: #fff; padding: 1em; border: 1px solid #ddd; border-radius: 4px; margin: 1em 0; }
form label { display: block; margin: 0.6em 0 0.2em; font-weight: 700; font-size: 0.85em; }
form input[type=text], form input[type=number], form textarea {
  width: 100%; padding: 0.4em; border: 1px solid #bbb; border-radius: 3px;
  font-family: inherit; font-size: 0.9em; box-sizing: border-box;
}
form button {
  background: #6b1b1b; color: #fff; border: 0; padding: 0.5em 1.2em;
  border-radius: 3px; cursor: pointer; font-family: inherit; font-size: 0.9em; margin-top: 0.6em;
}
form button:hover { background: #8a2828; }
.flash { background: #efe; border-left: 4px solid #4a4; padding: 0.5em 1em; margin: 1em 0; }
.flash.error { background: #fee; border-color: #c44; }
.rebuild-btn { background: #2a6; color: #fff; padding: 0.5em 1em; border: 0; border-radius: 3px; cursor: pointer; }
.rebuild-btn:hover { background: #3b7; }
.rebuild-output { background: #111; color: #0f0; padding: 1em; border-radius: 4px; font-size: 0.8em; white-space: pre-wrap; max-height: 300px; overflow: auto; }
small { color: #777; }
</style>
</head><body>
<h1>{{ title }}</h1>
<nav>
<a href="{{ url_for('index') }}">Home</a>
{% for key, sec in sections.items() %}
<a href="{{ url_for('section_view', section=key) }}">{{ sec.label }}</a>
{% endfor %}
<a href="{{ url_for('publications_list') }}">Publications (Zotero)</a>
<a href="{{ url_for('lab_view') }}">Lab</a>
<a href="{{ url_for('letters_view') }}">Letters</a>
<a href="{{ url_for('rebuild') }}" style="background:#2a6;color:#fff">Rebuild &amp; Preview</a>
</nav>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for cat, msg in messages %}
    <div class="flash {{ cat }}">{{ msg }}</div>
  {% endfor %}
{% endwith %}
"""

PAGE_FOOT = """</body></html>"""


@app.route("/")
def index():
    return render_template_string(
        PAGE_HEAD + """
<p>Pick a section from the nav above. The "Rebuild &amp; Preview" button regenerates <code>cv.qmd</code> and runs <code>quarto render cv.qmd</code>.</p>
<h2>Currently editable sections</h2>
<ul>
{% for key, sec in sections.items() %}
  <li><a href="{{ url_for('section_view', section=key) }}">{{ sec.label }}</a> ({{ counts[key] }} entries)</li>
{% endfor %}
</ul>
<p><small>cv.yml: <code>{{ cv_path }}</code></small></p>
""" + PAGE_FOOT,
        title="CV Admin", sections=SECTIONS, counts=_section_counts(), cv_path=CV_PATH
    )


def _section_counts():
    _, data = load_yaml_with_header(CV_PATH)
    return {k: len(get_at_path(data, s["path"]) or []) for k, s in SECTIONS.items()}


@app.route("/section/<section>")
def section_view(section):
    if section not in SECTIONS:
        flash(f"Unknown section: {section}", "error")
        return redirect(url_for("index"))
    sec = SECTIONS[section]
    _, data = load_yaml_with_header(CV_PATH)
    entries = get_at_path(data, sec["path"]) or []
    is_stringlist = sec.get("stringlist", False)
    return render_template_string(
        PAGE_HEAD + """
<h2>{{ sec.label }} <small>({{ entries|length }} entries)</small></h2>
{% if entries %}
<table>
<thead><tr><th>#</th><th>Entry</th><th>Actions</th></tr></thead>
<tbody>
{% for e in entries %}
<tr>
  <td>{{ loop.index }}</td>
  <td>{{ summary(e) }}</td>
  <td class="actions">
    {% if not is_stringlist %}
    <a href="{{ url_for('section_edit', section=section, idx=loop.index0) }}">edit</a>
    {% endif %}
    {% if section == 'under_review' %}
    <a href="{{ url_for('publish_under_review', idx=loop.index0) }}" style="color:#2a6">publish</a>
    {% endif %}
    <a class="del" href="{{ url_for('section_delete', section=section, idx=loop.index0) }}" onclick="return confirm('Delete this entry?')">delete</a>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p><em>No entries yet.</em></p>
{% endif %}

<h2>Add new</h2>
<form method="post" action="{{ url_for('section_add', section=section) }}">
{% if is_stringlist %}
  <label>Value *</label>
  <input type="text" name="value" required>
{% else %}
  {% for f in sec.fields %}
    <label>{{ f.label }}{% if f.required %} *{% endif %}</label>
    {% if f.type == 'checkbox' %}
      <input type="checkbox" name="{{ f.name }}">
    {% elif f.type == 'number' %}
      <input type="number" name="{{ f.name }}">
    {% else %}
      <input type="text" name="{{ f.name }}" {% if f.required %}required{% endif %}>
    {% endif %}
  {% endfor %}
{% endif %}
<button type="submit">Add</button>
</form>
""" + PAGE_FOOT,
        title=sec["label"], sections=SECTIONS, sec=sec, section=section,
        entries=entries, summary=sec["summary"], is_stringlist=is_stringlist,
    )


@app.route("/section/<section>/add", methods=["POST"])
def section_add(section):
    if section not in SECTIONS:
        flash("Unknown section", "error")
        return redirect(url_for("index"))
    sec = SECTIONS[section]
    header, data = load_yaml_with_header(CV_PATH)
    target = ensure_at_path(data, sec["path"])
    if sec.get("stringlist"):
        value = (request.form.get("value") or "").strip()
        if not value:
            flash("Empty value", "error")
            return redirect(url_for("section_view", section=section))
        target.append(value)
    else:
        entry = build_entry_from_form(request.form, sec.get("fields") or [])
        if not entry:
            flash("Empty entry — nothing added", "error")
            return redirect(url_for("section_view", section=section))
        target.append(entry)
    dump_yaml_with_header(CV_PATH, header, data)
    flash(f"Added to {sec['label']}", "")
    return redirect(url_for("section_view", section=section))


@app.route("/section/<section>/edit/<int:idx>", methods=["GET", "POST"])
def section_edit(section, idx):
    if section not in SECTIONS:
        flash("Unknown section", "error")
        return redirect(url_for("index"))
    sec = SECTIONS[section]
    header, data = load_yaml_with_header(CV_PATH)
    entries = get_at_path(data, sec["path"]) or []
    if idx >= len(entries):
        flash("Index out of range", "error")
        return redirect(url_for("section_view", section=section))

    if request.method == "POST":
        entry = build_entry_from_form(request.form, sec["fields"])
        entries[idx] = entry
        dump_yaml_with_header(CV_PATH, header, data)

        # If this is a mentorship entry, sync placement to lab.yml alumni
        sync_msg = ""
        if section in ("phd_mentees", "ma_mentees", "undergrad_mentees"):
            result = sync_placement_across_files(entry.get("name", ""), entry.get("placement", ""))
            if result and result.get("lab_updated"):
                sync_msg = " (also synced placement to lab.yml alumni)"
        flash(f"Saved{sync_msg}", "")
        return redirect(url_for("section_view", section=section))

    entry = entries[idx]
    return render_template_string(
        PAGE_HEAD + """
<h2>Edit: {{ sec.label }} #{{ idx + 1 }}</h2>
<form method="post">
{% for f in sec.fields %}
  <label>{{ f.label }}{% if f.required %} *{% endif %}</label>
  {% set existing = get_nested(entry, f.name) %}
  {% if f.type == 'checkbox' %}
    <input type="checkbox" name="{{ f.name }}" {% if existing %}checked{% endif %}>
  {% elif f.type == 'number' %}
    <input type="number" name="{{ f.name }}" value="{{ existing or '' }}">
  {% elif f.type == 'list' %}
    <input type="text" name="{{ f.name }}" value="{{ existing|join(', ') if existing else '' }}">
  {% else %}
    <input type="text" name="{{ f.name }}" value="{{ existing or '' }}" {% if f.required %}required{% endif %}>
  {% endif %}
{% endfor %}
<button type="submit">Save</button>
<a href="{{ url_for('section_view', section=section) }}" style="margin-left:1em">Cancel</a>
</form>
""" + PAGE_FOOT,
        title="Edit", sections=SECTIONS, sec=sec, section=section,
        idx=idx, entry=entry, get_nested=get_nested,
    )


@app.route("/lab")
def lab_view():
    """Lab member management — current grad, current undergrad, alumni."""
    header, lab = load_yaml_with_header(LAB_PATH)
    return render_template_string(
        PAGE_HEAD + """
<h2>Lab — Current Members</h2>

<h3>Graduate Researchers ({{ (lab.current_grad or [])|length }})</h3>
{% if lab.current_grad %}
<table>
<thead><tr><th>Name</th><th>Degree</th><th>Actions</th></tr></thead>
<tbody>
{% for m in lab.current_grad %}
<tr>
  <td><strong>{{ m.name }}</strong></td>
  <td>{{ m.degree or '' }}</td>
  <td class="actions">
    <a href="{{ url_for('lab_edit', group='current_grad', idx=loop.index0) }}">edit</a>
    <a href="{{ url_for('lab_promote', group='current_grad', idx=loop.index0) }}" style="color:#2a6">promote to alumni</a>
    <a class="del" href="{{ url_for('lab_delete', group='current_grad', idx=loop.index0) }}" onclick="return confirm('Delete?')">delete</a>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
<form method="post" action="{{ url_for('lab_add', group='current_grad') }}" style="margin-bottom:2em">
  <label>Name *</label><input type="text" name="name" required>
  <label>Degree (e.g., "PhD candidate", "MA student")</label><input type="text" name="degree">
  <label>Headshot path (e.g., images/headshot-foo.jpg)</label><input type="text" name="headshot">
  <label>Bio (without name prefix — start with "is a..." )</label><textarea name="bio" rows="4"></textarea>
  <button type="submit">Add grad researcher</button>
</form>

<h3>Undergraduate Researchers ({{ (lab.current_undergrad or [])|length }})</h3>
{% if lab.current_undergrad %}
<table>
<thead><tr><th>Name</th><th>Degree</th><th>Actions</th></tr></thead>
<tbody>
{% for m in lab.current_undergrad %}
<tr>
  <td><strong>{{ m.name }}</strong></td>
  <td>{{ m.degree or '' }}</td>
  <td class="actions">
    <a href="{{ url_for('lab_edit', group='current_undergrad', idx=loop.index0) }}">edit</a>
    <a href="{{ url_for('lab_promote', group='current_undergrad', idx=loop.index0) }}" style="color:#2a6">promote to alumni</a>
    <a class="del" href="{{ url_for('lab_delete', group='current_undergrad', idx=loop.index0) }}" onclick="return confirm('Delete?')">delete</a>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
<form method="post" action="{{ url_for('lab_add', group='current_undergrad') }}" style="margin-bottom:2em">
  <label>Name *</label><input type="text" name="name" required>
  <label>Degree</label><input type="text" name="degree">
  <label>Headshot path</label><input type="text" name="headshot">
  <label>Bio</label><textarea name="bio" rows="4"></textarea>
  <button type="submit">Add undergrad researcher</button>
</form>

<h2>DemoTIP Alumni ({{ (lab.alumni or [])|length }})</h2>
{% if lab.alumni %}
<table>
<thead><tr><th>Name</th><th>Degree</th><th>Year</th><th>Post-McGill</th><th>Actions</th></tr></thead>
<tbody>
{% for a in lab.alumni %}
<tr>
  <td><strong>{{ a.name }}</strong></td>
  <td>{{ a.degree or '' }}</td>
  <td>{{ a.graduation_year or '' }}</td>
  <td>{{ (a.post_mcgill or '')[:50] }}</td>
  <td class="actions">
    <a href="{{ url_for('lab_edit', group='alumni', idx=loop.index0) }}">edit</a>
    <a class="del" href="{{ url_for('lab_delete', group='alumni', idx=loop.index0) }}" onclick="return confirm('Delete?')">delete</a>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
""" + PAGE_FOOT,
        title="Lab", sections=SECTIONS, lab=lab,
    )


@app.route("/lab/<group>/add", methods=["POST"])
def lab_add(group):
    if group not in ("current_grad", "current_undergrad", "alumni"):
        return redirect(url_for("lab_view"))
    header, lab = load_yaml_with_header(LAB_PATH)
    entry = {
        "name": (request.form.get("name") or "").strip(),
        "degree": (request.form.get("degree") or "").strip(),
        "headshot": (request.form.get("headshot") or "").strip(),
        "bio": (request.form.get("bio") or "").strip(),
    }
    if not entry["name"]:
        flash("Name required", "error")
        return redirect(url_for("lab_view"))
    lab.setdefault(group, []).append(entry)
    dump_yaml_with_header(LAB_PATH, header, lab)
    flash(f"Added {entry['name']} to {group}", "")
    return redirect(url_for("lab_view"))


@app.route("/lab/<group>/edit/<int:idx>", methods=["GET", "POST"])
def lab_edit(group, idx):
    header, lab = load_yaml_with_header(LAB_PATH)
    members = lab.get(group, []) or []
    if idx >= len(members):
        flash("Index out of range", "error")
        return redirect(url_for("lab_view"))
    m = members[idx]
    if request.method == "POST":
        m["name"] = (request.form.get("name") or "").strip()
        if group == "alumni":
            m["degree"] = (request.form.get("degree") or "").strip()
            m["graduation_year"] = (request.form.get("graduation_year") or "").strip() or None
            m["publications"] = (request.form.get("publications") or "").strip()
            m["post_mcgill"] = (request.form.get("post_mcgill") or "").strip()
        else:
            m["degree"] = (request.form.get("degree") or "").strip()
            m["headshot"] = (request.form.get("headshot") or "").strip()
            m["bio"] = (request.form.get("bio") or "").strip()
        dump_yaml_with_header(LAB_PATH, header, lab)

        # If editing an alumnus, sync placement back to mentorship in cv.yml
        sync_msg = ""
        if group == "alumni":
            result = sync_placement_across_files(m["name"], m.get("post_mcgill", ""))
            if result and result.get("cv_updated"):
                sync_msg = " (also synced placement to cv.yml mentorship)"
        flash(f"Saved{sync_msg}", "")
        return redirect(url_for("lab_view"))

    if group == "alumni":
        form = """
<form method="post">
  <label>Name *</label><input type="text" name="name" value="{{ m.name }}" required>
  <label>Degree (Ph.D. / M.A. / B.A.)</label><input type="text" name="degree" value="{{ m.degree or '' }}">
  <label>Graduation Year</label><input type="text" name="graduation_year" value="{{ m.graduation_year or '' }}">
  <label>Publications & Research (markdown)</label><textarea name="publications" rows="3">{{ m.publications or '' }}</textarea>
  <label>Post-McGill placement (markdown)</label><textarea name="post_mcgill" rows="2">{{ m.post_mcgill or '' }}</textarea>
  <button type="submit">Save</button>
  <a href="{{ url_for('lab_view') }}" style="margin-left:1em">Cancel</a>
</form>"""
    else:
        form = """
<form method="post">
  <label>Name *</label><input type="text" name="name" value="{{ m.name }}" required>
  <label>Degree</label><input type="text" name="degree" value="{{ m.degree or '' }}">
  <label>Headshot path</label><input type="text" name="headshot" value="{{ m.headshot or '' }}">
  <label>Bio</label><textarea name="bio" rows="6">{{ m.bio or '' }}</textarea>
  <button type="submit">Save</button>
  <a href="{{ url_for('lab_view') }}" style="margin-left:1em">Cancel</a>
</form>"""
    return render_template_string(
        PAGE_HEAD + f"<h2>Edit: {{{{ m.name }}}}</h2>{form}" + PAGE_FOOT,
        title="Edit lab member", sections=SECTIONS, m=m, group=group,
    )


@app.route("/lab/<group>/delete/<int:idx>")
def lab_delete(group, idx):
    header, lab = load_yaml_with_header(LAB_PATH)
    members = lab.get(group, []) or []
    if idx < len(members):
        removed = members.pop(idx)
        dump_yaml_with_header(LAB_PATH, header, lab)
        flash(f"Deleted {removed.get('name','?')}", "")
    return redirect(url_for("lab_view"))


@app.route("/lab/<group>/promote/<int:idx>", methods=["GET", "POST"])
def lab_promote(group, idx):
    """Move a current member to alumni with updated info."""
    if group not in ("current_grad", "current_undergrad"):
        return redirect(url_for("lab_view"))
    header, lab = load_yaml_with_header(LAB_PATH)
    members = lab.get(group, []) or []
    if idx >= len(members):
        return redirect(url_for("lab_view"))
    m = members[idx]

    if request.method == "POST":
        alum = {
            "name": m["name"],
            "degree": (request.form.get("degree") or "").strip(),
            "graduation_year": (request.form.get("graduation_year") or "").strip() or None,
            "publications": (request.form.get("publications") or "").strip(),
            "post_mcgill": (request.form.get("post_mcgill") or "").strip(),
        }
        lab.setdefault("alumni", []).insert(0, alum)
        members.pop(idx)
        dump_yaml_with_header(LAB_PATH, header, lab)

        # Also sync the placement to mentorship in cv.yml (if a matching name exists)
        result = sync_placement_across_files(alum["name"], alum.get("post_mcgill", ""))
        sync_msg = ""
        if result and result.get("cv_updated"):
            sync_msg = " (also updated cv.yml mentorship placement)"
        flash(f"Promoted {alum['name']} to alumni{sync_msg}", "")
        return redirect(url_for("lab_view"))

    # Pre-fill degree from the current degree string
    suggested_degree = "Ph.D." if "PhD" in (m.get("degree") or "") else (
        "M.A." if "MA" in (m.get("degree") or "") else "B.A.")

    return render_template_string(
        PAGE_HEAD + """
<h2>Promote to alumni: {{ m.name }}</h2>
<p>Current bio: <em>{{ m.bio[:200] }}...</em></p>
<form method="post">
  <label>Final degree (Ph.D. / M.A. / B.A.) *</label>
  <input type="text" name="degree" value="{{ suggested_degree }}" required>

  <label>Graduation year *</label>
  <input type="text" name="graduation_year" required>

  <label>Publications & research with you (markdown supported)</label>
  <textarea name="publications" rows="4" placeholder="Thesis - [Title](url); [Article](doi)"></textarea>

  <label>Post-McGill placement (markdown supported — current employment, education, etc.)</label>
  <textarea name="post_mcgill" rows="3" placeholder="e.g., Post-Doc, Dartmouth College"></textarea>

  <button type="submit">Promote to alumni</button>
  <a href="{{ url_for('lab_view') }}" style="margin-left:1em">Cancel</a>
</form>
""" + PAGE_FOOT,
        title=f"Promote {m['name']}", sections=SECTIONS, m=m, suggested_degree=suggested_degree,
    )


@app.route("/publications")
def publications_list():
    """List all tagged publications from cv-tag-proposal.yml grouped by section."""
    _, proposal = load_yaml_with_header(PROPOSAL_PATH)
    sections = proposal.get("sections", {}) or {}
    return render_template_string(
        PAGE_HEAD + """
<h2>Publications</h2>
<p>Click any entry to add an award, media coverage, or press release. Annotations write directly to the Zotero item's <code>extra</code> field via the Web API.</p>
{% for sec in pub_sections %}
  {% set items = pub_data.get(sec, []) %}
  {% if items %}
    <h3>{{ sec }} ({{ items|length }})</h3>
    <table>
    <thead><tr><th>Title</th><th>Citekey</th><th>Existing annotations</th><th></th></tr></thead>
    <tbody>
    {% for e in items %}
      {% set ck = e.get('match_citekey') %}
      {% if ck and ck != 'SKIP' %}
      <tr>
        <td>{{ e.get('latex_title','')[:70] }}</td>
        <td><code>{{ ck }}</code></td>
        <td>
          {% set anns = e.get('latex_annotations') or [] %}
          {% if anns %}
            <small>{{ anns|length }} annotation(s)</small>
          {% else %}
            <small style="color:#aaa">none</small>
          {% endif %}
        </td>
        <td><a href="{{ url_for('annotate_publication', citekey=ck) }}">+ annotation</a></td>
      </tr>
      {% endif %}
    {% endfor %}
    </tbody>
    </table>
  {% endif %}
{% endfor %}
""" + PAGE_FOOT,
        title="Publications", sections=SECTIONS, pub_sections=PUB_SECTIONS,
        pub_data=sections,
    )


@app.route("/publications/<citekey>/annotate", methods=["GET", "POST"])
def annotate_publication(citekey):
    """Add an award or media citation to an existing tagged publication."""
    api_key = _zotero_api_key()
    if not api_key:
        flash(f"Missing Zotero API key at {ZOTERO_KEY_FILE}", "error")
        return redirect(url_for("publications_list"))

    if request.method == "POST":
        ann_type = request.form.get("ann_type", "")
        value = (request.form.get("value") or "").strip()
        label = (request.form.get("label") or "").strip()
        url = (request.form.get("url") or "").strip()

        line = _annotation_to_extra_line(ann_type, value, label, url)
        if not line:
            flash("Missing required fields for that annotation type", "error")
            return redirect(url_for("annotate_publication", citekey=citekey))

        item_key = _citekey_to_itemkey(citekey)
        if not item_key:
            flash(f"Could not find {citekey} in Zotero (is Zotero running?)", "error")
            return redirect(url_for("publications_list"))

        try:
            item = _zotero_get(item_key, api_key)
        except Exception as e:
            flash(f"Zotero GET failed: {e}", "error")
            return redirect(url_for("publications_list"))

        version = item["version"]
        existing_extra = item["data"].get("extra", "") or ""
        # Avoid dup
        if line.strip() in (l.strip() for l in existing_extra.splitlines()):
            flash("That exact annotation is already in the extra field", "error")
            return redirect(url_for("publications_list"))
        new_extra = (existing_extra + ("\n" if existing_extra else "") + line).strip()

        code, err = _zotero_patch(item_key, version, {"extra": new_extra}, api_key)
        if 200 <= code < 300:
            # Also update the local proposal's latex_annotations for consistency
            ph, proposal = load_yaml_with_header(PROPOSAL_PATH)
            for sec_items in (proposal.get("sections") or {}).values():
                for e in sec_items or []:
                    if e.get("match_citekey") == citekey:
                        e.setdefault("latex_annotations", []).append(line)
                        break
            dump_yaml_with_header(PROPOSAL_PATH, ph, proposal)
            flash(f"Wrote to Zotero: {line}", "")
            return redirect(url_for("publications_list"))
        else:
            flash(f"Zotero PATCH failed ({code}): {err[:200]}", "error")
            return redirect(url_for("annotate_publication", citekey=citekey))

    return render_template_string(
        PAGE_HEAD + """
<h2>Add annotation: <code>{{ citekey }}</code></h2>
<p>Writes a <code>tex.cv-*</code> line to the item's Zotero <code>extra</code> field via the Web API.</p>
<form method="post">
  <label>Annotation type *</label>
  <select name="ann_type" id="ann_type" onchange="updateFields()">
  {% for v, label in types %}
    <option value="{{ v }}">{{ label }}</option>
  {% endfor %}
  </select>

  <div id="award_fields">
    <label>Award text (e.g., "Best Paper, 2025 APSA")</label>
    <input type="text" name="value">
  </div>

  <div id="media_fields" style="display:none">
    <label>Outlet label (e.g., "Washington Post")</label>
    <input type="text" name="label">
    <label>URL</label>
    <input type="text" name="url">
  </div>

  <div id="press_fields" style="display:none">
    <label>Press release URL</label>
    <input type="text" name="url">
  </div>

  <button type="submit">Add to Zotero</button>
  <a href="{{ url_for('publications_list') }}" style="margin-left:1em">Cancel</a>
</form>
<script>
function updateFields() {
  var t = document.getElementById('ann_type').value;
  document.getElementById('award_fields').style.display = t.startsWith('award') ? 'block' : 'none';
  document.getElementById('media_fields').style.display = (t.startsWith('media') && t !== 'media_press_release') ? 'block' : 'none';
  document.getElementById('press_fields').style.display = t === 'media_press_release' ? 'block' : 'none';
}
updateFields();
</script>
""" + PAGE_FOOT,
        title=f"Annotate {citekey}", sections=SECTIONS, citekey=citekey, types=ANNOTATION_TYPES,
    )


@app.route("/section/under_review/publish/<int:idx>", methods=["GET", "POST"])
def publish_under_review(idx):
    """Move an under_review entry to a published Zotero-tracked publication."""
    header, data = load_yaml_with_header(CV_PATH)
    entries = data.get("under_review", []) or []
    if idx >= len(entries):
        flash("Index out of range", "error")
        return redirect(url_for("section_view", section="under_review"))
    entry = entries[idx]

    if request.method == "POST":
        citekey = (request.form.get("citekey") or "").strip()
        section = (request.form.get("section") or "peer-reviewed").strip()
        if not citekey or section not in PUB_SECTIONS:
            flash("Need a citekey and a valid section", "error")
            return redirect(url_for("publish_under_review", idx=idx))

        # 1. Add to cv-tag-proposal under the chosen section
        proposal_header, proposal = load_yaml_with_header(PROPOSAL_PATH)
        proposal["sections"].setdefault(section, []).append({
            "latex_title": entry.get("title", ""),
            "latex_year": entry.get("year"),
            "match_citekey": citekey,
            "match_score": 100,
            "proposed_tags": ["cv:include", f"cv:section/{section}"],
        })
        dump_yaml_with_header(PROPOSAL_PATH, proposal_header, proposal)

        # 2. Remove from under_review in cv.yml
        entries.pop(idx)
        dump_yaml_with_header(CV_PATH, header, data)

        flash(f"Promoted '{entry.get('title','')[:60]}' to {section} as {citekey}. Remember to run apply-tags then rebuild.", "")
        return redirect(url_for("section_view", section="under_review"))

    return render_template_string(
        PAGE_HEAD + """
<h2>Mark as published: {{ entry.title }}</h2>
<p><em>This will:</em></p>
<ol>
  <li>Add the citekey to <code>cv-tag-proposal.yml</code> under the chosen section</li>
  <li>Remove the entry from <code>under_review</code> in <code>cv.yml</code></li>
  <li>You'll need to manually run <code>python3 scripts/apply-tags.py --commit</code> to tag the Zotero item, then click Rebuild</li>
</ol>
<form method="post">
  <label>Zotero citekey *</label>
  <input type="text" name="citekey" required placeholder="e.g., erlich_NewPaper_2026">
  <label>CV section *</label>
  <select name="section">
    <option value="peer-reviewed">peer-reviewed</option>
    <option value="editor-reviewed">editor-reviewed</option>
    <option value="book-review">book-review</option>
    <option value="blog">blog</option>
    <option value="working-paper">working-paper</option>
  </select>
  <button type="submit">Promote</button>
  <a href="{{ url_for('section_view', section='under_review') }}" style="margin-left:1em">Cancel</a>
</form>
""" + PAGE_FOOT,
        title="Mark as published", sections=SECTIONS, entry=entry,
    )


@app.route("/section/<section>/delete/<int:idx>")
def section_delete(section, idx):
    if section not in SECTIONS:
        return redirect(url_for("index"))
    sec = SECTIONS[section]
    header, data = load_yaml_with_header(CV_PATH)
    entries = get_at_path(data, sec["path"]) or []
    if idx < len(entries):
        removed = entries.pop(idx)
        dump_yaml_with_header(CV_PATH, header, data)
        flash(f"Deleted: {sec['summary'](removed)}", "")
    return redirect(url_for("section_view", section=section))


# ---------- Letters of Recommendation ----------

import secrets
from datetime import datetime, date as _date


def load_letters() -> dict:
    """Load letter-requests.yml, return the raw dict with 'requests' list."""
    if not LETTERS_PATH.exists():
        return {"requests": []}
    text = LETTERS_PATH.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    data.setdefault("requests", [])
    return data


def save_letters(data: dict) -> None:
    """Save letter-requests.yml preserving header comments."""
    # Preserve top-of-file comments (same convention as cv.yml / lab.yml)
    existing_header = ""
    if LETTERS_PATH.exists():
        lines = LETTERS_PATH.read_text(encoding="utf-8").splitlines()
        header_lines = []
        for line in lines:
            if line.lstrip().startswith("#") or line.strip() == "":
                header_lines.append(line)
            else:
                break
        if header_lines:
            existing_header = "\n".join(header_lines).rstrip() + "\n\n"
    with open(LETTERS_PATH, "w", encoding="utf-8") as f:
        if existing_header:
            f.write(existing_header)
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120, default_flow_style=False)


def sync_tokens_to_kv_async() -> None:
    """Fire-and-forget: push active letter-request tokens to Cloudflare KV
    so the Worker can validate them immediately. Called after creating a
    new letter request so Aaron doesn't have to remember to run the sync
    script manually before emailing the student their upload link.

    Runs asynchronously to keep the Flask response snappy — typical KV
    sync takes <1s but network hiccups can stretch that."""
    sync_script = REPO / "scripts" / "sync-letter-tokens-to-kv.py"
    if not sync_script.exists():
        return
    try:
        # Popen with no wait() — child process runs independently
        subprocess.Popen(
            [sys.executable, str(sync_script)],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        # Don't block letter creation on sync failures — user can run
        # `python3 scripts/sync-letter-tokens-to-kv.py` manually.
        app.logger.warning(f"sync-to-KV launch failed: {e}")


def find_letter(token: str) -> tuple[int, dict | None]:
    """Return (index, entry) for a given token, or (-1, None)."""
    data = load_letters()
    for i, r in enumerate(data["requests"]):
        if r.get("token") == token:
            return i, r
    return -1, None


def transition_letter(token: str, new_state: str) -> bool:
    if new_state not in LETTER_STATES:
        return False
    data = load_letters()
    for r in data["requests"]:
        if r.get("token") == token:
            r["state"] = new_state
            r.setdefault("state_log", []).append({
                "state": new_state,
                "at": datetime.now().isoformat(timespec="seconds"),
            })
            save_letters(data)
            return True
    return False


def list_existing_folders() -> list[dict]:
    """Scan the OneDrive LORs tree and return existing student folders.
    Used by the re-upload picker. Each entry: {category, folder_name, path}."""
    results = []
    if not LORS_ROOT.exists():
        return results
    for cat in LETTER_CATEGORIES:
        cat_dir = LORS_ROOT / cat
        if not cat_dir.exists():
            continue
        try:
            for d in sorted(cat_dir.iterdir()):
                if d.is_dir() and not d.name.startswith("."):
                    results.append({
                        "category": cat,
                        "folder_name": d.name,
                        "relative_path": f"{cat}/{d.name}",
                        "full_path": str(d),
                    })
        except PermissionError:
            continue
    return results


# ---------- Letters routes ----------

@app.route("/letters")
def letters_view():
    data = load_letters()
    # Split active vs closed
    active = [r for r in data["requests"] if r.get("state") not in ("sent", "closed")]
    closed = [r for r in data["requests"] if r.get("state") in ("sent", "closed")]
    # Sort active by created date descending
    active.sort(key=lambda r: r.get("created", ""), reverse=True)
    closed.sort(key=lambda r: r.get("created", ""), reverse=True)
    return render_template_string(
        PAGE_HEAD + """
<h2>Letters of Recommendation</h2>
<p>
  <a href="{{ url_for('letters_new') }}" style="background:#6b1b1b;color:#fff;padding:0.4em 0.9em;border-radius:3px;text-decoration:none">+ New letter request</a>
  &nbsp;
  <a href="{{ url_for('letters_reupload_pick') }}" style="background:#2a6;color:#fff;padding:0.4em 0.9em;border-radius:3px;text-decoration:none">↻ Re-upload link (returning student)</a>
</p>

<h3>Active requests <small>({{ active|length }})</small></h3>
{% if active %}
<table>
<thead><tr><th>State</th><th>Student</th><th>Category</th><th>Type</th><th>Deadline</th><th>Created</th><th>Actions</th></tr></thead>
<tbody>
{% for r in active %}
<tr>
  <td><code>{{ r.state }}</code></td>
  <td><strong>{{ r.last_name }}, {{ r.first_name }}</strong> ({{ r.first_year }})</td>
  <td>{{ r.category }}</td>
  <td>{{ r.letter_type }}</td>
  <td>
    {% if r.programs %}
      {% for p in r.programs %}{{ p.deadline or '' }}{% if not loop.last %}, {% endif %}{% endfor %}
    {% endif %}
  </td>
  <td>{{ r.created }}</td>
  <td class="actions">
    <a href="{{ url_for('letters_detail', token=r.token) }}">open</a>
    {% if r.state == 'draft_ready' %}
    <a href="{{ url_for('letters_transition', token=r.token, new_state='approved') }}" style="color:#2a6">approve</a>
    {% endif %}
    {% if r.state == 'approved' %}
    <a href="{{ url_for('letters_transition', token=r.token, new_state='sent') }}" style="color:#2a6">mark sent</a>
    {% endif %}
    <a class="del" href="{{ url_for('letters_delete', token=r.token) }}" onclick="return confirm('Delete this letter request?')">del</a>
  </td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p><em>No active requests.</em></p>
{% endif %}

<h3>Sent / closed <small>({{ closed|length }})</small></h3>
{% if closed %}
<table>
<thead><tr><th>State</th><th>Student</th><th>Category</th><th>Type</th><th>Sent</th></tr></thead>
<tbody>
{% for r in closed %}
<tr>
  <td><code>{{ r.state }}</code></td>
  <td>{{ r.last_name }}, {{ r.first_name }}</td>
  <td>{{ r.category }}</td>
  <td>{{ r.letter_type }}</td>
  <td>{% for e in r.state_log %}{% if e.state == 'sent' %}{{ e.at[:10] }}{% endif %}{% endfor %}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% else %}
<p><em>No sent/closed requests yet.</em></p>
{% endif %}
""" + PAGE_FOOT,
        title="Letters", sections=SECTIONS, active=active, closed=closed,
    )


@app.route("/letters/new", methods=["GET", "POST"])
def letters_new():
    if request.method == "POST":
        last_name = (request.form.get("last_name") or "").strip()
        first_name = (request.form.get("first_name") or "").strip()
        first_year = (request.form.get("first_year") or "").strip()
        category = (request.form.get("category") or "").strip()
        letter_type = (request.form.get("letter_type") or "").strip()
        if not all([last_name, first_name, first_year, category, letter_type]):
            flash("All fields are required", "error")
            return redirect(url_for("letters_new"))
        if category not in LETTER_CATEGORIES:
            flash("Invalid category", "error")
            return redirect(url_for("letters_new"))
        if letter_type not in [t[0] for t in LETTER_TYPES]:
            flash("Invalid letter type", "error")
            return redirect(url_for("letters_new"))

        folder_name = f"{last_name}_{first_name}_{first_year}"
        folder_path = f"{category}/{folder_name}"
        token = secrets.token_urlsafe(18)  # ~24 chars

        entry = {
            "token": token,
            "last_name": last_name,
            "first_name": first_name,
            "first_year": int(first_year) if first_year.isdigit() else first_year,
            "category": category,
            "letter_type": letter_type,
            "folder_path": folder_path,
            "programs": [],  # populated by the student via the Worker form
            "state": "pending_upload",
            "created": _date.today().isoformat(),
            "state_log": [
                {"state": "pending_upload", "at": datetime.now().isoformat(timespec="seconds")}
            ],
        }
        data = load_letters()
        data["requests"].append(entry)
        save_letters(data)
        sync_tokens_to_kv_async()
        return redirect(url_for("letters_detail", token=token))

    today_year = _date.today().year
    return render_template_string(
        PAGE_HEAD + """
<h2>New letter request</h2>
<form method="post">
  <label>Last name *</label>
  <input type="text" name="last_name" required autofocus>

  <label>First name *</label>
  <input type="text" name="first_name" required>

  <label>First year you wrote this student a letter *</label>
  <input type="number" name="first_year" value="{{ today_year }}" required>
  <small>For brand-new students, keep the default. For returning students, use <em>Re-upload link</em> instead — this form creates a new folder.</small>

  <label>Category *</label>
  <select name="category" required>
    {% for c in categories %}
    <option value="{{ c }}">{{ c }}</option>
    {% endfor %}
  </select>

  <label>Letter type *</label>
  <select name="letter_type" required>
    {% for val, label in types %}
    <option value="{{ val }}">{{ label }}</option>
    {% endfor %}
  </select>

  <p style="background:#fff8e1;border-left:4px solid #e0c060;padding:0.8em 1em;margin:1.2em 0;font-size:0.92em">
    <strong>Note:</strong> The student fills in their list of programs, deadlines, portal URLs, etc. on the upload form itself.
    You don't enter any of that here — just generate the link, paste it into your reply email, and after they submit run
    <code>scripts/pull-letter-forms-from-kv.py</code> to pull their answers back into this dashboard.
  </p>

  <button type="submit">Generate upload link</button>
  <a href="{{ url_for('letters_view') }}" style="margin-left:1em">Cancel</a>
</form>
""" + PAGE_FOOT,
        title="New letter request", sections=SECTIONS,
        categories=LETTER_CATEGORIES, types=LETTER_TYPES, today_year=today_year,
    )


@app.route("/letters/reupload")
def letters_reupload_pick():
    folders = list_existing_folders()
    return render_template_string(
        PAGE_HEAD + """
<h2>Re-upload link for returning student</h2>
<p>Pick an existing student folder. A new upload link will be generated that targets the same folder; new uploads land alongside existing files.</p>
<p>Search: <input type="text" id="filter" oninput="filterTable()" placeholder="type to filter"></p>
<table id="folders-table">
<thead><tr><th>Category</th><th>Folder</th><th></th></tr></thead>
<tbody>
{% for f in folders %}
<tr>
  <td>{{ f.category }}</td>
  <td><code>{{ f.folder_name }}</code></td>
  <td><a href="{{ url_for('letters_reupload_confirm', category=f.category, folder_name=f.folder_name) }}">select</a></td>
</tr>
{% endfor %}
</tbody>
</table>
<p><small>Found {{ folders|length }} folders under <code>{{ lors_root }}</code></small></p>
<script>
function filterTable() {
  var q = document.getElementById('filter').value.toLowerCase();
  var rows = document.querySelectorAll('#folders-table tbody tr');
  rows.forEach(function(r) {
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
</script>
""" + PAGE_FOOT,
        title="Re-upload link", sections=SECTIONS, folders=folders, lors_root=LORS_ROOT,
    )


@app.route("/letters/reupload/confirm", methods=["GET", "POST"])
def letters_reupload_confirm():
    category = request.args.get("category", "") or request.form.get("category", "")
    folder_name = request.args.get("folder_name", "") or request.form.get("folder_name", "")
    if category not in LETTER_CATEGORIES:
        flash("Invalid category", "error")
        return redirect(url_for("letters_reupload_pick"))

    if request.method == "POST":
        letter_type = (request.form.get("letter_type") or "").strip()
        if letter_type not in [t[0] for t in LETTER_TYPES]:
            flash("Invalid letter type", "error")
            return redirect(url_for("letters_reupload_confirm", category=category, folder_name=folder_name))

        # Parse folder name: LastName_FirstName_YYYY
        parts = folder_name.rsplit("_", 1)
        try:
            first_year = int(parts[-1]) if parts[-1].isdigit() else folder_name
            name_parts = parts[0].split("_", 1)
            last_name = name_parts[0]
            first_name = name_parts[1] if len(name_parts) > 1 else ""
        except Exception:
            last_name = folder_name
            first_name = ""
            first_year = ""

        token = secrets.token_urlsafe(18)
        entry = {
            "token": token,
            "last_name": last_name,
            "first_name": first_name,
            "first_year": first_year,
            "category": category,
            "letter_type": letter_type,
            "folder_path": f"{category}/{folder_name}",
            "programs": [],  # populated by the student via the Worker form
            "returning": True,
            "state": "pending_upload",
            "created": _date.today().isoformat(),
            "state_log": [
                {"state": "pending_upload", "at": datetime.now().isoformat(timespec="seconds")}
            ],
        }
        data = load_letters()
        data["requests"].append(entry)
        save_letters(data)
        sync_tokens_to_kv_async()
        return redirect(url_for("letters_detail", token=token))

    return render_template_string(
        PAGE_HEAD + """
<h2>Re-upload for: {{ folder_name }}</h2>
<p>Category: <strong>{{ category }}</strong></p>
<p>New uploads will land in <code>LORs/{{ category }}/{{ folder_name }}/</code> alongside any existing files.</p>
<form method="post">
  <input type="hidden" name="category" value="{{ category }}">
  <input type="hidden" name="folder_name" value="{{ folder_name }}">
  <label>Letter type *</label>
  <select name="letter_type" required>
    {% for val, label in types %}
    <option value="{{ val }}">{{ label }}</option>
    {% endfor %}
  </select>
  <p style="background:#fff8e1;border-left:4px solid #e0c060;padding:0.8em 1em;margin:1.2em 0;font-size:0.92em">
    <strong>Note:</strong> The student fills in programs, deadlines, and portal URLs on the upload form itself.
    Run <code>scripts/pull-letter-forms-from-kv.py</code> after they submit to mirror their answers back here.
  </p>
  <button type="submit">Generate re-upload link</button>
  <a href="{{ url_for('letters_reupload_pick') }}" style="margin-left:1em">Back</a>
</form>
""" + PAGE_FOOT,
        title="Re-upload confirm", sections=SECTIONS,
        category=category, folder_name=folder_name, types=LETTER_TYPES,
    )


@app.route("/letters/<token>")
def letters_detail(token):
    _, r = find_letter(token)
    if not r:
        flash("Request not found", "error")
        return redirect(url_for("letters_view"))
    upload_url = f"https://upload.aaronerlich.com/upload/{token}"
    folder_full = LORS_ROOT / r.get("folder_path", "")
    return render_template_string(
        PAGE_HEAD + """
<h2>{{ r.last_name }}, {{ r.first_name }} ({{ r.first_year }})</h2>
<p>
  <strong>State:</strong> <code>{{ r.state }}</code>
  &nbsp; <strong>Type:</strong> {{ r.letter_type }}
  &nbsp; <strong>Category:</strong> {{ r.category }}
</p>

<h3>Upload link (email to student)</h3>
<p><input type="text" value="{{ upload_url }}" readonly style="width:100%;font-family:monospace;padding:0.5em;background:#fff8e1;border:1px solid #e0c060" onclick="this.select()"></p>
<p><small>Click to select, then copy. Send this URL in your reply email to the student. The token is single-use and tied to this student.</small></p>

<h3>Folder</h3>
<p><code>{{ folder_full }}</code></p>
<p><small>Files will land here once the student uploads. Check the folder manually or wait for the notification email.</small></p>

<h3>Programs</h3>
{% if r.programs %}
<ul>
  {% for p in r.programs %}
  <li>
    <strong>{{ p.name }}</strong>
    {% if p.institution %} — {{ p.institution }}{% endif %}
    {% if p.city %} ({{ p.city }}){% endif %}
    <br><small>
      {% if p.deadline %}Deadline: <code>{{ p.deadline }}</code>{% endif %}
      {% if p.submission_method %} &nbsp; · &nbsp; via <code>{{ p.submission_method }}</code>{% endif %}
      {% if p.portal_url %} &nbsp; · &nbsp; <a href="{{ p.portal_url }}" target="_blank" rel="noopener">{{ p.portal_url }}</a>{% endif %}
      {% if p.waived_right %} &nbsp; · &nbsp; waived{% endif %}
    </small>
    {% if p.notes %}<br><small><em>{{ p.notes }}</em></small>{% endif %}
  </li>
  {% endfor %}
</ul>
{% else %}
<p><em>No programs submitted yet.</em> Once the student fills in the form, run <code>scripts/pull-letter-forms-from-kv.py</code> to pull the data.</p>
{% endif %}

<h3>State transitions</h3>
<p>
  {% for state in states %}
    {% if state == r.state %}
      <strong style="color:#6b1b1b">{{ state }}</strong>
    {% else %}
      <a href="{{ url_for('letters_transition', token=token, new_state=state) }}">{{ state }}</a>
    {% endif %}
    {% if not loop.last %} → {% endif %}
  {% endfor %}
</p>

<h3>State log</h3>
<ul>
{% for e in r.state_log %}
  <li><code>{{ e.at }}</code> — {{ e.state }}</li>
{% endfor %}
</ul>

<p><a href="{{ url_for('letters_view') }}">← back to Letters</a></p>
""" + PAGE_FOOT,
        title=f"{r['last_name']}, {r['first_name']}", sections=SECTIONS,
        r=r, upload_url=upload_url, folder_full=folder_full, states=LETTER_STATES, token=token,
    )


@app.route("/letters/<token>/transition/<new_state>")
def letters_transition(token, new_state):
    if transition_letter(token, new_state):
        flash(f"State → {new_state}", "")
    else:
        flash(f"Failed to transition to {new_state}", "error")
    return redirect(url_for("letters_detail", token=token))


@app.route("/letters/<token>/delete")
def letters_delete(token):
    data = load_letters()
    data["requests"] = [r for r in data["requests"] if r.get("token") != token]
    save_letters(data)
    flash("Letter request deleted", "")
    return redirect(url_for("letters_view"))


@app.route("/rebuild")
def rebuild():
    proc1 = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    proc_lab = subprocess.run(
        [sys.executable, str(BUILD_LAB_SCRIPT)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    proc2 = subprocess.run(
        ["quarto", "render", "cv.qmd", "lab.qmd"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    output = (
        f"$ python3 scripts/build-cv.py\n{proc1.stdout}\n{proc1.stderr}\n\n"
        f"$ python3 scripts/build-lab.py\n{proc_lab.stdout}\n{proc_lab.stderr}\n\n"
        f"$ quarto render cv.qmd lab.qmd\n{proc2.stdout[-2000:]}\n{proc2.stderr[-1000:]}"
    )
    success = proc1.returncode == 0 and proc_lab.returncode == 0 and proc2.returncode == 0
    # Make sure a preview server is actually up (auto-start if the port is free).
    ensure_preview_server()
    prev_state, prev_msg = preview_status()
    return render_template_string(
        PAGE_HEAD + """
<h2>Rebuild result {% if success %}✓{% else %}✗{% endif %}</h2>
{% if prev_state != 'ok' %}
<p style="background:#fdd;border:1px solid #c00;padding:0.6em;border-radius:4px;">
⚠ {{ prev_msg }}
</p>
{% endif %}
<pre class="rebuild-output">{{ output }}</pre>
<p>
<a href="{{ preview_url }}/cv.html" target="_blank">Open cv.html →</a>
&nbsp; <a href="{{ url_for('index') }}">Back to admin</a>
</p>
""" + PAGE_FOOT,
        title="Rebuild", sections=SECTIONS, output=output, success=success,
        prev_state=prev_state, prev_msg=prev_msg, preview_url=PREVIEW_URL,
    )


if __name__ == "__main__":
    # Default to 5001: macOS Control Center's AirPlay Receiver squats on port 5000,
    # which silently steals requests (returns an empty 403) and blocks Flask from
    # binding. Override with ADMIN_PORT if needed.
    admin_port = int(os.environ.get("ADMIN_PORT", "5001"))
    print(f"CV Admin running at http://localhost:{admin_port}", file=sys.stderr)
    ensure_preview_server()
    app.run(debug=False, port=admin_port, host="127.0.0.1")
