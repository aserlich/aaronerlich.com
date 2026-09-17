#!/usr/bin/env python3
"""Apply approved CV link fixes to Zotero's URL field.

Reads _data/link-fixes.yml (written by scripts/audit-pub-links.py) and acts ONLY
on entries with `approved: true`. Dry-run by default; --commit writes.

Why Zotero and not this repo: scripts/build-cv.py resolves a publication's link
as `item["URL"] or https://doi.org/<DOI>`, and scripts/disseminate.py reads the
same records for social posts. Fixing the library repairs the web CV, the LaTeX
CV and the dissemination queue at once. A `clear_url` action deletes the stale
URL so the renderer falls through to the DOI — usually the whole fix.

Requires Zotero running (Better BibTeX's JSON-RPC resolves citekey -> itemKey)
and an API key at ~/.config/zotero/api_key, exactly like scripts/apply-tags.py.

Usage:
    python3 scripts/apply-link-fixes.py             # dry run
    python3 scripts/apply-link-fixes.py --commit    # write to Zotero
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
FIXES_YML = REPO / "_data" / "link-fixes.yml"
KEY_FILE = Path.home() / ".config" / "zotero" / "api_key"
USER_ID = 38708
BBT_RPC = "http://localhost:23119/better-bibtex/json-rpc"
ZOTERO_API = f"https://api.zotero.org/users/{USER_ID}"


def bbt_search(query: str) -> list:
    body = json.dumps({"jsonrpc": "2.0", "method": "item.search",
                       "params": [query], "id": 1}).encode()
    req = urllib.request.Request(BBT_RPC, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp).get("result", []) or []


def citekey_to_itemkey(citekey: str) -> str | None:
    for r in bbt_search(citekey):
        if (r.get("citekey") or r.get("citation-key")) == citekey:
            m = re.search(r"/items/([A-Z0-9]+)$", r.get("id", ""))
            if m:
                return m.group(1)
    return None


def zotero_get(item_key: str, key: str) -> dict:
    req = urllib.request.Request(f"{ZOTERO_API}/items/{item_key}",
                                 headers={"Zotero-API-Key": key})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def zotero_patch(item_key: str, version: int, body: dict, key: str) -> int:
    req = urllib.request.Request(
        f"{ZOTERO_API}/items/{item_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Zotero-API-Key": key, "Content-Type": "application/json",
                 "If-Unmodified-Since-Version": str(version)},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        print(f"  ! PATCH failed: {e.code} {e.reason}", file=sys.stderr)
        detail = e.read().decode("utf-8", errors="ignore")
        if detail:
            print(f"    body: {detail[:300]}", file=sys.stderr)
        return e.code


REEXPORT_NOTE = """
Next: get the change into the CV build.
  1. Zotero: sync down (so the web-API edit reaches the local library).
  2. Zotero: File > Export Library > Better BibTeX CSL JSON, overwriting
     ~/Dropbox/research_projects/My Library.json
     (there is no auto-export configured for that file).
  3. python3 scripts/audit-pub-links.py --verify
  4. python3 scripts/build-cv.py && python3 scripts/build-cv-latex.py \\
       && quarto render cv.qmd
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="actually write to Zotero")
    args = ap.parse_args()

    if not FIXES_YML.is_file():
        sys.exit(f"No {FIXES_YML.relative_to(REPO)} — run scripts/audit-pub-links.py first.")
    data = yaml.safe_load(FIXES_YML.read_text(encoding="utf-8")) or {}
    fixes = data.get("fixes") or []

    pending = [f for f in fixes
               if f.get("approved") and not f.get("applied_at")
               and f.get("action") in ("clear_url", "set_url")]
    approved_total = sum(1 for f in fixes if f.get("approved"))

    if not pending:
        print(f"{len(fixes)} proposal(s), {approved_total} approved, nothing pending.")
        if approved_total:
            print("All approved fixes are already applied.")
        else:
            print("Set `approved: true` in _data/link-fixes.yml for the ones you want.")
        return 0

    print(f"{len(pending)} approved fix(es) to apply"
          f"{'' if args.commit else '  [DRY RUN — nothing will be written]'}\n")
    for f in pending:
        target = f["proposed_url"] if f["action"] == "set_url" else "(cleared)"
        print(f"  {f['citekey']}")
        print(f"    {f['current_url'] or '(none)'}\n    -> {target}   [{f['reason']}]")

    if not args.commit:
        print("\nRe-run with --commit to write these to Zotero.")
        return 0

    if not KEY_FILE.exists():
        sys.exit(f"No Zotero API key at {KEY_FILE}")
    api_key = KEY_FILE.read_text().strip()
    try:
        bbt_search("test")
    except Exception:
        sys.exit("Better BibTeX JSON-RPC unreachable — is Zotero running?")

    applied = 0
    for f in pending:
        ck = f["citekey"]
        item_key = citekey_to_itemkey(ck)
        if not item_key:
            print(f"  ! {ck}: no itemKey from Better BibTeX; skipped", file=sys.stderr)
            continue
        try:
            item = zotero_get(item_key, api_key)
        except Exception as e:
            print(f"  ! {ck}: GET failed ({e}); skipped", file=sys.stderr)
            continue
        version = item.get("version") or item["data"].get("version")
        new_url = f["proposed_url"] if f["action"] == "set_url" else ""
        code = zotero_patch(item_key, version, {"url": new_url}, api_key)
        if code in (200, 204):
            f["applied_at"] = date.today().isoformat()
            applied += 1
            print(f"  ok {ck} -> {new_url or '(cleared)'}")

    # Persist applied_at so a rerun is idempotent, even on partial failure.
    FIXES_YML.write_text(
        FIXES_YML.read_text(encoding="utf-8").split("\ngenerated:")[0].rstrip("\n") + "\n"
        + yaml.dump({"generated": data.get("generated"), "fixes": fixes},
                    sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")

    print(f"\nApplied {applied}/{len(pending)}.")
    if applied:
        print(REEXPORT_NOTE)
    return 0 if applied == len(pending) else 1


if __name__ == "__main__":
    sys.exit(main())
