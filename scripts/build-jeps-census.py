#!/usr/bin/env python3
"""Census every article in a Cambridge Core journal by its article type, so
preregistered reports can be counted as a share of what the journal publishes.

Why this and not something easier: Crossref carries no article-type field for
these journals at all (all 379 JEPS records have an empty `group-title`), and
full-text phrase search both over- and under-counts — it catches papers that
merely cite a preregistered report, and misses ones that never use the phrase.
Cambridge, however, tags every article on its issue pages with

    <h4 class="journal-article-listing-type">Preregistered Report</h4>

which is the journal's own label and settles the question at the source. Note that
this heading is a SECTION header — the articles it covers follow it, each carrying a
`part-link` anchor — so the type applies to every article until the next heading, not
to one article.

Note the label is "Preregistered Report", not "Registered Report". JEPS and APSR
both use the former; searching for the latter is what produced the false
positives this script replaces.

Writes one row per article to _data/<slug>_article_types.csv.

Usage:
    python3 scripts/build-jeps-census.py                # JEPS
    python3 scripts/build-jeps-census.py --journal apsr
"""

import argparse
import csv
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Cambridge 403s a default user-agent; a browser one is served normally.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

JOURNALS = {
    "jeps": {
        "slug": "journal-of-experimental-political-science",
        "name": "Journal of Experimental Political Science",
        # JEPS volume 1 = 2014. Verified against issue pages, not assumed.
        "vol1_year": 2014,
    },
    "apsr": {
        "slug": "american-political-science-review",
        "name": "American Political Science Review",
        # APSR volume 1 = 1906.
        "vol1_year": 1906,
    },
}

# Types that count as peer-reviewed research — the denominator. Deliberately
# generous: giving the format its best case means a small share cannot be
# dismissed as an artefact of a padded denominator.
RESEARCH_TYPES = {
    "research article", "research articles",
    "letter", "letters",
    "short report", "short reports",
    "replication study", "replication studies", "replications",
    "preregistered report", "preregistered reports",
    "registered report", "registered reports",
    "original article", "original articles",
}
PREREG_TYPES = {
    "preregistered report", "preregistered reports",
    "registered report", "registered reports",
}


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=90).read().decode("utf8", "ignore")
        except Exception as exc:
            if attempt == tries - 1:
                print(f"    FAILED {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(3)


def issue_urls(slug):
    html = fetch(f"https://www.cambridge.org/core/journals/{slug}/all-issues")
    if not html:
        sys.exit("could not fetch the all-issues page")
    hrefs = re.findall(rf"/core/journals/{slug}/issue/[A-Z0-9]+", html)
    # dict.fromkeys preserves first-seen order while de-duplicating
    return list(dict.fromkeys(hrefs))


def parse_issue(html):
    """Return (volume, issue, [(type, title, doi), ...])."""
    m = re.search(r"Volume\s+(\d+)\s*-\s*Issue\s+([0-9A-Za-z]+)", html)
    vol = int(m.group(1)) if m else None
    iss = m.group(2) if m else None

    articles = []
    # The type heading is a section header: every article between it and the next
    # heading has that type. Articles are the `part-link` anchors inside.
    parts = re.split(r'<h4 class="journal-article-listing-type[^"]*">', html)
    for chunk in parts[1:]:
        label = re.match(r"([^<]{1,80})</h4>", chunk)
        if not label:
            continue
        atype = re.sub(r"\s+", " ", label.group(1)).strip()
        dois = re.findall(r'data-doi="([^"]+)"', chunk)
        titles = re.findall(r'class="part-link"[^>]*>(.*?)</a>', chunk, re.S)
        clean = []
        for t in titles:
            t = re.sub(r"<[^>]+>", "", t)
            clean.append(re.sub(r"\s+", " ", t).strip())
        seen, uniq_dois = set(), []
        for d in dois:
            if d not in seen:
                seen.add(d)
                uniq_dois.append(d)
        for i in range(max(len(clean), len(uniq_dois))):
            articles.append((atype,
                             clean[i] if i < len(clean) else "",
                             uniq_dois[i] if i < len(uniq_dois) else ""))
    return vol, iss, articles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default="jeps", choices=sorted(JOURNALS))
    ap.add_argument("--since", type=int, default=0,
                    help="only report rates for years >= this")
    args = ap.parse_args()
    J = JOURNALS[args.journal]

    urls = issue_urls(J["slug"])
    print(f"{J['name']}: {len(urls)} issues found")

    rows = []
    for i, href in enumerate(urls, 1):
        html = fetch("https://www.cambridge.org" + href)
        if not html:
            continue
        vol, iss, arts = parse_issue(html)
        year = J["vol1_year"] + vol - 1 if vol else None
        for atype, title, doi in arts:
            rows.append({
                "journal": J["name"], "year": year, "volume": vol,
                "issue": iss, "type": atype, "title": title, "doi": doi,
            })
        print(f"  [{i}/{len(urls)}] vol {vol} iss {iss} ({year}) — {len(arts)} items")
        time.sleep(0.6)

    out = ROOT / "_data" / f"{args.journal}_article_types.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["journal", "year", "volume", "issue",
                                           "type", "title", "doi"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out.relative_to(ROOT)}: {len(rows)} articles")

    print("\nall type labels seen:")
    for label, n in Counter(r["type"] for r in rows).most_common():
        mark = "  <- research" if label.lower() in RESEARCH_TYPES else ""
        print(f"  {n:5d}  {label}{mark}")

    by_year = defaultdict(lambda: {"research": 0, "prereg": 0, "other": 0})
    for r in rows:
        if r["year"] is None:
            continue
        t = r["type"].lower()
        if t in PREREG_TYPES:
            by_year[r["year"]]["prereg"] += 1
        if t in RESEARCH_TYPES:
            by_year[r["year"]]["research"] += 1
        else:
            by_year[r["year"]]["other"] += 1

    print(f"\n{'year':6}{'research':>10}{'prereg':>8}{'share':>9}{'non-research':>14}")
    for y in sorted(by_year):
        if y < args.since:
            continue
        d = by_year[y]
        share = f"{100*d['prereg']/d['research']:.1f}%" if d["research"] else "-"
        print(f"{y:<6}{d['research']:>10}{d['prereg']:>8}{share:>9}{d['other']:>14}")


if __name__ == "__main__":
    main()
