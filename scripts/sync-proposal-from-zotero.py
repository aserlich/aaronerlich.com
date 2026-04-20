#!/usr/bin/env python3
"""
sync-proposal-from-zotero.py — Refresh _data/cv-tag-proposal.yml from
Zotero's `cv:include` + `cv:section/*` tags, hit via the Zotero Web API.

Background: Better BibTeX's CSL JSON export drops tags entirely, so the
static CV build pipeline had no way to "see" newly-tagged papers. This
script closes the loop: before each build, it fetches every Zotero item
tagged `cv:include`, figures out which section each belongs to from its
`cv:section/*` tag, and updates cv-tag-proposal.yml:

  - Adds brand-new entries when a tag appears on an item not yet tracked
  - Moves entries when the section tag changes (e.g., working-paper →
    peer-reviewed after acceptance)
  - Preserves manually-curated fields on existing entries:
      latex_annotations   (awards, media coverage, press releases)
      latex_status        (Forthcoming / Accepted / Online First)
      latex_url           (override link)
      latex_year          (override year)
  - Warns about proposal entries whose citekey no longer has cv:include
    but never auto-deletes — too risky

Run:
  python3 scripts/sync-proposal-from-zotero.py           # preview (safe default)
  python3 scripts/sync-proposal-from-zotero.py --commit  # actually rewrite yaml

Defaults to dry-run for safety — duplicate-citekey messes in Zotero can
cause surprising moves. Review the preview, then re-run with --commit
when satisfied.

Credentials:
  ~/.config/zotero/api_key   — Zotero Web API token (read-only scope OK)

Depends on: stdlib + PyYAML + Zotero Web API reachable over the internet.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Install PyYAML: pip install pyyaml")

REPO = Path(__file__).resolve().parents[1]
PROPOSAL_PATH = REPO / "_data" / "cv-tag-proposal.yml"
KEY_FILE = Path.home() / ".config" / "zotero" / "api_key"
ZOTERO_JSON = Path.home() / "Dropbox" / "research_projects" / "My Library.json"
USER_ID = 38708
ZOTERO_API = f"https://api.zotero.org/users/{USER_ID}"

# Must match the cv:section/<name> tag suffix → cv-tag-proposal.yml key.
# Any cv:section/* tag outside this list is warned about and skipped.
# Order matters: used as a priority ranking when a citekey appears in
# multiple sections (from duplicate Zotero items or stale tags on a
# single item). Higher-index = more "published" = wins.
SECTION_PRIORITY = [
    "working-paper",   # least published
    "blog",
    "book-review",
    "editor-reviewed",
    "peer-reviewed",   # most published → wins ties
]
KNOWN_SECTIONS = set(SECTION_PRIORITY)

def _section_rank(s: str) -> int:
    try:
        return SECTION_PRIORITY.index(s)
    except ValueError:
        return -1

# Fields we preserve when an entry already exists in the proposal — these
# are manually curated (annotations, status, overrides) and should not be
# clobbered by a no-new-info resync.
PRESERVE_FIELDS = (
    "latex_annotations",
    "latex_status",
    "latex_url",
    "latex_year",
    "latex_title",
    "match_zotero_title",
    "match_score",
)

CITEKEY_RE = re.compile(r"^Citation Key:\s*(\S+)\s*$", re.MULTILINE)


def load_api_key() -> str:
    if not KEY_FILE.exists():
        sys.exit(f"No Zotero API key at {KEY_FILE}")
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(f"Empty API key in {KEY_FILE}")
    return key


def zotero_items_by_tag(tag: str, key: str, start: int = 0, limit: int = 100) -> list[dict]:
    """Fetch all items carrying a given tag, paginated."""
    results: list[dict] = []
    while True:
        url = f"{ZOTERO_API}/items?tag={urllib.parse.quote(tag)}&limit={limit}&start={start}"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                batch = json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:300]
            sys.exit(f"Zotero API error {e.code}: {body}")
        if not batch:
            break
        results.extend(batch)
        if len(batch) < limit:
            break
        start += limit
    return results


def citekey_from_extra(extra: str) -> str | None:
    """Better BibTeX writes 'Citation Key: <ck>' into an item's Extra field
    when 'Cite as' is set. For BBT installs without that setting (including
    Aaron's), Extra is blank and we fall back to title-matching against the
    CSL JSON export."""
    if not extra:
        return None
    m = CITEKEY_RE.search(extra)
    return m.group(1) if m else None


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")

def _normalize_title(s: str) -> str:
    """Lowercase + strip all punctuation/whitespace for robust title match.
    Zotero sometimes has slightly different titles than BBT export (curly
    vs straight quotes, stray whitespace, capitalization drift)."""
    return _NORMALIZE_RE.sub("", (s or "").lower())


def build_title_index() -> dict[str, list[dict]]:
    """Map normalized-title → list of candidate CSL entries from the local
    BBT CSL JSON. Each candidate is a dict with citekey + metadata we can
    score on (year present? author present?). Duplicates in Zotero
    (same title, multiple citekeys) are common in Aaron's library, so
    returning a list and scoring is more robust than picking the first."""
    if not ZOTERO_JSON.exists():
        return {}
    try:
        data = json.loads(ZOTERO_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! could not read {ZOTERO_JSON}: {e}", file=sys.stderr)
        return {}
    idx: dict[str, list[dict]] = {}
    for it in data:
        citekey = it.get("id") or it.get("citation-key")
        title = it.get("title") or ""
        if not citekey or not title:
            continue
        key = _normalize_title(title)
        if not key:
            continue
        issued = it.get("issued") or {}
        has_year = bool((issued.get("date-parts") or [[None]])[0][0])
        has_authors = bool(it.get("author"))
        idx.setdefault(key, []).append({
            "citekey": citekey,
            "has_year": has_year,
            "has_authors": has_authors,
        })
    return idx


def resolve_citekey(title: str, title_idx: dict, existing_proposal_cks: set) -> str | None:
    """Pick the best citekey for a title, preferring:
      1. A citekey already present in the current proposal (stability)
      2. A citekey whose CSL entry has both year and authors (non-stub)
      3. The alphabetically-first remaining candidate (tiebreaker)
    Returns None if no title match at all."""
    cands = title_idx.get(_normalize_title(title)) or []
    if not cands:
        return None
    # Tier 1: citekeys already in the proposal
    in_proposal = [c for c in cands if c["citekey"] in existing_proposal_cks]
    if in_proposal:
        return in_proposal[0]["citekey"]
    # Tier 2: non-stubs (year + authors present)
    complete = [c for c in cands if c["has_year"] and c["has_authors"]]
    if complete:
        return sorted(complete, key=lambda c: c["citekey"])[0]["citekey"]
    # Tier 3: anything else, sorted for determinism
    return sorted(cands, key=lambda c: c["citekey"])[0]["citekey"]


def section_from_tags(tags: list[dict]) -> tuple[str | None, list[str]]:
    """Return (canonical-section, all cv:section/* subtypes) found in the
    tag list. If an item has multiple cv:section/* tags (stale + fresh),
    returns the most-published one (peer-reviewed > editor-reviewed >
    book-review > blog > working-paper)."""
    found = []
    for t in tags or []:
        name = t.get("tag") if isinstance(t, dict) else str(t)
        if name and name.startswith("cv:section/"):
            suffix = name.split("/", 1)[1]
            found.append(suffix)
    known = [f for f in found if f in KNOWN_SECTIONS]
    canonical = max(known, key=_section_rank) if known else None
    return canonical, found


def load_proposal() -> dict:
    return yaml.safe_load(PROPOSAL_PATH.read_text(encoding="utf-8")) or {}


def save_proposal(data: dict) -> None:
    """Write yaml preserving the section-ordered layout. Higher default
    line width (200) keeps long titles on one line, matching the original
    file's formatting."""
    with PROPOSAL_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            data, f, sort_keys=False, allow_unicode=True,
            default_flow_style=False, width=200,
        )


def build_ck_index(proposal: dict) -> dict[str, tuple[str, int]]:
    """Map citekey → (section-name, index-within-section) for every entry
    currently in the proposal. Used to detect adds / moves / preserves."""
    idx: dict[str, tuple[str, int]] = {}
    sections = proposal.get("sections") or {}
    for sect_name, entries in sections.items():
        for i, e in enumerate(entries or []):
            ck = e.get("match_citekey")
            if ck and ck != "SKIP":
                idx[ck] = (sect_name, i)
    return idx


def sync(dry_run: bool = False) -> int:
    key = load_api_key()
    proposal = load_proposal()
    proposal.setdefault("sections", {})
    for sect in KNOWN_SECTIONS:
        proposal["sections"].setdefault(sect, [])

    existing_idx = build_ck_index(proposal)

    # Title → citekey map from the local BBT CSL JSON. Used as fallback
    # when the Extra field doesn't carry `Citation Key: …` (which is the
    # default for many BBT installs).
    title_idx = build_title_index()
    print(f"Loaded {len(title_idx)} title → citekey entries from local BBT export",
          file=sys.stderr)

    print("Fetching cv:include items from Zotero…", file=sys.stderr)
    tagged = zotero_items_by_tag("cv:include", key)
    print(f"  {len(tagged)} tagged items returned", file=sys.stderr)

    added = 0
    moved = 0
    skipped = 0
    warnings: list[str] = []

    # Track which citekeys we saw, and for each, which section they best
    # belong to (highest-ranked across all Zotero items carrying that ck).
    # Storing section + source title lets us dedupe when Zotero has multiple
    # items with the same title but different section tags.
    resolved: dict[str, dict] = {}  # citekey → {"section", "title", "all_titles": []}

    # First pass: resolve each Zotero item to a (citekey, section) pair, and
    # for each citekey track the highest-ranked section encountered.
    for item in tagged:
        data = item.get("data") or {}
        tags = data.get("tags") or []
        extra = data.get("extra") or ""
        title = data.get("title") or ""

        section, all_section_tags = section_from_tags(tags)

        citekey = citekey_from_extra(extra) or resolve_citekey(
            title, title_idx, set(existing_idx.keys()))
        if not citekey:
            warnings.append(
                f"  ! no citekey for {title[:60]!r} — "
                f"not in Extra field AND no matching title in BBT export"
            )
            skipped += 1
            continue

        if not section:
            warnings.append(
                f"  ! {citekey} has cv:include but no recognized cv:section/* tag "
                f"(saw: {all_section_tags or 'none'}) — skipping"
            )
            skipped += 1
            continue

        if citekey in resolved:
            # Same citekey from multiple Zotero items — keep the higher-
            # ranked section (more-published wins). Warn either way so
            # Aaron can deduplicate in Zotero.
            prior = resolved[citekey]
            if _section_rank(section) > _section_rank(prior["section"]):
                warnings.append(
                    f"  ! {citekey} resolved from multiple Zotero items "
                    f"(prior section={prior['section']!r}, now {section!r}) "
                    f"— keeping {section!r} (more-published)"
                )
                resolved[citekey] = {"section": section, "title": title}
            elif _section_rank(section) < _section_rank(prior["section"]):
                warnings.append(
                    f"  ! {citekey} resolved from multiple Zotero items "
                    f"(prior section={prior['section']!r}, now {section!r}) "
                    f"— keeping {prior['section']!r} (more-published)"
                )
            # Equal rank → keep first, silent
            continue

        resolved[citekey] = {"section": section, "title": title}

    seen_citekeys = set(resolved.keys())

    # Build the new state section-by-section. We rebuild entries that come
    # from Zotero; proposal-only entries (no Zotero match) stay as-is.
    new_sections: dict[str, list[dict]] = {s: [] for s in KNOWN_SECTIONS}

    # Second pass: emit one entry per resolved citekey, in its best section,
    # merging any curated fields forward from the existing proposal.
    for citekey, info in resolved.items():
        section = info["section"]
        title = info["title"]

        if citekey in existing_idx:
            old_sect, old_i = existing_idx[citekey]
            old_entry = (proposal["sections"].get(old_sect) or [])[old_i]
            merged: dict = {
                "match_citekey": citekey,
                "latex_title": old_entry.get("latex_title") or title,
                "proposed_tags": ["cv:include", f"cv:section/{section}"],
            }
            for field in PRESERVE_FIELDS:
                if field in old_entry and old_entry[field] is not None:
                    merged[field] = old_entry[field]
            if not merged.get("latex_title"):
                merged["latex_title"] = title
            if old_sect != section:
                moved += 1
                print(f"  move {citekey}  {old_sect} → {section}", file=sys.stderr)
        else:
            added += 1
            merged = {
                "match_citekey": citekey,
                "latex_title": title,
                "latex_year": None,
                "proposed_tags": ["cv:include", f"cv:section/{section}"],
                "match_zotero_title": title,
                "match_score": 100,
            }
            print(f"  add  {citekey}  → {section}: {title[:60]}", file=sys.stderr)

        new_sections[section].append(merged)

    # Second pass: carry over any existing proposal entries whose citekey
    # doesn't appear in Zotero's cv:include set (e.g., stub entries for
    # papers not yet in Zotero, or items where the tag was dropped).
    # These get WARNED about but not auto-removed — safety.
    for sect_name, entries in (proposal.get("sections") or {}).items():
        if sect_name not in KNOWN_SECTIONS:
            # Unknown sections (legacy) — preserve verbatim, warn once
            warnings.append(
                f"  ! proposal contains unknown section {sect_name!r} "
                f"(not in KNOWN_SECTIONS) — preserving but not syncing"
            )
            continue
        for e in entries or []:
            ck = e.get("match_citekey")
            if not ck or ck == "SKIP":
                # Stub entry (no Zotero match) — carry forward
                new_sections[sect_name].append(e)
                continue
            if ck not in seen_citekeys:
                warnings.append(
                    f"  ! {ck} in proposal[{sect_name}] but no longer tagged "
                    f"cv:include in Zotero — kept in place"
                )
                new_sections[sect_name].append(e)

    # Write back
    proposal["sections"] = {s: new_sections[s] for s in KNOWN_SECTIONS}

    print(f"\nSummary: {added} added, {moved} moved, {skipped} skipped, "
          f"{len(warnings)} warnings", file=sys.stderr)
    for w in warnings:
        print(w, file=sys.stderr)

    if dry_run:
        print("\n(dry-run — cv-tag-proposal.yml NOT written)", file=sys.stderr)
        return 0

    if added == 0 and moved == 0 and not warnings:
        print("  (no changes — cv-tag-proposal.yml not rewritten)", file=sys.stderr)
        return 0

    save_proposal(proposal)
    print(f"\nWrote {PROPOSAL_PATH}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="Actually rewrite cv-tag-proposal.yml. Default is dry-run.")
    args = ap.parse_args()
    return sync(dry_run=not args.commit)


if __name__ == "__main__":
    # Need urllib.parse (used inside zotero_items_by_tag). Stdlib — free.
    import urllib.parse  # noqa: E402, F401
    sys.exit(main())
