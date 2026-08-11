"""Minimal AT Protocol client for posting to Bluesky.

Stdlib only, on purpose: `atproto` and `requests` are not installed, and the
house idiom for JSON HTTP is urllib (see sync-letter-tokens-to-kv.py, which
talks to the Cloudflare v4 API the same way). Two endpoints are all we need.

Credentials live at ~/.config/bluesky/credentials.env (mode 600):

    BLUESKY_HANDLE=aaronerlich.bsky.social
    BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

Use a Bluesky **app password** (bsky.app -> Settings -> Privacy and Security ->
App Passwords), never the account password. Environment variables of the same
names win over the file.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PDS = "https://bsky.social"
ENV_FILE = Path.home() / ".config" / "bluesky" / "credentials.env"
TIMEOUT = 20


# ---------------------------------------------------------------- credentials

def load_env() -> dict:
    """Env vars first, then the dotenv-style file. Copied from the loader in
    sync-letter-tokens-to-kv.py so both follow the same house convention."""
    env = {
        "handle": os.environ.get("BLUESKY_HANDLE", ""),
        "app_password": os.environ.get("BLUESKY_APP_PASSWORD", ""),
    }
    keymap = {"BLUESKY_HANDLE": "handle", "BLUESKY_APP_PASSWORD": "app_password"}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            slot = keymap.get(k.strip())
            if slot and not env[slot]:
                env[slot] = v.strip().strip("'\"")
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(
            f"Missing Bluesky credentials: {', '.join(missing)}\n"
            f"  Set BLUESKY_HANDLE / BLUESKY_APP_PASSWORD, or save them to\n"
            f"  {ENV_FILE} (chmod 600). Use an app password, not your account password."
        )
    return env


# ---------------------------------------------------------------- xrpc

def _xrpc(method: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        f"{PDS}/xrpc/{method}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"{method} failed: HTTP {e.code} {detail}") from None


def create_session(env: dict | None = None) -> dict:
    env = env or load_env()
    return _xrpc("com.atproto.server.createSession",
                 {"identifier": env["handle"], "password": env["app_password"]})


# ---------------------------------------------------------------- facets

_URL_RE = re.compile(r"https?://[^\s<>\"\]）)]+")


def link_facets(text: str) -> list:
    """Bluesky does not auto-link: every URL needs a facet whose byteStart and
    byteEnd are offsets into the **UTF-8 encoding** of the text, not character
    indices. Non-ASCII characters before a link therefore shift the offsets,
    which is the classic way to get a post whose link is subtly mis-anchored.
    """
    facets = []
    raw = text.encode("utf-8")
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?")
        start = len(text[:m.start()].encode("utf-8"))
        end = start + len(url.encode("utf-8"))
        assert raw[start:end].decode("utf-8") == url, "facet offset mismatch"
        facets.append({
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        })
    return facets


def external_embed(uri: str, title: str, description: str = "") -> dict:
    """A link card. The thumbnail would need a com.atproto.repo.uploadBlob
    round-trip; the card renders fine without one."""
    return {
        "$type": "app.bsky.embed.external",
        "external": {
            "uri": uri,
            "title": (title or uri)[:300],
            "description": (description or "")[:1000],
        },
    }


# ---------------------------------------------------------------- posting

def post_url(handle: str, at_uri: str) -> str:
    """at://<did>/app.bsky.feed.post/<rkey> -> the public bsky.app permalink."""
    rkey = at_uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def build_record(text: str, embed: dict | None = None, langs=("en",)) -> dict:
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": dt.datetime.now(dt.timezone.utc)
                       .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "langs": list(langs),
    }
    facets = link_facets(text)
    if facets:
        record["facets"] = facets
    if embed:
        record["embed"] = embed
    return record


def post(text: str, embed: dict | None = None, env: dict | None = None) -> dict:
    """Post and return {'uri', 'cid', 'url', 'handle'}."""
    env = env or load_env()
    session = create_session(env)
    record = build_record(text, embed)
    result = _xrpc(
        "com.atproto.repo.createRecord",
        {"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
        token=session["accessJwt"],
    )
    handle = session.get("handle") or env["handle"]
    return {"uri": result["uri"], "cid": result.get("cid", ""),
            "url": post_url(handle, result["uri"]), "handle": handle}


if __name__ == "__main__":  # offline check of the fiddly part
    samples = [
        "Plain https://example.com trailing",
        "Côte d'Ivoire — em-dash before https://aaronerlich.com/citation-arcs/",
        "Ukrainian текст then https://example.org/x?a=1&b=2 end",
        "No link at all",
    ]
    for s in samples:
        for f in link_facets(s):
            i = f["index"]
            got = s.encode("utf-8")[i["byteStart"]:i["byteEnd"]].decode("utf-8")
            print(f"ok  {got:<45} bytes {i['byteStart']}..{i['byteEnd']}  | {s[:38]}…")
        if not link_facets(s):
            print(f"--  (no links)                                    | {s[:38]}")
