#!/usr/bin/env python3
"""Dissemination pipeline: detect announceable things, draft copy, post them.

_data/dissemination.yml is the single source of truth — the queue, the drafts, and
the permanent record of what was shared where. There is no separate seen-file; an
item's `id` is the dedup key and its `status` drives everything, the same way
watch-letter-requests.py works.

Nothing reaches the public without an explicit `approve`. `scan` only ever appends
rows, so it is safe to run unattended.

Usage:
    disseminate.py seed                 # once, first: archive the back catalogue
    disseminate.py scan                 # detect new things
    disseminate.py list [--status new]
    disseminate.py add --kind tool --title … --url …
    disseminate.py reannounce <id> [--note "resurface"]

Later phases add: draft, approve, schedule, post, mark-posted, queue, run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pubs  # noqa: E402
import bluesky  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "_data" / "dissemination.yml"
CV_YAML = REPO / "_data" / "cv.yml"
POSTS_DIR = REPO / "posts"
SITE_URL = "https://aaronerlich.com"

KINDS = ["publication", "blog", "tool", "media", "talk", "award", "grant", "other"]

# Item-level statuses that are not derived from a round.
TERMINAL_STATUSES = {"new", "archived", "skipped"}


# ---------------------------------------------------------------- store

def _str_presenter(dumper, data):
    """Multi-line strings dump as literal blocks, so drafted copy stays readable."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(str, _str_presenter)

STORE_HEADER = """\
# Dissemination queue and archive. Generated and maintained by scripts/disseminate.py.
#
# This repo is PUBLIC. Unposted drafts in this file become visible on GitHub the
# moment you commit them — so commit this file *after* posting, not while drafts
# are pending. A killed draft otherwise lives in git history forever.
#
# Not served on aaronerlich.com: Quarto only copies _data files that a page
# actually references (submissions_public.json, via an OJS FileAttachment).
"""


def load_store() -> dict:
    if not STORE.exists():
        return {"meta": {"last_scan": None}, "items": []}
    data = yaml.safe_load(STORE.read_text(encoding="utf-8")) or {}
    data.setdefault("meta", {})
    data.setdefault("items", [])
    return data


def save_store(store: dict) -> None:
    for item in store["items"]:
        sync_status(item)
    body = yaml.dump(store, Dumper=_Dumper, sort_keys=False,
                     allow_unicode=True, default_flow_style=False, width=95)
    STORE.write_text(STORE_HEADER + body, encoding="utf-8")


def today() -> str:
    return dt.date.today().isoformat()


def find(store: dict, item_id: str) -> dict | None:
    for item in store["items"]:
        if item["id"] == item_id:
            return item
    return None


def current_round(item: dict) -> dict | None:
    rounds = item.get("rounds") or []
    return rounds[-1] if rounds else None


def open_round(item: dict, note: str = "") -> dict:
    """Start a fresh announcement round. It carries no copy until `draft` runs."""
    rounds = item.setdefault("rounds", [])
    rnd = {
        "n": len(rounds) + 1,
        "opened": today(),
        "status": "new",
        "note": note or ("launch" if not rounds else "resurface"),
        "drafts": {},
    }
    rounds.append(rnd)
    return rnd


def sync_status(item: dict) -> None:
    """Item status mirrors the newest round unless it is a terminal item state."""
    if item.get("status") in TERMINAL_STATUSES and not item.get("rounds"):
        return
    rnd = current_round(item)
    if rnd:
        item["status"] = rnd["status"]


def slug(text: str, maxlen: int = 48) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", str(text).lower()).strip("-")
    return s[:maxlen].rstrip("-")


# Bluesky's hard limit is 300 *graphemes*. Python has no stdlib grapheme
# segmentation, so approximate: normalize to NFC and drop combining marks, which
# is exact for Latin/Cyrillic and errs on the safe side for emoji sequences.
BLUESKY_LIMIT = 300
BLUESKY_SOFT = 280


def grapheme_len(text: str) -> int:
    return sum(1 for ch in unicodedata.normalize("NFC", text)
               if not unicodedata.combining(ch))


# ---------------------------------------------------------------- candidates

def _frontmatter(path: Path) -> dict:
    """Parse the YAML frontmatter block of a .qmd file."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _en(value):
    """cv.yml values are often {en: …, fr: …} translatable leaves."""
    if isinstance(value, dict):
        return value.get("en", "")
    return value or ""


_DATE_FORMATS = ["%B %d, %Y", "%b %d, %Y", "%B %Y", "%b %Y", "%Y-%m-%d", "%Y"]


def parse_loose_date(value) -> dt.date | None:
    """cv.yml presentation dates are free-form: 'October 10, 2025', 'Fall 2024'."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def candidates() -> list:
    """Every automatically-detectable announceable thing, as store-shaped dicts.

    Manual kinds (tool, other) are not produced here — they come from `add`.
    """
    out = []

    # --- publications, plus the media/awards hanging off them -------------
    for p in _pubs.iter_publications():
        ck = p["citekey"]
        out.append({
            "id": f"pub-{ck}",
            "kind": "publication",
            "title": p["title"],
            "url": p["url"],
            "blurb": p["abstract"][:400],
            "year": p["year"],
            "venue": p["venue"],
            "coauthors": p["coauthors"],
            "source": {"citekey": ck, "section": p["section"]},
        })
        for m in p["media"]:
            if not m["outlet"]:
                continue
            out.append({
                "id": f"media-{ck}-{slug(m['outlet'], 24)}",
                "kind": "media",
                "title": f"{m['outlet']} on “{p['title']}”",
                "url": m["url"],
                "blurb": "",
                "year": p["year"],
                "venue": m["outlet"],
                "coauthors": p["coauthors"],
                "source": {"citekey": ck, "outlet": m["outlet"], "paper": p["title"]},
            })
        for a in p["awards"]:
            out.append({
                "id": f"award-{ck}-{a['kind']}",
                "kind": "award",
                "title": a["text"] or a["kind"],
                "url": p["url"],
                "blurb": "",
                "year": p["year"],
                "venue": p["venue"],
                "coauthors": p["coauthors"],
                "source": {"citekey": ck, "award_kind": a["kind"], "paper": p["title"]},
            })

    # --- blog posts -------------------------------------------------------
    for qmd in sorted(POSTS_DIR.glob("*/index.qmd")):
        fm = _frontmatter(qmd)
        if fm.get("draft"):
            continue
        name = qmd.parent.name
        out.append({
            "id": f"post-{name}",
            "kind": "blog",
            "title": fm.get("title", name),
            "url": f"{SITE_URL}/posts/{name}/",
            "blurb": fm.get("description") or fm.get("description-meta") or "",
            "year": str(fm.get("date", ""))[:4],
            "venue": "",
            "coauthors": [],
            "source": {"path": str(qmd.relative_to(REPO))},
        })

    cv = yaml.safe_load(CV_YAML.read_text(encoding="utf-8")) or {}

    # --- software -> tool -------------------------------------------------
    for sw in cv.get("software") or []:
        name = sw.get("name") or ""
        if not name:
            continue
        out.append({
            "id": f"tool-{slug(name)}",
            "kind": "tool",
            "title": name,
            "url": sw.get("url", ""),
            "blurb": _en(sw.get("description")),
            "year": "",
            "venue": "",
            "coauthors": sw.get("coauthors") or [],
            "source": {"cv_section": "software"},
        })

    # --- grants -----------------------------------------------------------
    for g in cv.get("grants") or []:
        title = _en(g.get("title"))
        if not title:
            continue
        out.append({
            "id": f"grant-{slug(title)}-{g.get('year', '')}",
            "kind": "grant",
            "title": title,
            "url": "",
            "blurb": _en(g.get("notes")),
            "year": str(g.get("year") or ""),
            "venue": _en(g.get("agency")),
            "coauthors": [],
            "source": {"cv_section": "grants", "role": _en(g.get("role"))},
        })

    # --- talks (future-dated only reach the queue) ------------------------
    for pr in cv.get("presentations") or []:
        title = _en(pr.get("title"))
        if not title:
            continue
        when = parse_loose_date(pr.get("date"))
        out.append({
            "id": f"talk-{slug(title, 40)}-{when.isoformat() if when else 'undated'}",
            "kind": "talk",
            "title": title,
            "url": "",
            "blurb": "",
            "year": str(when.year) if when else "",
            "venue": _en(pr.get("venue")),
            "coauthors": [],
            "source": {"cv_section": "presentations", "date": str(pr.get("date", ""))},
            "_upcoming": bool(when and when >= dt.date.today()),
        })

    return _disambiguate(out)


def _disambiguate(cands: list) -> list:
    """Suffix colliding ids with -2, -3, …

    Collisions are real, not bugs: cv.yml holds two distinct 2015 grants both
    titled "Power of the Panopticon" from different agencies. Ordering within a
    source list is stable, so the suffix a given item gets is stable too.
    """
    seen = {}
    for c in cands:
        base = c["id"]
        n = seen.get(base, 0) + 1
        seen[base] = n
        if n > 1:
            c["id"] = f"{base}-{n}"
    return cands


# ---------------------------------------------------------------- commands

def cmd_seed(args) -> int:
    """Record everything currently known as `archived` so the back catalogue
    does not flood the queue. Only things appearing after this get `new`."""
    store = load_store()
    if store["items"] and not args.force:
        print(f"Store already has {len(store['items'])} items. "
              f"Use `scan` to pick up new ones, or --force to re-seed.", file=sys.stderr)
        return 1

    known = {i["id"] for i in store["items"]}
    added = 0
    for cand in candidates():
        cand.pop("_upcoming", None)
        if cand["id"] in known:
            continue
        cand.update({"added": today(), "status": "archived", "rounds": []})
        store["items"].append(cand)
        added += 1

    store["meta"]["last_scan"] = today()
    if args.dry_run:
        print(f"[dry-run] would seed {added} items as archived")
        return 0
    save_store(store)
    print(f"Seeded {added} items as archived → {STORE.relative_to(REPO)}")
    return 0


def cmd_scan(args) -> int:
    """Append unseen candidates as status: new. Idempotent, quiet, always 0."""
    store = load_store()
    known = {i["id"] for i in store["items"]}
    added = []
    for cand in candidates():
        upcoming = cand.pop("_upcoming", None)
        if cand["id"] in known:
            continue
        # Past talks are historical record, not announcements.
        status = "new"
        if cand["kind"] == "talk" and upcoming is False:
            status = "archived"
        cand.update({"added": today(), "status": status, "rounds": []})
        store["items"].append(cand)
        if status == "new":
            added.append(cand)

    store["meta"]["last_scan"] = today()
    if args.dry_run:
        for c in added:
            print(f"[dry-run] new  {c['kind']:<12} {c['id']}")
        print(f"[dry-run] {len(added)} new")
        return 0

    save_store(store)
    for c in added:
        print(f"new  {c['kind']:<12} {c['id']}  {c['title'][:60]}")
    if added:
        print(f"\n{len(added)} new. Draft them with:  disseminate.py draft --all-new")
    return 0


def _fmt_row(item: dict) -> str:
    rnd = current_round(item)
    rtag = f"r{rnd['n']}" if rnd else "  "
    return (f"{item['status']:<10} {rtag:<3} {item['kind']:<12} "
            f"{item['id'][:44]:<44} {item['title'][:44]}")


def cmd_list(args) -> int:
    store = load_store()
    items = store["items"]
    if args.status:
        items = [i for i in items if i["status"] == args.status]
    if args.kind:
        items = [i for i in items if i["kind"] == args.kind]
    if not items:
        print("(nothing matches)")
        return 0
    items = sorted(items, key=lambda i: (i.get("added", ""), i["id"]), reverse=True)
    for item in items:
        print(_fmt_row(item))
    print(f"\n{len(items)} item(s)")
    return 0


def cmd_add(args) -> int:
    store = load_store()
    item_id = args.id or f"{args.kind}-{slug(args.title)}"
    existing = find(store, item_id)
    if existing:
        if existing["status"] in ("archived", "skipped"):
            was = existing["status"]
            existing["status"] = "new"
            save_store(store)
            print(f"Reopened {item_id} (was {was}) → new")
            return 0
        print(f"{item_id} already exists with status {existing['status']}", file=sys.stderr)
        return 1

    store["items"].append({
        "id": item_id,
        "kind": args.kind,
        "title": args.title,
        "url": args.url or "",
        "blurb": args.blurb or "",
        "year": args.year or str(dt.date.today().year),
        "venue": args.venue or "",
        "coauthors": args.coauthor or [],
        "source": {"manual": True},
        "added": today(),
        "status": "new",
        "rounds": [],
    })
    save_store(store)
    print(f"Added {item_id} ({args.kind}) → new")
    return 0


EDITOR_TEMPLATE = """\
# Announcement copy for: {title}
# kind: {kind}   round: {n}   url: {url}
#
# Lines starting with # are ignored. Keep the two headings.
# Bluesky: {soft}-char soft ceiling ({hard}-grapheme hard limit); put the link last.
# LinkedIn: first two lines are the hook (it truncates around 210 chars).

## bluesky

{bluesky}

## linkedin

{linkedin}
"""


def parse_draft_text(text: str) -> dict:
    """Split the `## bluesky` / `## linkedin` editor format into a dict."""
    out, current, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("#") and not line.startswith("##"):
            continue
        m = re.match(r"^##\s+(bluesky|linkedin)\s*$", line.strip(), re.I)
        if m:
            if current:
                out[current] = "\n".join(buf).strip()
            current, buf = m.group(1).lower(), []
            continue
        if current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return {k: v for k, v in out.items() if v}


def _round_for_drafting(item: dict) -> dict:
    """The round that should receive copy, opening round 1 if there is none."""
    rnd = current_round(item)
    if rnd is None or rnd["status"] == "posted":
        rnd = open_round(item)
    return rnd


def _apply_drafts(item: dict, rnd: dict, drafts: dict) -> None:
    store_drafts = rnd.setdefault("drafts", {})
    if drafts.get("bluesky"):
        store_drafts["bluesky"] = {
            "text": drafts["bluesky"],
            "embed": {
                "uri": item.get("url", ""),
                "title": item.get("title", "")[:300],
                "description": (item.get("blurb") or item.get("venue") or "")[:1000],
            } if item.get("url") else None,
        }
        if store_drafts["bluesky"]["embed"] is None:
            del store_drafts["bluesky"]["embed"]
    if drafts.get("linkedin"):
        store_drafts["linkedin"] = {"text": drafts["linkedin"]}
    if store_drafts:
        rnd["status"] = "drafted"


def _print_drafts(item: dict, rnd: dict) -> None:
    print(f"\n{item['id']}  [{item['kind']}, round {rnd['n']}, {rnd['status']}]")
    print(f"  {item['title'][:70]}")
    bs = (rnd.get("drafts") or {}).get("bluesky")
    li = (rnd.get("drafts") or {}).get("linkedin")
    if bs:
        n = grapheme_len(bs["text"])
        flag = "  ⚠ OVER LIMIT" if n > BLUESKY_LIMIT else ("  ⚠ over soft ceiling" if n > BLUESKY_SOFT else "")
        print(f"\n--- bluesky ({n} graphemes){flag}\n{bs['text']}")
        if bs.get("embed"):
            print(f"    [card] {bs['embed']['title'][:60]} — {bs['embed']['uri']}")
    if li:
        print(f"\n--- linkedin ({len(li['text'])} chars)\n{li['text']}")
    if not bs and not li:
        print("  (no copy yet)")
    print()


def cmd_set_draft(args) -> int:
    """Write copy into an item. This is how Claude drafts: it composes the text
    with full repo context and calls this, rather than the script calling an API."""
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1

    drafts = {}
    if args.from_file:
        drafts = parse_draft_text(Path(args.from_file).read_text(encoding="utf-8"))
    if args.bluesky:
        drafts["bluesky"] = args.bluesky
    if args.linkedin:
        drafts["linkedin"] = args.linkedin
    if not drafts:
        print("Nothing to write — pass --bluesky/--linkedin or --from-file.", file=sys.stderr)
        return 1

    n = grapheme_len(drafts.get("bluesky", ""))
    if n > BLUESKY_LIMIT:
        print(f"Bluesky copy is {n} graphemes; the hard limit is {BLUESKY_LIMIT}.", file=sys.stderr)
        return 1

    rnd = _round_for_drafting(item)
    _apply_drafts(item, rnd, drafts)
    if args.dry_run:
        _print_drafts(item, rnd)
        print("[dry-run] not saved")
        return 0
    save_store(store)
    _print_drafts(item, rnd)
    print(f"Saved → round {rnd['n']} drafted.  Approve with:  disseminate.py approve {item['id']}")
    return 0


def _edit_in_editor(item: dict, rnd: dict) -> dict:
    existing = rnd.get("drafts") or {}
    body = EDITOR_TEMPLATE.format(
        title=item["title"], kind=item["kind"], n=rnd["n"],
        url=item.get("url", "(none)"), soft=BLUESKY_SOFT, hard=BLUESKY_LIMIT,
        bluesky=(existing.get("bluesky") or {}).get("text", ""),
        linkedin=(existing.get("linkedin") or {}).get("text", ""),
    )
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(body)
        path = fh.name
    try:
        subprocess.run([*editor.split(), path], check=True)
        return parse_draft_text(Path(path).read_text(encoding="utf-8"))
    finally:
        Path(path).unlink(missing_ok=True)


def cmd_draft(args) -> int:
    store = load_store()
    targets = []
    if args.all_new:
        targets = [i for i in store["items"] if i["status"] == "new"]
        if not targets:
            print("Nothing with status: new.")
            return 0
    else:
        item = find(store, args.id)
        if not item:
            print(f"No such item: {args.id}", file=sys.stderr)
            return 1
        targets = [item]

    for item in targets:
        rnd = _round_for_drafting(item)
        print(f"\n{item['id']} — {item['title'][:60]}  [{item['kind']}, round {rnd['n']}]")
        if item.get("url"):
            print(f"  {item['url']}")

        choice = "w" if args.self else ""
        while not choice:
            choice = input("  [w] write it myself   [c] have Claude draft it   "
                           "[s] skip   [q] stop: ").strip().lower()[:1]
            if choice not in ("w", "c", "s", "q"):
                choice = ""

        if choice == "q":
            break
        if choice == "s":
            continue
        if choice == "c":
            print("  → Ask Claude in this session to draft it, e.g.:\n"
                  f'      "draft the announcement for {item["id"]}"\n'
                  "    Claude writes the copy with full repo context and saves it with\n"
                  f"      disseminate.py set-draft {item['id']} --bluesky … --linkedin …")
            continue

        drafts = _edit_in_editor(item, rnd)
        if not drafts:
            print("  (nothing written — skipped)")
            continue
        n = grapheme_len(drafts.get("bluesky", ""))
        if n > BLUESKY_LIMIT:
            print(f"  Bluesky copy is {n} graphemes (limit {BLUESKY_LIMIT}) — not saved.",
                  file=sys.stderr)
            continue
        _apply_drafts(item, rnd, drafts)
        _print_drafts(item, rnd)

    if args.dry_run:
        print("[dry-run] not saved")
        return 0
    save_store(store)
    return 0


def cmd_show(args) -> int:
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1
    print(yaml.dump({k: v for k, v in item.items() if k != "rounds"},
                    Dumper=_Dumper, sort_keys=False, allow_unicode=True))
    for rnd in item.get("rounds") or []:
        _print_drafts(item, rnd)
        if rnd.get("posted"):
            print(f"  posted: {rnd['posted']}")
    return 0


def cmd_approve(args) -> int:
    store = load_store()
    if args.all_drafted:
        targets = [i for i in store["items"]
                   if (current_round(i) or {}).get("status") == "drafted"]
    else:
        item = find(store, args.id)
        if not item:
            print(f"No such item: {args.id}", file=sys.stderr)
            return 1
        targets = [item]

    approved = 0
    for item in targets:
        rnd = current_round(item)
        if not rnd or rnd["status"] != "drafted":
            print(f"{item['id']}: nothing drafted to approve "
                  f"(round status: {rnd['status'] if rnd else 'none'})", file=sys.stderr)
            continue
        _print_drafts(item, rnd)
        if not args.yes:
            if input("  Approve this copy? [y/N] ").strip().lower()[:1] != "y":
                print("  skipped")
                continue
        rnd["status"] = "approved"
        approved += 1

    if args.dry_run:
        print(f"[dry-run] would approve {approved}")
        return 0
    save_store(store)
    print(f"Approved {approved}. Schedule with:  disseminate.py schedule --all-approved …")
    return 0


# ---------------------------------------------------------------- scheduling

LOCAL_TZ = ZoneInfo("America/Toronto")
_EVERY_RE = re.compile(r"^(\d+)\s*([mhdw])$", re.I)


def parse_every(spec: str) -> dt.timedelta:
    m = _EVERY_RE.match(spec.strip())
    if not m:
        raise ValueError(f"--every wants forms like 90m, 6h, 2d, 1w (got {spec!r})")
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"m": dt.timedelta(minutes=n), "h": dt.timedelta(hours=n),
            "d": dt.timedelta(days=n), "w": dt.timedelta(weeks=n)}[unit]


def parse_when(text: str) -> dt.datetime:
    """Accept 'YYYY-MM-DD HH:MM' or a full ISO string; always return tz-aware.

    Times are stored with an explicit UTC offset so a DST change cannot silently
    move an already-scheduled post.
    """
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=LOCAL_TZ)
        except ValueError:
            continue
    when = dt.datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=LOCAL_TZ)


def cmd_schedule(args) -> int:
    store = load_store()
    if args.all_approved:
        targets = [i for i in store["items"]
                   if (current_round(i) or {}).get("status") == "approved"]
    else:
        item = find(store, args.id) if args.id else None
        if not item:
            print(f"No such item: {args.id}", file=sys.stderr)
            return 1
        targets = [item]
    if not targets:
        print("Nothing approved to schedule.")
        return 0

    if args.at:
        when = parse_when(args.at)
        if len(targets) > 1:
            print("--at schedules one item; use --starting/--every for a batch.",
                  file=sys.stderr)
            return 1
        slots = [when]
    else:
        if not args.starting:
            print("Give --at for one item, or --starting (+ --every) for a batch.",
                  file=sys.stderr)
            return 1
        step = parse_every(args.every) if args.every else dt.timedelta(days=1)
        cursor, slots = parse_when(args.starting), []
        for _ in targets:
            if args.weekdays_only:
                while cursor.weekday() >= 5:      # Sat/Sun
                    cursor += dt.timedelta(days=1)
            slots.append(cursor)
            cursor = cursor + step

    scheduled = 0
    for item, when in zip(targets, slots):
        rnd = current_round(item)
        if not rnd or rnd["status"] != "approved":
            print(f"{item['id']}: not approved (status "
                  f"{rnd['status'] if rnd else 'none'}) — skipped", file=sys.stderr)
            continue
        rnd["post_at"] = when.isoformat()
        rnd["status"] = "scheduled"
        scheduled += 1
        print(f"{when.strftime('%a %b %d  %H:%M %Z')}  {item['id']}")

    if args.dry_run:
        print(f"[dry-run] would schedule {scheduled}")
        return 0
    save_store(store)
    print(f"\nScheduled {scheduled}. Review with:  disseminate.py queue")
    return 0


def cmd_unschedule(args) -> int:
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1
    rnd = current_round(item)
    if not rnd or rnd["status"] != "scheduled":
        print(f"{args.id}: not scheduled.", file=sys.stderr)
        return 1
    rnd.pop("post_at", None)
    rnd["status"] = "approved"
    save_store(store)
    print(f"{args.id} returned to approved.")
    return 0


def due_rounds(store: dict, now: dt.datetime | None = None) -> list:
    """(item, round) pairs whose scheduled time has passed."""
    now = now or dt.datetime.now(LOCAL_TZ)
    out = []
    for item in store["items"]:
        rnd = current_round(item)
        if not rnd or rnd["status"] != "scheduled" or not rnd.get("post_at"):
            continue
        if parse_when(rnd["post_at"]) <= now:
            out.append((item, rnd))
    return out


def cmd_queue(args) -> int:
    store = load_store()
    rows = []
    for item in store["items"]:
        rnd = current_round(item)
        if rnd and rnd["status"] == "scheduled" and rnd.get("post_at"):
            rows.append((parse_when(rnd["post_at"]), item, rnd))
    if not rows:
        print("Nothing scheduled.")
        return 0
    now = dt.datetime.now(LOCAL_TZ)
    for when, item, rnd in sorted(rows, key=lambda r: r[0]):
        li = "li manual" if (rnd.get("drafts") or {}).get("linkedin") else "no li"
        bs = "bsky auto" if (rnd.get("drafts") or {}).get("bluesky") else "no bsky"
        due = " DUE" if when <= now else ""
        print(f"{when.strftime('%a %b %d  %H:%M')}  {item['id'][:40]:<40} "
              f"{item['kind']:<12} [{bs} + {li}]{due}")
    print(f"\n{len(rows)} scheduled")
    return 0


# ---------------------------------------------------------------- posting

def _clipboard(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return True
    except Exception:
        return False


def publish_round(item: dict, rnd: dict, dry_run: bool = False,
                  open_linkedin: bool = False) -> bool:
    """Post the Bluesky half and stage the LinkedIn half. Returns True on success."""
    drafts = rnd.get("drafts") or {}
    posted = rnd.setdefault("posted", {})

    bs = drafts.get("bluesky")
    if bs and "bluesky" not in posted:
        embed = bluesky.external_embed(**bs["embed"]) if bs.get("embed") else None
        if dry_run:
            print(json.dumps(bluesky.build_record(bs["text"], embed),
                             indent=2, ensure_ascii=False))
        else:
            try:
                result = bluesky.post(bs["text"], embed)
            except Exception as exc:
                print(f"{item['id']}: Bluesky post failed — {exc}", file=sys.stderr)
                return False
            posted["bluesky"] = {"url": result["url"], "uri": result["uri"],
                                 "at": dt.datetime.now(dt.timezone.utc)
                                        .isoformat(timespec="seconds")}
            print(f"  bluesky → {result['url']}")

    li = drafts.get("linkedin")
    if li and "linkedin" not in posted:
        if dry_run:
            print(f"  [dry-run] would copy {len(li['text'])} chars to the clipboard")
        else:
            copied = _clipboard(li["text"])
            posted["linkedin"] = {"pending_manual": True,
                                  "notified": today()}
            print(f"  linkedin → {'on your clipboard' if copied else 'copy it below'};"
                  f" paste it, then:\n"
                  f"      disseminate.py mark-posted {item['id']} --linkedin <url>")
            if not copied:
                print("\n" + li["text"] + "\n")
            if open_linkedin:
                subprocess.run(["open", "https://www.linkedin.com/feed/"], check=False)

    if not dry_run and not posted.get("linkedin", {}).get("pending_manual"):
        rnd["status"] = "posted"
    return True


def cmd_post(args) -> int:
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1
    rnd = current_round(item)
    if not rnd or rnd["status"] not in ("approved", "scheduled"):
        print(f"{args.id}: round is {rnd['status'] if rnd else 'missing'} — "
              f"only approved or scheduled rounds can be posted.", file=sys.stderr)
        return 1

    print(f"{item['id']} — {item['title'][:60]}")
    ok = publish_round(item, rnd, dry_run=args.dry_run, open_linkedin=args.open)
    if args.dry_run:
        print("[dry-run] nothing posted, nothing saved")
        return 0 if ok else 1
    save_store(store)
    return 0 if ok else 1


def cmd_mark_posted(args) -> int:
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1
    rnd = current_round(item)
    if not rnd:
        print(f"{args.id}: no round to close.", file=sys.stderr)
        return 1
    posted = rnd.setdefault("posted", {})
    if args.linkedin:
        posted["linkedin"] = {"url": args.linkedin,
                              "at": dt.datetime.now(dt.timezone.utc)
                                     .isoformat(timespec="seconds")}
    if args.bluesky:
        posted["bluesky"] = {"url": args.bluesky,
                             "at": dt.datetime.now(dt.timezone.utc)
                                    .isoformat(timespec="seconds")}
    still_pending = any(v.get("pending_manual") for v in posted.values()
                        if isinstance(v, dict))
    rnd["status"] = "posted" if posted and not still_pending else rnd["status"]
    save_store(store)
    print(f"{item['id']}: round {rnd['n']} → {rnd['status']}")
    return 0


def cmd_reannounce(args) -> int:
    store = load_store()
    item = find(store, args.id)
    if not item:
        print(f"No such item: {args.id}", file=sys.stderr)
        return 1
    rnd = current_round(item)
    if rnd and rnd["status"] != "posted":
        print(f"Round {rnd['n']} is still {rnd['status']} — finish or drop it first.",
              file=sys.stderr)
        return 1
    new = open_round(item, args.note)
    save_store(store)
    print(f"Opened round {new['n']} on {item['id']} — now draft it.")
    return 0


# ---------------------------------------------------------------- runner

LOG_PATH = Path.home() / "Library" / "Caches" / "dissemination.log"
LOCK_PATH = Path("/tmp/dissemination.lock")


def log(msg: str) -> None:
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass  # a logging failure must never take down the run


def acquire_lock() -> bool:
    """PID file with a staleness probe, same shape as watch-letter-requests.py."""
    if LOCK_PATH.exists():
        try:
            os.kill(int(LOCK_PATH.read_text().strip()), 0)
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            LOCK_PATH.unlink(missing_ok=True)
    LOCK_PATH.write_text(str(os.getpid()))
    return True


def notify(title: str, message: str) -> None:
    script = (f'display notification {json.dumps(message)} '
              f'with title {json.dumps(title)}')
    subprocess.run(["osascript", "-e", script], check=False,
                   capture_output=True, timeout=10)


def cmd_run(args) -> int:
    """One tick of the background job: scan at most daily, then fire due rounds.

    Always exits 0 — a per-item failure is logged, never propagated, so launchd
    never sees a nonzero status.
    """
    if not acquire_lock():
        return 0
    try:
        store = load_store()

        # 1. Scan, at most once a day: re-reading a 3 MB Zotero export on every
        #    15-minute tick would be 96 pointless parses.
        if store["meta"].get("last_scan") != today() and not args.no_scan:
            known = {i["id"] for i in store["items"]}
            added = []
            for cand in candidates():
                upcoming = cand.pop("_upcoming", None)
                if cand["id"] in known:
                    continue
                status = "archived" if (cand["kind"] == "talk" and upcoming is False) else "new"
                cand.update({"added": today(), "status": status, "rounds": []})
                store["items"].append(cand)
                if status == "new":
                    added.append(cand["id"])
            store["meta"]["last_scan"] = today()
            if added:
                log(f"scan: {len(added)} new — {', '.join(added[:5])}")
                notify("New to announce", f"{len(added)} item(s) detected")
            if not args.dry_run:
                save_store(store)

        # 2. Fire anything due.
        due = due_rounds(store)
        for item, rnd in due:
            log(f"firing {item['id']} (round {rnd['n']}, due {rnd['post_at']})")
            if args.dry_run:
                print(f"[dry-run] would fire {item['id']}")
                continue
            try:
                ok = publish_round(item, rnd)
            except Exception as exc:
                log(f"  FAIL {item['id']}: {exc}")
                continue
            if not ok:
                continue
            save_store(store)
            pending = (rnd.get("posted") or {}).get("linkedin", {}).get("pending_manual")
            if pending:
                notify("LinkedIn copy on your clipboard", item["title"][:80])

        # 3. Re-nudge LinkedIn halves still waiting — once a day, not every tick.
        for item in store["items"]:
            rnd = current_round(item)
            li = ((rnd or {}).get("posted") or {}).get("linkedin") or {}
            if li.get("pending_manual") and li.get("notified") != today():
                if args.dry_run:
                    print(f"[dry-run] would re-notify {item['id']}")
                    continue
                _clipboard((rnd["drafts"]["linkedin"])["text"])
                notify("Still to paste on LinkedIn", item["title"][:80])
                li["notified"] = today()
                save_store(store)
                log(f"re-notified {item['id']} (LinkedIn still pending)")

        if args.dry_run:
            print(f"[dry-run] {len(due)} due")
        return 0
    finally:
        LOCK_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true",
                   help="print what would change; touch nothing")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="archive the existing back catalogue (run once)")
    s.add_argument("--force", action="store_true", help="re-seed a non-empty store")
    s.set_defaults(func=cmd_seed)

    s = sub.add_parser("scan", help="append newly-detected things as status: new")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("list", help="show the store")
    s.add_argument("--status")
    s.add_argument("--kind", choices=KINDS)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("add", help="add a manual item (the only path for tool/other)")
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--title", required=True)
    s.add_argument("--url", default="")
    s.add_argument("--blurb", default="")
    s.add_argument("--venue", default="")
    s.add_argument("--year", default="")
    s.add_argument("--coauthor", action="append", default=[])
    s.add_argument("--id", help="override the generated id, or reopen an archived one")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("reannounce", help="open a new round on an already-posted item")
    s.add_argument("id")
    s.add_argument("--note", default="resurface")
    s.set_defaults(func=cmd_reannounce)

    s = sub.add_parser("draft", help="write announcement copy for an item")
    s.add_argument("id", nargs="?")
    s.add_argument("--self", action="store_true", help="skip the prompt; open $EDITOR")
    s.add_argument("--all-new", action="store_true", help="walk every status: new item")
    s.set_defaults(func=cmd_draft)

    s = sub.add_parser("set-draft", help="write copy directly (how Claude drafts)")
    s.add_argument("id")
    s.add_argument("--bluesky")
    s.add_argument("--linkedin")
    s.add_argument("--from-file", help="a file in the ## bluesky / ## linkedin format")
    s.set_defaults(func=cmd_set_draft)

    s = sub.add_parser("show", help="print an item and its rounds")
    s.add_argument("id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("approve", help="mark drafted copy as approved")
    s.add_argument("id", nargs="?")
    s.add_argument("--all-drafted", action="store_true")
    s.add_argument("--yes", "-y", action="store_true", help="skip the confirmation")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("schedule", help="set when approved copy should go out")
    s.add_argument("id", nargs="?")
    s.add_argument("--at", help='one item: "2026-08-13 09:30"')
    s.add_argument("--all-approved", action="store_true")
    s.add_argument("--starting", help='first slot: "2026-08-13 09:30"')
    s.add_argument("--every", default="1d", help="spacing: 90m, 6h, 2d, 1w")
    s.add_argument("--weekdays-only", action="store_true")
    s.set_defaults(func=cmd_schedule)

    s = sub.add_parser("unschedule", help="return a scheduled round to approved")
    s.add_argument("id")
    s.set_defaults(func=cmd_unschedule)

    s = sub.add_parser("queue", help="show the rollout in time order")
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("post", help="post an approved/scheduled round now")
    s.add_argument("id")
    s.add_argument("--open", action="store_true", help="also open the LinkedIn feed")
    s.set_defaults(func=cmd_post)

    s = sub.add_parser("mark-posted", help="record a manually-pasted post URL")
    s.add_argument("id")
    s.add_argument("--linkedin")
    s.add_argument("--bluesky")
    s.set_defaults(func=cmd_mark_posted)

    s = sub.add_parser("run", help="one tick of the background job (launchd entry point)")
    s.add_argument("--once", action="store_true", help="accepted for symmetry; always one tick")
    s.add_argument("--no-scan", action="store_true", help="fire due rounds only")
    s.set_defaults(func=cmd_run)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
