#!/usr/bin/env python3
"""Check every link on a rendered page (default: the CV) and report what's broken.

Complements scripts/audit-pub-links.py, which audits publication links at the
Zotero level. This one crawls the *rendered* HTML, so it also covers links that
never pass through Zotero: affiliations, testimony, mentorship placements, media
coverage, the PDF download button and internal site links.

Publisher bot walls (403) are reported as `botwall`, not as breakage — roughly
half the CV's publisher links refuse scripted requests while working fine in a
browser. Only `malformed`, `dead` and `redirect_login` set a non-zero exit code.

Usage:
    python3 scripts/check-links.py                      # docs/cv.html
    python3 scripts/check-links.py docs/cv.html docs/index.html
    python3 scripts/check-links.py https://aaronerlich.com/cv.html
    python3 scripts/check-links.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _linkcheck as lc  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HREF_RE = re.compile(r'href="([^"]+)"')
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "#")


def extract_hrefs(html: str) -> list:
    seen, out = set(), []
    for href in HREF_RE.findall(html):
        href = href.strip()
        if not href or href.startswith(SKIP_SCHEMES) or href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def load_page(target: str) -> tuple[str, str]:
    """Returns (html, base). base is a URL for remote pages, else a local dir."""
    if target.startswith(("http://", "https://")):
        req = urllib.request.Request(target, headers={"User-Agent": lc.UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace"), resp.geturl()
    path = Path(target)
    if not path.is_absolute():
        path = REPO / path
    return path.read_text(encoding="utf-8", errors="replace"), str(path)


def resolve_local(href: str, base: str) -> Path:
    """Map a relative href to the file that would be served for it."""
    clean = href.split("#")[0].split("?")[0]
    return (Path(base).parent / clean).resolve()


def check_page(target: str, workers: int) -> list:
    html, base = load_page(target)
    hrefs = extract_hrefs(html)
    remote_base = base.startswith(("http://", "https://"))
    rows, external = [], []

    for href in hrefs:
        if href.startswith(("http://", "https://")):
            external.append(href)
        elif remote_base:
            external.append(urllib.parse.urljoin(base, href))
        elif lc.malformed_reason(href) and not href.startswith(("/", ".")):
            # A schemeless absolute URL looks like a relative path to a browser.
            # This is exactly the bug that put a 404 on the live CV, so treat a
            # local href with a dotted host-like first segment as suspect.
            first = href.split("/")[0]
            if "." in first and not first.endswith((".html", ".css", ".js", ".pdf",
                                                    ".png", ".jpg", ".svg", ".xml")):
                rows.append({"page": target, "url": href, "status": "malformed",
                             "code": None, "note": "no scheme — resolves against "
                                                   "your own domain and 404s"})
            else:
                rows.append(_local_row(target, href, base))
        else:
            rows.append(_local_row(target, href, base))

    # Serialize per host so a single publisher never sees a burst.
    by_host = defaultdict(list)
    for url in external:
        by_host[urllib.parse.urlparse(url).netloc].append(url)

    def run_host(urls):
        out = []
        for url in urls:
            res = lc.check_url(url)
            if res["status"] == "botwall":
                m = re.search(r"(10\.\d{4,9}/[^\s?&#]+)", url)
                if m and lc.doi_resolves(m.group(1)):
                    res["note"] = "publisher blocks bots; DOI resolves — not broken"
            out.append({"page": target, "url": url, "status": res["status"],
                        "code": res["code"], "note": res["note"]})
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in pool.map(run_host, by_host.values()):
            rows.extend(chunk)
    return rows


def _local_row(target: str, href: str, base: str) -> dict:
    path = resolve_local(href, base)
    if path.is_dir():
        path = path / "index.html"
    ok = path.exists()
    return {"page": target, "url": href, "status": "ok" if ok else "dead",
            "code": None, "note": "" if ok else f"no file at {path}"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="*", default=["docs/cv.html"],
                    help="rendered HTML paths or URLs (default: docs/cv.html)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    rows = []
    for target in (args.targets or ["docs/cv.html"]):
        rows.extend(check_page(target, args.workers))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        counts = defaultdict(int)
        for r in rows:
            counts[r["status"]] += 1
        for r in sorted(rows, key=lambda r: r["status"]):
            if r["status"] == "ok":
                continue
            mark = "x" if r["status"] in lc.BROKEN else "!"
            print(f"  {mark} {r['status']:<15} {str(r['code'] or ''):<4} {r['url'][:88]}")
            if r["note"]:
                print(f"      {r['note']}")
        print("\n" + "  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    broken = [r for r in rows if r["status"] in lc.BROKEN]
    if broken:
        print(f"\n{len(broken)} broken link(s).", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
