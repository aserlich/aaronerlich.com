#!/usr/bin/env python3
"""
apply-tags.py — Apply CV tags + extra-field annotations to Zotero items.

Reads:
  _data/cv-tag-proposal.yml  (after Aaron's review)
  ~/.config/zotero/api_key

Writes via Zotero Web API (https://api.zotero.org):
  - Adds cv:include + cv:section/<name> tags to each item
  - Appends tex.cv-* annotation lines to the `extra` field

Defaults to dry-run. Pass --commit to actually write.

Conventions:
  - Set match_citekey: SKIP in the YAML to ignore an entry.
  - Edit proposed_tags directly in the YAML to override the parser.
  - latex_annotations are converted to tex.cv-* lines:
      "Winner: ..."             → tex.cv-award: winner | ...
      "Honourable Mention: ..." → tex.cv-award: honorable-mention | ...
      "Top 10 Most cited..."    → tex.cv-award: top-cited | ...
      "Media coverage: ..."     → (one tex.cv-media line per linked outlet)
      everything else           → tex.cv-note: <text>

Requires: PyYAML (`pip install pyyaml`), Zotero running locally with BBT.
"""

from __future__ import annotations
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Install PyYAML: pip install pyyaml")

REPO = Path(__file__).resolve().parents[1]
PROPOSAL = REPO / "_data" / "cv-tag-proposal.yml"
KEY_FILE = Path.home() / ".config" / "zotero" / "api_key"
USER_ID = 38708
BBT_RPC = "http://localhost:23119/better-bibtex/json-rpc"
ZOTERO_API = f"https://api.zotero.org/users/{USER_ID}"


# ---------- HTTP helpers ----------

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
            return json.load(resp).get("result", []) or []
    except Exception as e:
        print(f"  ! BBT search failed for {query!r}: {e}", file=sys.stderr)
        return []


def zotero_get(path: str, key: str) -> dict:
    req = urllib.request.Request(
        f"{ZOTERO_API}{path}",
        headers={"Zotero-API-Key": key},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def zotero_patch(item_key: str, version: int, body: dict, key: str) -> int:
    req = urllib.request.Request(
        f"{ZOTERO_API}/items/{item_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Zotero-API-Key": key,
            "Content-Type": "application/json",
            "If-Unmodified-Since-Version": str(version),
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        print(f"  ! PATCH failed: {e.code} {e.reason}", file=sys.stderr)
        body = e.read().decode("utf-8", errors="ignore")
        if body:
            print(f"    body: {body[:300]}", file=sys.stderr)
        return e.code


# ---------- citekey → itemKey ----------

def citekey_to_itemkey(citekey: str) -> str | None:
    """BBT search returns id like http://zotero.org/users/38708/items/I47EL3HC."""
    results = bbt_search(citekey)
    for r in results:
        if (r.get("citekey") or r.get("citation-key")) == citekey:
            id_url = r.get("id", "")
            m = re.search(r"/items/([A-Z0-9]+)$", id_url)
            if m:
                return m.group(1)
    # Fallback: take first result if exactly one
    if len(results) == 1:
        id_url = results[0].get("id", "")
        m = re.search(r"/items/([A-Z0-9]+)$", id_url)
        if m:
            return m.group(1)
    return None


# ---------- annotation parsing ----------

_HREF_RE = re.compile(
    r"\\href\s*\{([^}]+)\}\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)

def _clean_latex(text: str) -> str:
    """Strip common inline LaTeX markup from a fragment."""
    text = re.sub(r"\\textit\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\emph\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\texttt\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_hrefs(text: str) -> list[tuple[str, str]]:
    """Extract all \\href{url}{label} pairs, returning [(label, url), ...]."""
    out = []
    for m in _HREF_RE.finditer(text):
        url = m.group(1).strip()
        label = _clean_latex(m.group(2))
        out.append((label, url))
    return out


def _classify_outlet(label: str, url: str) -> str:
    """Heuristic outlet classifier: press-release | news | blog | podcast | magazine | other."""
    l = (label or "").lower()
    u = (url or "").lower()
    if "press release" in l or "prnewswire" in u or "/news-releases/" in u:
        return "press-release"
    if any(k in u for k in ("canadaland", "/podcast/")):
        return "podcast"
    if any(k in u for k in ("marginalrevolution", "blog", "spsp.org")):
        return "blog"
    if any(k in u for k in ("theconversation", "warontherocks", "nexos", "hilltimes")):
        return "magazine"
    if any(k in u for k in (
        "washingtonpost", "macleans", "journaldemontreal", "themessenger",
        "independent.co.ug", "kyivindependent", "psypost",
        "monkey-cage", "monkeycage",  # WaPo's politics column — Aaron treats as news
        "demtech.oii", "oii.ox.ac.uk",  # Oxford DemTech — news/research
    )):
        return "news"
    return "other"


def annotation_to_extra(annotation: str) -> list[str]:
    """Convert a LaTeX --- annotation to one or more tex.cv-* extra field lines."""
    a = annotation.strip().rstrip(".")
    if not a:
        return []

    # Awards — plain-text values
    m = re.match(r"(?i)^winner\s*[:\-]\s*(.+)", a)
    if m:
        value = _clean_latex(m.group(1))
        return [f"tex.cv-award: winner | {value}"]

    m = re.match(r"(?i)^hono(?:u)?rable\s*mention\s*[:\-]\s*(.+)", a)
    if m:
        value = _clean_latex(m.group(1))
        return [f"tex.cv-award: honorable-mention | {value}"]

    m = re.match(r"(?i)^top\s*\d+\s*most\s*cited\s*(?:article\s*award)?\s*(.*)", a)
    if m:
        value = _clean_latex(m.group(1))
        return [f"tex.cv-award: top-cited | {value or 'unspecified'}"]

    # Media coverage — split on every \href
    if re.match(r"(?i)^media\s*coverage", a):
        hrefs = _parse_hrefs(a)
        if hrefs:
            return [
                f"tex.cv-media: {_classify_outlet(label, url)} | {label} | {url}"
                for label, url in hrefs
            ]
        stripped = re.sub(r"(?i)^media\s*coverage\s*[:\-]?\s*", "", a)
        return [f"tex.cv-media: other | {_clean_latex(stripped)}"]

    # Press release (single or list)
    if re.match(r"(?i)^press\s*release", a):
        hrefs = _parse_hrefs(a)
        if hrefs:
            return [f"tex.cv-press-release: {url}" for _, url in hrefs]
        return [f"tex.cv-press-release: {_clean_latex(a)}"]

    # Generic note — still strip LaTeX
    return [f"tex.cv-note: {_clean_latex(a)}"]


def merge_extra(existing: str, new_lines: list[str]) -> str:
    """Append new tex.cv-* lines to existing extra, avoiding duplicates."""
    existing_lines = (existing or "").splitlines()
    out = list(existing_lines)
    existing_set = set(l.strip() for l in existing_lines)
    for line in new_lines:
        if line.strip() not in existing_set:
            out.append(line)
            existing_set.add(line.strip())
    return "\n".join(out).strip()


def merge_tags(existing: list[dict], new_tags: list[str]) -> list[dict]:
    """Merge new tag strings into existing tag-objects, dedupe."""
    seen = {t.get("tag") for t in existing}
    out = list(existing)
    for t in new_tags:
        if t not in seen:
            out.append({"tag": t})
            seen.add(t)
    return out


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="Actually write to Zotero (default: dry-run)")
    ap.add_argument("--proposal", default=str(PROPOSAL),
                    help=f"Path to proposal YAML (default: {PROPOSAL})")
    args = ap.parse_args()

    if not KEY_FILE.exists():
        sys.exit(f"Missing API key: {KEY_FILE}")
    api_key = KEY_FILE.read_text().strip()

    proposal = yaml.safe_load(Path(args.proposal).read_text(encoding="utf-8"))
    sections = proposal.get("sections", {}) or {}

    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"[{mode}] Reading {args.proposal}", file=sys.stderr)
    print(f"[{mode}] Zotero user: {USER_ID}", file=sys.stderr)
    print(file=sys.stderr)

    stats = {"applied": 0, "skipped": 0, "errored": 0, "no_change": 0}

    for section_tag, items in sections.items():
        if not items:
            continue
        for entry in items:
            citekey = entry.get("match_citekey")
            tags = entry.get("proposed_tags") or []
            if not citekey or citekey == "SKIP" or not tags:
                stats["skipped"] += 1
                continue

            print(f"  → {citekey}  ({entry.get('latex_title','')[:60]}...)", file=sys.stderr)

            item_key = citekey_to_itemkey(citekey)
            if not item_key:
                print(f"    ! could not resolve citekey to itemKey", file=sys.stderr)
                stats["errored"] += 1
                continue

            # Fetch current item state from Zotero Web API
            try:
                item = zotero_get(f"/items/{item_key}", api_key)
            except urllib.error.HTTPError as e:
                print(f"    ! GET failed: {e.code} {e.reason}", file=sys.stderr)
                stats["errored"] += 1
                continue

            data = item["data"]
            version = item["version"]
            current_tags = data.get("tags", [])
            current_extra = data.get("extra", "")

            # Compute new tags
            new_tags = merge_tags(current_tags, tags)

            # Compute new extra
            ann_lines = []
            for ann in entry.get("latex_annotations") or []:
                ann_lines.extend(annotation_to_extra(ann))
            new_extra = merge_extra(current_extra, ann_lines)

            tags_changed = [t for t in new_tags if t not in current_tags]
            extra_changed = new_extra != (current_extra or "")
            if not tags_changed and not extra_changed:
                stats["no_change"] += 1
                print(f"    = no change", file=sys.stderr)
                continue

            if tags_changed:
                print(f"    + tags: {[t['tag'] for t in tags_changed]}", file=sys.stderr)
            if extra_changed:
                added = set(new_extra.splitlines()) - set((current_extra or "").splitlines())
                for line in added:
                    print(f"    + extra: {line}", file=sys.stderr)

            if args.commit:
                patch_body = {}
                if tags_changed:
                    patch_body["tags"] = new_tags
                if extra_changed:
                    patch_body["extra"] = new_extra
                code = zotero_patch(item_key, version, patch_body, api_key)
                if 200 <= code < 300:
                    stats["applied"] += 1
                    time.sleep(0.1)  # be polite to API
                else:
                    stats["errored"] += 1
            else:
                stats["applied"] += 1  # would-be applied

    print(file=sys.stderr)
    print(f"[{mode}] applied={stats['applied']} no_change={stats['no_change']} skipped={stats['skipped']} errored={stats['errored']}", file=sys.stderr)
    if not args.commit:
        print("Re-run with --commit to actually write to Zotero.", file=sys.stderr)


if __name__ == "__main__":
    main()
