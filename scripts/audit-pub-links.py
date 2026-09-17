#!/usr/bin/env python3
"""Audit every CV publication link and propose open-access replacements.

READ-ONLY with respect to the CV: this writes only its own two artifacts,
`_data/link-audit.md` (for you to read) and `_data/link-fixes.yml` (for
scripts/apply-link-fixes.py to act on, once you flip `approved: true`).
Nothing reaches Zotero from here.

Why the fix lands in Zotero rather than in this repo: scripts/build-cv.py
resolves a publication's link as `item["URL"] or https://doi.org/<DOI>` — the
Zotero URL field wins over the DOI. scripts/disseminate.py reads the same
records, so a bad URL left in Zotero keeps being broadcast to social even after
the CV is patched. Clearing a stale URL is therefore often the whole fix: the
renderer falls through to the DOI, which is the durable link.

Link policy: one link per publication — the open-access version when a free one
exists, the publisher/DOI otherwise.

Usage:
    python3 scripts/audit-pub-links.py              # audit, write both artifacts
    python3 scripts/audit-pub-links.py --refresh    # bust the OpenAlex cache
    python3 scripts/audit-pub-links.py --offline    # no network; cache only
    python3 scripts/audit-pub-links.py --verify     # did the BBT re-export land?
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _linkcheck as lc  # noqa: E402
import _pubs  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
AUDIT_MD = REPO / "_data" / "link-audit.md"
FIXES_YML = REPO / "_data" / "link-fixes.yml"
OA_CACHE = REPO / "_generated" / "oa-cache.json"
OVERRIDES_YML = REPO / "_data" / "link-overrides.yml"

# Aaron's OpenAlex author record (McGill). Preprint matching is restricted to
# this author: OpenAlex free-text title search returns other people's papers.
OPENALEX_AUTHOR = "A5079669887"
OPENALEX = "https://api.openalex.org"
WORK_SELECT = "doi,title,open_access,best_oa_location,locations,primary_location,type"

RECHECK_DAYS = 30
SEVERITY = ["malformed", "dead", "redirect_login", "botwall", "unknown",
            "down", "oa_upgrade", "ok"]


# ---------- OpenAlex ----------

def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": lc.UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class OpenAlex:
    """Thin cached client. The cache makes reruns cheap and --offline possible."""

    def __init__(self, refresh: bool = False, offline: bool = False):
        self.refresh, self.offline = refresh, offline
        self.cache = {}
        if OA_CACHE.is_file() and not refresh:
            try:
                self.cache = json.loads(OA_CACHE.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        self.dirty = False

    def save(self):
        if self.dirty:
            OA_CACHE.parent.mkdir(parents=True, exist_ok=True)
            OA_CACHE.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")

    def by_doi(self, doi: str) -> dict | None:
        key = f"doi:{doi.lower()}"
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return None
        url = f"{OPENALEX}/works/doi:{urllib.parse.quote(doi, safe='/')}?select={WORK_SELECT}"
        try:
            work = _get_json(url)
        except Exception:
            work = None
        self.cache[key] = work
        self.dirty = True
        time.sleep(0.12)  # be polite to a free API
        return work

    def author_works(self) -> list:
        key = f"author:{OPENALEX_AUTHOR}"
        if key in self.cache:
            return self.cache[key]
        if self.offline:
            return []
        works, cursor = [], "*"
        try:
            while cursor:
                url = (f"{OPENALEX}/works?filter=author.id:{OPENALEX_AUTHOR}"
                       f"&select={WORK_SELECT}&per-page=200&cursor={cursor}")
                page = _get_json(url, timeout=40)
                works.extend(page.get("results") or [])
                cursor = (page.get("meta") or {}).get("next_cursor")
                time.sleep(0.12)
        except Exception:
            pass
        self.cache[key] = works
        self.dirty = True
        return works


# ---------- title matching ----------

def norm_title(s: str) -> set:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return set(re.findall(r"[a-z0-9]+", s))


def title_match(a: str, b: str, threshold: float = 0.9) -> bool:
    ta, tb = norm_title(a), norm_title(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / max(1, min(len(ta), len(tb))) >= threshold


# ---------- OA extraction ----------

VERSION_RANK = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2}


def validate_proposed(url: str) -> str:
    """Return url if it is well-formed and actually reachable, else "".

    OpenAlex location metadata comes from repositories and is sometimes junk —
    several of Aaron's records carry a landing_page_url of
    "https://orcid.org/0000-0002-...>," (an ORCID field bleeding into the URL).
    Proposing that would replace a working paywalled link with a broken one, so
    every candidate is checked before it reaches the review table.
    """
    if not url or lc.malformed_reason(url):
        return ""
    if "orcid.org" in url:  # never a copy of the paper
        return ""
    res = lc.check_url(url)
    # botwall is fine: the target works in a browser. dead/login/malformed is not.
    return url if res["status"] in ("ok", "botwall") else ""


def best_oa(work: dict | None) -> dict | None:
    """Pick one OA location. Landing pages beat raw PDFs (they survive longer and
    give the reader the citation); published beats accepted beats submitted."""
    if not work:
        return None
    oa = work.get("open_access") or {}
    if not oa.get("is_oa"):
        return None
    cands = [l for l in (work.get("locations") or []) if l.get("is_oa")]
    best = work.get("best_oa_location")
    if best and best not in cands:
        cands.append(best)
    if not cands:
        return {"url": oa.get("oa_url"), "status": oa.get("oa_status"), "host": ""}
    cands.sort(key=lambda l: VERSION_RANK.get(l.get("version"), 9))
    top = cands[0]
    url = top.get("landing_page_url") or top.get("pdf_url") or oa.get("oa_url")
    return {"url": url, "status": oa.get("oa_status"),
            "host": ((top.get("source") or {}).get("display_name") or "")}


def repo_candidates(work: dict | None) -> list:
    """Non-OA-flagged repository copies (e.g. eScholarship@McGill). Worth showing
    a human even though OpenAlex doesn't call them open access."""
    out = []
    for l in (work or {}).get("locations") or []:
        src = (l.get("source") or {}).get("display_name") or ""
        lp = l.get("landing_page_url") or ""
        if l.get("is_oa") or not lp:
            continue
        if any(k in src.lower() for k in ("escholarship", "repository", "eprints",
                                          "hal", "zenodo", "osf", "arxiv")):
            out.append({"url": lp, "host": src})
    return out


# ---------- the roster ----------

DOI_IN_URL = re.compile(r"(10\.\d{4,9}/[^\s?&#]+)")


def effective_url(item: dict) -> tuple[str, str]:
    """Reproduce build-cv.py:293-299 exactly. Auditing anything else audits a
    fiction: the DOI normalization and the URL-wins-over-DOI rule both matter."""
    doi = item.get("DOI") or ""
    doi = re.sub(r"^\s*(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi,
                 flags=re.IGNORECASE).strip()
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    return url, doi


def doi_from_url(url: str) -> str:
    """Recover a DOI embedded in a publisher or proxy URL when the Zotero DOI
    field is empty — a library-proxy link like
    www-tandfonline-com.proxy3.library.mcgill.ca/doi/abs/10.1080/... carries the
    DOI that should replace it."""
    m = DOI_IN_URL.search(url or "")
    return m.group(1).rstrip(".,;") if m else ""


def load_overrides() -> dict:
    """Hand-curated links for items no API can resolve (newsletters, chapters,
    institutional PDFs). Each entry needs a `source` note saying how it was
    verified, so a future reader can tell curation from guesswork."""
    if not OVERRIDES_YML.is_file():
        return {}
    data = yaml.safe_load(OVERRIDES_YML.read_text(encoding="utf-8")) or {}
    return data.get("overrides") or {}


def load_roster() -> list:
    zot = _pubs.load_zotero()
    proposal = _pubs.load_proposal()
    rows = []
    for section, entries in (proposal.get("sections") or {}).items():
        for entry in entries or []:
            ck = entry.get("match_citekey")
            if not ck or ck == "SKIP":
                continue
            item = zot.get(ck)
            if item is None:
                continue  # stub entries render from latex_url; out of scope here
            url, doi = effective_url(item)
            rows.append({
                "citekey": ck,
                "section": section,
                "title": (item.get("title") or entry.get("latex_title") or "").strip(),
                "zotero_url": item.get("URL") or "",
                "doi": doi,
                "doi_in_url": doi_from_url(url) if not doi else "",
                "effective_url": url,
            })
    return rows


# ---------- the decision ladder ----------

def decide(row: dict, check: dict, work: dict | None) -> dict:
    """One link per publication: OA when a free copy exists, DOI/publisher when not.

    Returns action (clear_url | set_url | none), proposed_url and a reason.
    Clearing is the quiet workhorse: with no URL the renderer emits the DOI.
    """
    oa = best_oa(work)
    doi_url = f"https://doi.org/{row['doi']}" if row["doi"] else ""
    override = row.get("override") or {}
    status = check["status"]
    legacy = bool(row["zotero_url"]) and lc.is_legacy_host(row["zotero_url"])

    def oa_is_elsewhere():
        return bool(oa and oa["url"] and oa["url"].rstrip("/") != row["effective_url"].rstrip("/"))

    # 0. A curated link beats anything derived, but only where the current link
    # is unusable — an override must never silently override a working OA link.
    if override.get("url") and (status in lc.BROKEN or status == "none"):
        return _fix(row, "set_url", override["url"], "curated_link", oa,
                    override.get("source", "hand-verified"))

    # 1. Malformed: the reader never even reaches the publisher.
    if status == "malformed":
        if row["doi"]:
            return _fix(row, "clear_url", "", "malformed_url", oa,
                        f"falls through to {doi_url}")
        if oa and oa["url"]:
            return _fix(row, "set_url", oa["url"], "malformed_url", oa, "")
        return _fix(row, "none", "", "malformed_needs_manual", oa, "no DOI and no OA copy")

    # 2/3. Actually broken, or a URL form the publisher has abandoned.
    if status in ("dead", "redirect_login") or legacy:
        why = {"dead": "dead_link", "redirect_login": "login_wall"}.get(status, "legacy_host")
        if oa and oa["url"]:
            return _fix(row, "set_url", oa["url"], f"oa_replaces_{why}", oa, "")
        if row["doi"]:
            return _fix(row, "clear_url", "", f"doi_replaces_{why}", oa,
                        f"falls through to {doi_url}")
        if row.get("doi_in_url"):
            # The dead link carries its own DOI; promote it rather than dropping
            # the publication to unlinked.
            return _fix(row, "set_url", f"https://doi.org/{row['doi_in_url']}",
                        f"doi_replaces_{why}", oa, "DOI recovered from the old URL")
        return _fix(row, "none", "", f"{why}_needs_manual", oa, "no DOI and no OA copy")

    # 5. Nothing to link at all.
    if not row["effective_url"]:
        if oa and oa["url"]:
            return _fix(row, "set_url", oa["url"], "oa_fills_missing_link", oa, "")
        cands = repo_candidates(work)
        if cands:
            return _fix(row, "set_url", cands[0]["url"], "candidate_needs_judgement", oa,
                        f"repository copy at {cands[0]['host']}, not flagged OA")
        return _fix(row, "none", "", "no_link_found", oa, "no URL, DOI or OA copy")

    # 4. Working, but paywalled while a free copy exists. Discretionary.
    if oa_is_elsewhere() and status in ("ok", "botwall"):
        if row.get("section") == "working-paper":
            # The CV lists these *as* working papers; pointing the line at the
            # published version would misdescribe it.
            return _fix(row, "none", "", "ok", oa, "working paper — link left as-is")
        return _fix(row, "set_url", oa["url"], "oa_upgrade", oa, "")

    return _fix(row, "none", "", "ok", oa, check.get("note", ""))


def _fix(row, action, url, reason, oa, note):
    if action == "set_url":
        checked = validate_proposed(url)
        if not checked:
            # The replacement is unusable. Fall back to the DOI if there is one,
            # otherwise leave the item alone rather than break a working link.
            if row.get("doi") and row.get("zotero_url"):
                action, url = "clear_url", ""
                reason, note = f"{reason}_fallback_doi", "OA candidate was unreachable"
            else:
                action, url = "none", ""
                reason, note = f"{reason}_unusable", "OA candidate was unreachable"
        else:
            url = checked
    return {"action": action, "proposed_url": url, "reason": reason,
            "oa_status": (oa or {}).get("status") or "closed",
            "oa_host": (oa or {}).get("host") or "", "note": note}


# ---------- artifacts ----------

def load_existing_fixes() -> dict:
    """Carry approvals and applied_at across reruns — the audit must never quietly
    un-approve something Aaron has already signed off."""
    if not FIXES_YML.is_file():
        return {}
    data = yaml.safe_load(FIXES_YML.read_text(encoding="utf-8")) or {}
    return {f["citekey"]: f for f in (data.get("fixes") or []) if f.get("citekey")}


def write_fixes(rows: list, prior: dict):
    fixes = []
    for r in rows:
        if r["action"] == "none" and r["reason"] == "ok":
            continue
        old = prior.get(r["citekey"], {})
        # An approval applies to a specific proposal; if the proposal changed,
        # the approval is no longer meaningful.
        same = (old.get("proposed_url", "") == r["proposed_url"]
                and old.get("action") == r["action"])
        fixes.append({
            "citekey": r["citekey"],
            "title": r["title"][:110],
            "action": r["action"],
            "current_url": r["effective_url"],
            "proposed_url": r["proposed_url"],
            "reason": r["reason"],
            "oa_status": r["oa_status"],
            "status": r["status"],
            "note": r["note"],
            "approved": bool(old.get("approved")) if same else False,
            "applied_at": old.get("applied_at") if same else None,
        })
    FIXES_YML.write_text(
        "# Proposed CV link fixes. Generated by scripts/audit-pub-links.py.\n"
        "# Nothing is written to Zotero until you set `approved: true` here and\n"
        "# run scripts/apply-link-fixes.py --commit.\n"
        "#   clear_url = delete the Zotero URL so the CV falls through to the DOI\n"
        "#   set_url   = replace the Zotero URL with proposed_url\n"
        "#   none      = recorded so the audit stops re-raising it; no write\n"
        + yaml.dump({"generated": date.today().isoformat(), "fixes": fixes},
                    sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8")
    return fixes


def write_audit_md(rows: list):
    rank = {s: i for i, s in enumerate(SEVERITY)}
    rows = sorted(rows, key=lambda r: (rank.get(r["reason"].split("_")[0], 50),
                                       rank.get(r["status"], 50), r["citekey"]))
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    out = [
        "# CV publication link audit",
        "",
        f"Generated {date.today().isoformat()} by `scripts/audit-pub-links.py`. "
        "Read-only; approvals live in `_data/link-fixes.yml`.",
        "",
        "Status counts: " + ", ".join(f"**{k}** {v}" for k, v in sorted(counts.items())),
        "",
        "`botwall` means the publisher blocks scripted requests but the DOI resolves — "
        "those links work in a browser and are **not** broken.",
        "",
        "| citekey | title | current link | status | proposed | OA | reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        prop = r["proposed_url"] or ("*(clear — falls through to DOI)*"
                                     if r["action"] == "clear_url" else "—")
        cur = r["effective_url"] or "*(none — renders unlinked)*"
        out.append("| `{}` | {} | {} | {} | {} | {} | {} |".format(
            r["citekey"], r["title"][:60].replace("|", "/"), cur[:70].replace("|", "/"),
            r["status"], prop[:70].replace("|", "/"), r["oa_status"], r["reason"]))
    AUDIT_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------- verify ----------

def verify(prior: dict) -> int:
    """After apply-link-fixes.py + a Better BibTeX re-export, confirm the new URLs
    actually reached My Library.json. This is the step that catches a forgotten
    re-export before it silently no-ops the rebuild."""
    zot = _pubs.load_zotero()
    applied = [f for f in prior.values() if f.get("applied_at")]
    if not applied:
        print("No fixes marked applied yet — nothing to verify.")
        return 0
    bad = 0
    for f in applied:
        item = zot.get(f["citekey"])
        if item is None:
            print(f"  ? {f['citekey']}: not in the export")
            bad += 1
            continue
        actual = item.get("URL") or ""
        want = f["proposed_url"] or ""
        if actual.rstrip("/") == want.rstrip("/"):
            print(f"  ok {f['citekey']}")
        else:
            print(f"  FAIL {f['citekey']}: export still has {actual!r}, expected {want!r}")
            bad += 1
    if bad:
        print(f"\n{bad} item(s) not reflected in My Library.json.\n"
              "Zotero: sync down, then File > Export Library > Better BibTeX CSL JSON,\n"
              "overwriting ~/Dropbox/research_projects/My Library.json. Then rerun --verify.")
    else:
        print(f"\nAll {len(applied)} applied fix(es) present in the export.")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="bust the OpenAlex cache")
    ap.add_argument("--offline", action="store_true", help="cache only, no network")
    ap.add_argument("--verify", action="store_true",
                    help="check applied fixes reached My Library.json")
    args = ap.parse_args()

    prior = load_existing_fixes()
    if args.verify:
        return verify(prior)

    roster = load_roster()
    overrides = load_overrides()
    for row in roster:
        row["override"] = overrides.get(row["citekey"]) or {}
    oa_client = OpenAlex(refresh=args.refresh, offline=args.offline)
    author_works = None
    print(f"Auditing {len(roster)} publications…")

    for i, row in enumerate(roster, 1):
        check = ({"status": "none", "code": None, "note": ""} if not row["effective_url"]
                 else lc.check_url(row["effective_url"]))
        # Never call a bot-walled publisher dead: ask Crossref whether the work
        # still resolves, and report that instead.
        if check["status"] == "botwall" and row["doi"]:
            check["note"] = ("DOI resolves — works in a browser"
                             if lc.doi_resolves(row["doi"]) else "DOI does NOT resolve")

        work = oa_client.by_doi(row["doi"]) if row["doi"] else None
        if work is None and not row["doi"]:
            if author_works is None:
                author_works = oa_client.author_works()
            work = next((w for w in author_works
                         if title_match(row["title"], w.get("title") or "")), None)

        row["status"] = check["status"]
        row.update(decide(row, check, work))
        if row["note"] and check.get("note") and row["reason"] == "ok":
            row["note"] = check["note"]
        print(f"  [{i:>2}/{len(roster)}] {row['status']:<14} {row['reason']:<28} {row['citekey']}")

    oa_client.save()
    fixes = write_fixes(roster, prior)
    write_audit_md(roster)

    broken = [r for r in roster if r["status"] in lc.BROKEN]
    print(f"\n{len(broken)} broken, {len(fixes)} proposed change(s).")
    print(f"Review {AUDIT_MD.relative_to(REPO)}, approve in {FIXES_YML.relative_to(REPO)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
