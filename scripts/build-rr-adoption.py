#!/usr/bin/env python3
"""Build _data/rr_adoption.json — when the top political science journals have
offered results-blind review, in any form.

Two inputs, joined by journal title:

1. `_data/sjr_ps_top60.csv` — the ranking. SCImago Journal Rank, 2025, restricted
   to journals and hand-curated to political science proper. Scimago splits the
   discipline across two categories ("Political Science and International
   Relations" and "Sociology and Political Science"), and the second is a
   grab-bag that also holds Administrative Science Quarterly, JPSP and ASR — so
   neither category alone is usable. The pool is the union of both, curated down
   to political science (general, IR, comparative, behaviour, theory, area
   studies), excluding management, psychology, sociology, public administration
   and policy. Regenerate from the sjrdata package
   (github.com/ikashnitsky/sjrdata), filtering year == 2025.

   SJR is a citation metric, not a scholarly evaluation of journals. It is used
   here only to order the field. The post says so explicitly.

2. HISTORY below — hand-coded. A journal gets a list of `periods` because
   offering results-blind review is not a one-way door: journals have taken it
   up, dropped it, and in one case taken it up again.

   Three kinds of period:
     track       — a standing registered-reports option, open-ended if current
     pilot       — a time-limited experiment the journal ran alone
     competition — participation in the Election Research Preacceptance
                   Competition, a one-off cross-journal initiative

   Journals absent from HISTORY were checked and have no results-blind history;
   absence means checked-and-absent, not unchecked.

Dating these is harder than it sounds, because journals rarely announce them
with a date. The most reliable instrument turned out to be archived snapshots of
COS's own registry page (cos.io/rr), which was server-rendered for most of its
life and is captured roughly monthly back to Feb 2017 — often bracketing an
adoption to within days. Note that the registry lags reality in both directions:
it listed the Journal of Politics two and a half years late, while Wiley's own
LSQ guidelines lagged the registry by over a year.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANKS = ROOT / "_data" / "sjr_ps_top60.csv"
OUT = ROOT / "_data" / "rr_adoption.json"

# Data current as of this date; open-ended periods are drawn to here.
AS_OF = "2026-08-27"

COS = "https://www.cos.io/initiatives/registered-reports"

# The Election Research Preacceptance Competition: nine political science
# journals agreed to review results-blind submissions built on preregistered
# analyses of the 2016 ANES. Announced 18-19 Aug 2016; preregistration closed
# when the ANES 2016 data were released in Mar 2017. Manuscripts arising from it
# were reviewed after that, but no new entrants could join.
ERPC = {
    "start": "2016-08",
    "end": "2017-03",
    "kind": "competition",
    "label": "ERPC",
    "evidence": "announcement",
    "note": (
        "Election Research Preacceptance Competition — a one-off, organised by "
        "Arthur Lupia and Brendan Nyhan and funded by the Arnold Foundation, in "
        "which nine journals agreed to review results-blind submissions using "
        "preregistered analyses of the 2016 ANES. Announced 18 Aug 2016; "
        "preregistration closed with the ANES data release in Mar 2017. It did "
        "not become standing policy at any participating journal."
    ),
    "source": "https://www.washingtonpost.com/news/monkey-cage/wp/2016/08/19/new-political-science-initiative-calls-for-evaluating-research-before-knowing-the-results/",
    "confidence": "high",
}

HISTORY = {
    # --- ERPC participants that never adopted a standing track -------------
    "American Journal of Political Science": [ERPC],
    "Political Analysis": [ERPC],
    "Political Behavior": [ERPC],
    "Political Science Research and Methods": [ERPC],
    "Public Opinion Quarterly": [ERPC],
    # (American Politics Research, Political Science Quarterly and State
    # Politics & Policy Quarterly also took part but fall outside the top 60.)

    # --- the one journal that tried it, stopped, and came back -------------
    "American Political Science Review": [
        ERPC,
        {
            "start": "2025-08",
            "end": None,
            "kind": "track",
            "evidence": "announcement",
            "note": (
                "Registered Reports launched as one of five new publication "
                "tracks — nine years after APSR's first, brief experiment with "
                "results-blind review in the ERPC."
            ),
            "source": "https://politicalsciencenow.com/new-tracks-at-the-apsr/",
            "confidence": "high",
        },
    ],

    # --- the journal that adopted and reversed ----------------------------
    "Comparative Political Studies": [
        {
            "start": "2014-11",
            "end": "2016-11",
            "kind": "pilot",
            "evidence": "pilot",
            "note": (
                "A results-free review pilot, not a standing track: an open "
                "call, 19 submissions, three papers in a special issue "
                "(49(13), Nov 2016). The editors did not continue it. Current "
                "CPS guidelines mention only optional anonymised pre-analysis "
                "plans."
            ),
            "source": "https://journals.sagepub.com/doi/10.1177/0010414016655539",
            "confidence": "high",
        }
    ],

    # --- standing tracks, in order of adoption ----------------------------
    "Journal of Experimental Political Science": [
        {
            "start": "2016-08",
            "end": None,
            "kind": "track",
            "evidence": "editorial",
            "note": (
                "The first standing registered-reports track in political "
                "science, announced in Eric Dickson's incoming-editor "
                "editorial 'Continuity and Change at the Journal of "
                "Experimental Political Science' (online 1 Aug 2016). JEPS is "
                "on COS's registry from its earliest archived capture."
            ),
            "source": "https://doi.org/10.1017/xps.2016.1",
            "confidence": "high",
        }
    ],
    "Research and Politics": [
        {
            "start": "2019-02",
            "uncertain_from": "2019-01",
            "end": None,
            "kind": "track",
            "evidence": "registry-bracket",
            "note": (
                "Absent from COS's registry on 3 Jan 2019 and listed on 3 Feb "
                "2019, so adoption falls in that month."
            ),
            "source": COS,
            "confidence": "medium-high",
        }
    ],
    "Legislative Studies Quarterly": [
        {
            "start": "2020-11",
            "end": None,
            "kind": "track",
            "evidence": "registry-bracket",
            "note": (
                "Absent from COS's registry on 11 Nov 2020 and listed by 15 "
                "Nov 2020 — a four-day window. Wiley's own LSQ author "
                "guidelines still did not mention registered reports a year "
                "later, in Nov 2021."
            ),
            "source": COS,
            "confidence": "high",
        }
    ],
    "Journal of Politics": [
        {
            "start": "2023-01",
            "end": None,
            "kind": "track",
            "evidence": "announcement",
            "note": (
                "Opened as a trial running 1 Jan – 30 Sep 2023, then retained "
                "as a standard article format. COS's registry did not list it "
                "until Aug 2025, two and a half years late."
            ),
            "source": "https://www.journals.uchicago.edu/journals/jop/registered-report-guidelines",
            "confidence": "high",
        }
    ],
}


def main():
    with RANKS.open() as fh:
        rows = list(csv.DictReader(fh))

    journals = []
    for r in rows:
        title = r["title"]
        periods = HISTORY.get(title, [])
        journals.append({
            "rank": int(r["rank"]),
            "title": title,
            "sjr": float(r["sjr"]),
            "publisher": r["publisher"],
            "periods": periods,
            "current": any(p["end"] is None for p in periods),
            "ever": bool(periods),
        })

    unmatched = sorted(set(HISTORY) - {j["title"] for j in journals})
    if unmatched:
        raise SystemExit(
            "history entries not found in the ranking (title mismatch?): "
            + ", ".join(unmatched)
        )

    ever = [j for j in journals if j["ever"]]
    current = [j for j in journals if j["current"]]
    payload = {
        "as_of": AS_OF,
        "rank_source": "SCImago Journal Rank 2025, political science, curated",
        "n_journals": len(journals),
        "n_ever": len(ever),
        "n_current": len(current),
        "journals": journals,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n")

    print(f"wrote {OUT.relative_to(ROOT)}: {len(journals)} journals, "
          f"{len(ever)} ever offered it, {len(current)} offer it now")
    for j in ever:
        for p in j["periods"]:
            span = f"{p['start']} → {p['end'] or 'now'}"
            print(f"  #{j['rank']:<3} {j['title'][:42]:<44} {span:<20} {p['kind']}")


if __name__ == "__main__":
    main()
