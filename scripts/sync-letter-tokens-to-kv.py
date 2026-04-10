#!/usr/bin/env python3
"""
sync-letter-tokens-to-kv.py — Push active letter request tokens from
_data/letter-requests.yml to the Cloudflare Worker KV namespace.

The Worker (letter-upload-worker/) reads tokens from KV to validate incoming
upload URLs. This script is the source-of-truth → KV bridge.

Run manually after creating a new letter request in the Flask admin:
  python3 scripts/sync-letter-tokens-to-kv.py

Or wire it into the Flask admin's `letters_new` handler so every new request
auto-syncs (see README for the call-site).

Requires:
  CLOUDFLARE_ACCOUNT_ID       (from dashboard URL)
  CLOUDFLARE_KV_NAMESPACE_ID  (from `wrangler kv namespace create TOKENS`)
  CLOUDFLARE_API_TOKEN         (from dashboard → My Profile → API Tokens
                                  with Workers KV:Edit permission)

Stored in ~/.config/cloudflare/letter-worker.env as:
  CLOUDFLARE_ACCOUNT_ID=...
  CLOUDFLARE_KV_NAMESPACE_ID=...
  CLOUDFLARE_API_TOKEN=...
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip3 install --user --break-system-packages pyyaml")


REPO = Path(__file__).resolve().parents[1]
LETTERS_PATH = REPO / "_data" / "letter-requests.yml"
ENV_FILE = Path.home() / ".config" / "cloudflare" / "letter-worker.env"


def load_env() -> dict:
    """Load Cloudflare credentials from ~/.config/cloudflare/letter-worker.env
    or environment variables."""
    env = {
        "account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
        "namespace_id": os.environ.get("CLOUDFLARE_KV_NAMESPACE_ID", ""),
        "api_token": os.environ.get("CLOUDFLARE_API_TOKEN", ""),
    }
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k == "CLOUDFLARE_ACCOUNT_ID" and not env["account_id"]:
                env["account_id"] = v
            elif k == "CLOUDFLARE_KV_NAMESPACE_ID" and not env["namespace_id"]:
                env["namespace_id"] = v
            elif k == "CLOUDFLARE_API_TOKEN" and not env["api_token"]:
                env["api_token"] = v
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(
            f"Missing Cloudflare config: {', '.join(missing)}\n"
            f"  Set env vars or save to {ENV_FILE}"
        )
    return env


def kv_put(env: dict, key: str, value: str) -> None:
    """PUT a key/value pair to the Cloudflare KV namespace."""
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['account_id']}"
        f"/storage/kv/namespaces/{env['namespace_id']}/values/{key}"
    )
    req = urllib.request.Request(
        url,
        data=value.encode("utf-8"),
        headers={
            "Authorization": f"Bearer {env['api_token']}",
            "Content-Type": "text/plain",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"KV PUT returned {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"KV PUT {key} failed: {e.code} {body[:200]}")


def kv_delete(env: dict, key: str) -> None:
    """DELETE a key from the Cloudflare KV namespace."""
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['account_id']}"
        f"/storage/kv/namespaces/{env['namespace_id']}/values/{key}"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {env['api_token']}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                raise RuntimeError(f"KV DELETE returned {resp.status}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"KV DELETE {key} failed: {e.code} {body[:200]}")


def kv_list(env: dict) -> list:
    """List keys in the KV namespace (paginated)."""
    keys = []
    cursor = ""
    while True:
        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{env['account_id']}"
            f"/storage/kv/namespaces/{env['namespace_id']}/keys?limit=1000"
        )
        if cursor:
            url += f"&cursor={cursor}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {env['api_token']}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.load(resp)
        for item in data.get("result", []):
            keys.append(item["name"])
        cursor = data.get("result_info", {}).get("cursor", "")
        if not cursor:
            break
    return keys


def main():
    env = load_env()

    if not LETTERS_PATH.exists():
        sys.exit(f"Missing {LETTERS_PATH}")
    data = yaml.safe_load(LETTERS_PATH.read_text(encoding="utf-8")) or {}
    requests = data.get("requests", []) or []

    # Only push tokens whose state is pending_upload. Tokens for closed/sent
    # requests get removed from KV to keep the namespace clean.
    active = {r["token"]: r for r in requests if r.get("state") == "pending_upload"}
    inactive = {r["token"] for r in requests if r.get("state") != "pending_upload"}

    existing_keys = set(kv_list(env))

    put_count = 0
    del_count = 0
    for token, req in active.items():
        try:
            kv_put(env, token, json.dumps(req, ensure_ascii=False))
            put_count += 1
            print(f"  put  {token[:10]}…  ({req['first_name']} {req['last_name']})")
        except Exception as e:
            print(f"  fail {token[:10]}…  {e}", file=sys.stderr)

    # Remove tokens that are no longer active but still in KV
    for key in existing_keys:
        if key not in active:
            try:
                kv_delete(env, key)
                del_count += 1
                print(f"  del  {key[:10]}…")
            except Exception as e:
                print(f"  fail-del {key[:10]}…  {e}", file=sys.stderr)

    print(f"\nSynced: {put_count} put, {del_count} deleted", file=sys.stderr)


if __name__ == "__main__":
    main()
