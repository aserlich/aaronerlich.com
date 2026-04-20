#!/usr/bin/env python3
"""
pull-letter-forms-from-kv.py — Mirror of sync-letter-tokens-to-kv.py.

When a student submits the Worker's upload form, the Worker writes the
populated LetterRequest (programs array + advanced state + appended
state_log) back into the Cloudflare KV namespace under the token key.
This script fetches each local token from KV and merges any newer fields
(programs, state, state_log) into _data/letter-requests.yml.

Run manually from the repo root:
  python3 scripts/pull-letter-forms-from-kv.py

Or wire it into the Flask admin's Letters dashboard as a "Pull submissions"
button that runs this via subprocess.

Requires ~/.config/cloudflare/letter-worker.env with the same fields used
by the sync script:
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_KV_NAMESPACE_ID
  CLOUDFLARE_API_TOKEN
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip3 install --user --break-system-packages pyyaml")


REPO = Path(__file__).resolve().parents[1]
LETTERS_PATH = REPO / "_data" / "letter-requests.yml"
ENV_FILE = Path.home() / ".config" / "cloudflare" / "letter-worker.env"

# Ordering used to detect "forward" progress in the state machine.
STATE_ORDER = [
    "pending_upload",
    "uploaded",
    "drafting",
    "draft_ready",
    "approved",
    "sent",
    "closed",
]


def load_env() -> dict:
    """Load Cloudflare credentials from env file or environment variables."""
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


def kv_get(env: dict, key: str) -> dict | None:
    """GET a KV value. Returns the parsed JSON dict, or None if missing."""
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{env['account_id']}"
        f"/storage/kv/namespaces/{env['namespace_id']}/values/{key}"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {env['api_token']}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"KV GET {key} failed: {e.code} {detail[:200]}")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def state_index(state: str) -> int:
    """Return position of a state in the state machine (-1 if unknown)."""
    try:
        return STATE_ORDER.index(state)
    except ValueError:
        return -1


def dump_yaml_with_header(path: Path, data: dict) -> None:
    """Preserve the top-of-file comment block when rewriting the yaml."""
    existing = path.read_text(encoding="utf-8")
    header_lines = []
    for line in existing.splitlines():
        if line.startswith("#") or not line.strip():
            header_lines.append(line)
        else:
            break
    header = "\n".join(header_lines)
    yaml_body = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    path.write_text(
        (header + "\n" if header else "") + yaml_body,
        encoding="utf-8",
    )


def merge_remote(local: dict, remote: dict) -> tuple[dict, list[str]]:
    """Merge KV's version into the local entry. Returns (merged, changes)."""
    changes: list[str] = []
    merged = dict(local)

    # programs: overwrite only if remote has a non-empty list and differs
    remote_programs = remote.get("programs")
    local_programs = local.get("programs")
    if (
        isinstance(remote_programs, list)
        and len(remote_programs) > 0
        and remote_programs != local_programs
    ):
        merged["programs"] = remote_programs
        changes.append(f"programs ({len(remote_programs)} entries)")

    # state: only advance forward
    remote_state = remote.get("state")
    local_state = local.get("state")
    if (
        isinstance(remote_state, str)
        and state_index(remote_state) > state_index(str(local_state))
    ):
        merged["state"] = remote_state
        changes.append(f"state {local_state}→{remote_state}")

    # state_log: append any entries the remote has that we don't
    remote_log = remote.get("state_log") or []
    local_log = local.get("state_log") or []
    if isinstance(remote_log, list) and len(remote_log) > len(local_log):
        # Trust the remote log tail past our length
        merged["state_log"] = list(local_log) + list(remote_log[len(local_log):])
        changes.append(f"state_log +{len(remote_log) - len(local_log)}")
    elif "state_log" not in merged:
        merged["state_log"] = local_log

    # If state advanced but no log entry was appended, stamp one now
    if (
        "state" in merged
        and merged["state"] != local_state
        and not any(
            e.get("state") == merged["state"] for e in merged.get("state_log", [])
        )
    ):
        merged.setdefault("state_log", []).append(
            {"state": merged["state"], "at": datetime.now().isoformat(timespec="seconds")}
        )

    return merged, changes


def main() -> int:
    env = load_env()
    if not LETTERS_PATH.exists():
        sys.exit(f"Missing {LETTERS_PATH}")

    data = yaml.safe_load(LETTERS_PATH.read_text(encoding="utf-8")) or {}
    requests_list = data.get("requests") or []
    if not requests_list:
        print("No letter requests in yaml — nothing to pull.", file=sys.stderr)
        return 0

    pulled = 0
    unchanged = 0
    missing = 0

    for idx, local in enumerate(requests_list):
        token = local.get("token")
        if not token:
            continue
        name = f"{local.get('first_name','?')} {local.get('last_name','?')}"
        try:
            remote = kv_get(env, token)
        except Exception as e:
            print(f"  fail {token[:10]}…  {e}", file=sys.stderr)
            continue
        if remote is None:
            missing += 1
            continue
        merged, changes = merge_remote(local, remote)
        if changes:
            requests_list[idx] = merged
            pulled += 1
            print(f"  pull {token[:10]}…  {name}: {', '.join(changes)}")
        else:
            unchanged += 1

    if pulled > 0:
        data["requests"] = requests_list
        dump_yaml_with_header(LETTERS_PATH, data)

    print(
        f"\nPulled: {pulled} updated, {unchanged} unchanged, {missing} missing in KV",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
