"""Shared link-status classification for the CV link audit and the link checker.

Used by scripts/audit-pub-links.py (Zotero-side URL audit) and
scripts/check-links.py (rendered-HTML crawl). Stdlib only, matching the rest of
scripts/ — the repo has no `requests`.

The classification that matters most here: academic publishers (Sage, Taylor &
Francis, Wiley, Chicago, OUP, ScienceDirect, Cambridge) sit behind bot walls that
answer 403 to any scripted request while working perfectly in a browser. Those
are `botwall`, never `dead` — reporting them as broken is how a link audit turns
into 30 false alarms. Where the item has a DOI we confirm the work still resolves
via Crossref, which is not bot-walled.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 15

# Statuses that mean a reader hits something other than the paper.
BROKEN = {"malformed", "dead", "redirect_login"}

# Hosts that still answer but whose URL form is obsolete: the publisher has
# migrated and only the DOI is durable. Proposed for replacement even at 200.
LEGACY_HOST_RE = re.compile(
    r"(^|\.)(journals\.cambridge\.org|cps\.sagepub\.com)$|"
    r"\.proxy\d*\.library\.|^www-.*-com\.proxy",
    re.IGNORECASE,
)

# A redirect into any of these means the reader gets a login form, not the paper.
LOGIN_RE = re.compile(
    r"(^|\.)login\.|\.proxy\d*\.library\.|/login|/action/showLogin|idp\.|shibboleth|"
    r"accounts\.google\.com|/servicelogin|/signin|/sso/|wayf",
    re.IGNORECASE,
)


def is_legacy_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc
    return bool(LEGACY_HOST_RE.search(host) or LEGACY_HOST_RE.search(url))


def malformed_reason(url: str) -> str | None:
    """Pre-network validation. Returns a reason string, or None if the URL is sane."""
    if not url or not url.strip():
        return "empty"
    if url != url.strip():
        return "leading/trailing whitespace"
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme:
        # The killer case: a browser resolves this relative to the current page,
        # so "example.org/x" becomes aaronerlich.com/example.org/x -> 404.
        return "no scheme (renders as a relative link)"
    if parsed.scheme not in ("http", "https"):
        return f"non-http scheme: {parsed.scheme}"
    if not parsed.netloc:
        return "no host"
    if url.rstrip().endswith((".", ",", ";")):
        return "trailing punctuation"
    return None


def _request(url: str, method: str, timeout: int):
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check_url(url: str, timeout: int = TIMEOUT) -> dict:
    """Classify a single URL.

    status is one of: ok, malformed, dead, redirect_login, botwall, down, unknown.
    """
    reason = malformed_reason(url)
    if reason:
        return {"status": "malformed", "code": None, "final_url": url, "note": reason}

    code = None
    final_url = url
    try:
        with _request(url, "HEAD", timeout) as resp:
            code, final_url = resp.status, resp.geturl()
    except urllib.error.HTTPError as e:
        code, final_url = e.code, (e.geturl() or url)
        # Plenty of servers reject HEAD but serve GET fine.
        if code in (403, 405, 406, 501):
            try:
                with _request(url, "GET", timeout) as resp:
                    code, final_url = resp.status, resp.geturl()
            except urllib.error.HTTPError as e2:
                code, final_url = e2.code, (e2.geturl() or url)
            except Exception:
                pass
    except urllib.error.URLError as e:
        return {"status": "down", "code": None, "final_url": url,
                "note": f"connection failed: {e.reason}"}
    except Exception as e:  # socket timeouts, bad redirects, malformed responses
        return {"status": "unknown", "code": None, "final_url": url,
                "note": f"{type(e).__name__}: {e}"}

    # A login wall is a broken link for every reader outside the institution,
    # whatever status code it happens to return.
    if LOGIN_RE.search(final_url):
        return {"status": "redirect_login", "code": code, "final_url": final_url,
                "note": "redirects to an institutional login wall"}
    if code in (404, 410):
        return {"status": "dead", "code": code, "final_url": final_url, "note": "not found"}
    if code in (403, 429, 999):
        return {"status": "botwall", "code": code, "final_url": final_url,
                "note": "publisher blocks scripted requests; verify via DOI"}
    if code and 500 <= code < 600:
        return {"status": "down", "code": code, "final_url": final_url,
                "note": "server error; recheck later"}
    if code and 200 <= code < 400:
        return {"status": "ok", "code": code, "final_url": final_url, "note": ""}
    return {"status": "unknown", "code": code, "final_url": final_url, "note": ""}


def doi_resolves(doi: str, timeout: int = TIMEOUT) -> bool:
    """True if Crossref knows the DOI. Crossref's API is never bot-walled, so this
    is how we tell 'publisher blocks curl' apart from 'the paper is gone'."""
    if not doi:
        return False
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    try:
        with _request(url, "GET", timeout) as resp:
            return resp.status == 200 and json.loads(resp.read())["status"] == "ok"
    except Exception:
        return False
