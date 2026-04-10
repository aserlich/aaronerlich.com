#!/usr/bin/env python3
"""
cv-add.py — Add a publication to Aaron's CV by tagging its Zotero item.

Given a citekey OR a DOI, this script:
  1. Looks up the Zotero item via Better BibTeX (local JSON-RPC)
  2. Fetches the full item from the Zotero Web API
  3. Adds cv:include + cv:section/<section> tags
  4. Optionally appends tex.cv-* lines to the `extra` field for awards / media
  5. Prints a dry-run diff by default; --commit actually writes

Requires:
  - Zotero running locally (Better BibTeX installed)
  - Zotero Web API key at ~/.config/zotero/api_key (already set up)

Usage:
  # Simple — add a paper already in Zotero
  cv-add.py berlinerCompetingTransparencyPolitical2015 peer-reviewed

  # By DOI
  cv-add.py 10.1086/724010 peer-reviewed

  # With an award
  cv-add.py erlich_WhatCorruption_2025 peer-reviewed \\
      --award winner:"Best Paper in Comparative Politics, 2025 APSA"

  # With media coverage (kind | label | url; repeatable)
  cv-add.py my_new_paper_2026 peer-reviewed \\
      --media news:"Washington Post":https://www.washingtonpost.com/... \\
      --media podcast:"Slate Money":https://slate.com/podcasts/...

  # With a press release
  cv-add.py my_new_paper_2026 peer-reviewed \\
      --press-release https://www.mcgill.ca/channels/...

  # Actually commit to Zotero (default is dry-run)
  cv-add.py my_new_paper_2026 peer-reviewed --commit
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

USER_ID = 38708
BBT_RPC = "http://localhost:23119/better-bibtex/json-rpc"
ZOTERO_API = f"https://api.zotero.org/users/{USER_ID}"
KEY_FILE = Path.home() / ".config" / "zotero" / "api_key"

VALID_SECTIONS = [
    "peer-reviewed",
    "under-review",
    "editor-reviewed",
    "book-review",
    "blog",
    "working-paper",
    "in-prep",
    "on-hold",
    "software",
    "professional-eval",
    "testimony",
]


# ---------- HTTP helpers ----------

def bbt_search(query: str) -> list:
    body = json.dumps({"jsonrpc":"2.0","method":"item.search","params":[query],"id":1}).encode()
    req = urllib.request.Request(
        BBT_RPC, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp).get("result", []) or []
    except Exception as e:
        sys.exit(f"BBT search failed: {e}\n  (is Zotero running?)")


def zotero_get(path: str, api_key: str) -> dict:
    req = urllib.request.Request(
        f"{ZOTERO_API}{path}",
        headers={"Zotero-API-Key": api_key},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def zotero_patch(item_key: str, version: int, body: dict, api_key: str) -> int:
    req = urllib.request.Request(
        f"{ZOTERO_API}/items/{item_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Zotero-API-Key": api_key,
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
        body_text = e.read().decode("utf-8", errors="ignore")
        if body_text:
            print(f"    body: {body_text[:300]}", file=sys.stderr)
        return e.code


# ---------- lookup ----------

def resolve_identifier(identifier: str) -> tuple[str, str]:
    """Return (itemKey, citekey) from a citekey OR DOI input."""
    # DOI?
    is_doi = "/" in identifier and ("10." in identifier)
    results = bbt_search(identifier)
    if not results:
        sys.exit(f"No Zotero item found for: {identifier}")

    if is_doi:
        # Match exactly by DOI
        for r in results:
            if (r.get("DOI") or "").lower() == identifier.lower():
                return _extract_itemkey(r), (r.get("citekey") or r.get("citation-key"))
        # Fall back to first
        r = results[0]
        return _extract_itemkey(r), (r.get("citekey") or r.get("citation-key"))

    # Citekey — find exact match
    for r in results:
        ck = r.get("citekey") or r.get("citation-key")
        if ck == identifier:
            return _extract_itemkey(r), ck
    # Ambiguous — show options
    if len(results) > 1:
        print(f"Ambiguous match for '{identifier}'. Candidates:", file=sys.stderr)
        for r in results[:5]:
            ck = r.get("citekey") or r.get("citation-key") or "?"
            title = (r.get("title") or "")[:70]
            print(f"  {ck}  —  {title}", file=sys.stderr)
        sys.exit("Pick one and re-run with its exact citekey.")
    r = results[0]
    return _extract_itemkey(r), (r.get("citekey") or r.get("citation-key"))


def _extract_itemkey(r: dict) -> str:
    id_url = r.get("id", "")
    m = re.search(r"/items/([A-Z0-9]+)$", id_url)
    if not m:
        sys.exit(f"Could not extract itemKey from: {id_url}")
    return m.group(1)


# ---------- extra field manipulation ----------

def build_extra_lines(args) -> list[str]:
    lines = []
    for a in args.award or []:
        # format: type:"value"
        m = re.match(r"^([a-z\-]+):(.+)$", a)
        if not m:
            sys.exit(f"--award must be 'type:\"value\"', got: {a}")
        kind = m.group(1)
        value = m.group(2).strip('"').strip("'")
        lines.append(f"tex.cv-award: {kind} | {value}")
    for m_arg in args.media or []:
        # format: kind:"label":url
        m = re.match(r"^([a-z\-]+):(.+?):(https?://.+)$", m_arg)
        if not m:
            sys.exit(f"--media must be 'kind:\"label\":url', got: {m_arg}")
        kind = m.group(1)
        label = m.group(2).strip('"').strip("'")
        url = m.group(3)
        lines.append(f"tex.cv-media: {kind} | {label} | {url}")
    for pr in args.press_release or []:
        lines.append(f"tex.cv-press-release: {pr}")
    return lines


def merge_extra(existing: str, new_lines: list[str]) -> str:
    existing_lines = (existing or "").splitlines()
    out = list(existing_lines)
    seen = {l.strip() for l in existing_lines}
    for l in new_lines:
        if l.strip() not in seen:
            out.append(l)
            seen.add(l.strip())
    return "\n".join(out).strip()


def merge_tags(existing: list[dict], new_tags: list[str]) -> tuple[list[dict], list[str]]:
    existing_set = {t.get("tag") for t in existing}
    out = list(existing)
    added = []
    for t in new_tags:
        if t not in existing_set:
            out.append({"tag": t})
            existing_set.add(t)
            added.append(t)
    return out, added


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("identifier", help="Zotero citekey OR DOI")
    ap.add_argument("section", choices=VALID_SECTIONS, help="CV section tag")
    ap.add_argument("--award", action="append", metavar='TYPE:"VALUE"',
                    help='e.g., winner:"Best Paper 2025 APSA" (repeatable)')
    ap.add_argument("--media", action="append", metavar='KIND:"LABEL":URL',
                    help='e.g., news:"New York Times":https://... (repeatable)')
    ap.add_argument("--press-release", action="append", metavar="URL",
                    help="Press release URL (repeatable)")
    ap.add_argument("--commit", action="store_true", help="Actually write (default: dry-run)")
    args = ap.parse_args()

    if not KEY_FILE.exists():
        sys.exit(f"Missing Zotero API key: {KEY_FILE}")
    api_key = KEY_FILE.read_text().strip()

    # Resolve
    item_key, citekey = resolve_identifier(args.identifier)
    print(f"Resolved: {args.identifier} → itemKey={item_key}, citekey={citekey}", file=sys.stderr)

    # Fetch
    item = zotero_get(f"/items/{item_key}", api_key)
    data = item["data"]
    version = item["version"]
    title = data.get("title", "(untitled)")
    print(f"  title: {title[:80]}", file=sys.stderr)

    # Compute new tags
    new_tag_list = [f"cv:include", f"cv:section/{args.section}"]
    merged_tags, added_tags = merge_tags(data.get("tags", []), new_tag_list)

    # Compute new extra
    extra_lines = build_extra_lines(args)
    new_extra = merge_extra(data.get("extra", ""), extra_lines)
    extra_changed = new_extra != (data.get("extra", "") or "")

    # Report
    mode = "COMMIT" if args.commit else "DRY-RUN"
    print(f"\n[{mode}]")
    if added_tags:
        for t in added_tags:
            print(f"  + tag: {t}")
    else:
        print("  (no new tags — already present)")
    if extra_changed:
        added_extra = set(new_extra.splitlines()) - set((data.get("extra","") or "").splitlines())
        for line in added_extra:
            print(f"  + extra: {line}")

    if not added_tags and not extra_changed:
        print("  (nothing to change)")
        return

    if not args.commit:
        print(f"\nRe-run with --commit to actually write.")
        return

    # Write
    patch = {}
    if added_tags:
        patch["tags"] = merged_tags
    if extra_changed:
        patch["extra"] = new_extra

    code = zotero_patch(item_key, version, patch, api_key)
    if 200 <= code < 300:
        print(f"\n✓ Written to Zotero ({code})")
    else:
        sys.exit(f"\n✗ Write failed: HTTP {code}")


if __name__ == "__main__":
    main()
