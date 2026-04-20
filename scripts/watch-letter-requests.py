#!/usr/bin/env python3
"""
watch-letter-requests.py — Poll _data/letter-requests.yml for entries in
`uploaded` state and run the letter-draft skill against each.

Intended to be invoked periodically by launchd (see
~/Library/LaunchAgents/com.aaronerlich.letter-watcher.plist). A single run
processes every `uploaded` token once and exits; the state transitions
performed by letter_draft.py (`uploaded` → `drafting` → `draft_ready`)
prevent re-runs on subsequent polls.

Logs to ~/Library/Logs/letter-watcher.log.

Manual invocation:
  python3 scripts/watch-letter-requests.py          # one polling pass
  python3 scripts/watch-letter-requests.py --once   # same as default
  python3 scripts/watch-letter-requests.py --dry-run  # list work, don't run
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip3 install --user --break-system-packages pyyaml")


REPO = Path(__file__).resolve().parents[1]
LETTERS_PATH = REPO / "_data" / "letter-requests.yml"
SKILL_SCRIPT = Path.home() / ".claude" / "skills" / "letter-draft" / "letter_draft.py"
LOG_PATH = Path.home() / "Library" / "Caches" / "letter-watcher.log"
LOCK_PATH = Path("/tmp/letter-watcher.lock")


def log(msg: str) -> None:
    """Append a timestamped line to the watcher log and stderr."""
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        print(f"  (log write failed: {e})", file=sys.stderr)


def acquire_lock() -> bool:
    """Prevent overlapping runs. Returns True if lock acquired."""
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text().strip())
            # Check if the PID is still alive
            os.kill(pid, 0)
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock — remove it
            LOCK_PATH.unlink(missing_ok=True)
    LOCK_PATH.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def find_uploaded_tokens() -> list[dict]:
    """Return all letter-request entries in `uploaded` state."""
    if not LETTERS_PATH.exists():
        return []
    data = yaml.safe_load(LETTERS_PATH.read_text(encoding="utf-8")) or {}
    requests = data.get("requests", []) or []
    return [r for r in requests if r.get("state") == "uploaded"]


def run_letter_draft(token: str) -> tuple[bool, str]:
    """Invoke letter_draft.py against a single token. Returns (ok, output)."""
    if not SKILL_SCRIPT.exists():
        return False, f"skill script missing: {SKILL_SCRIPT}"
    try:
        result = subprocess.run(
            [sys.executable, str(SKILL_SCRIPT), "--token", token],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min per letter
            cwd=str(REPO),
        )
        ok = result.returncode == 0
        tail = (result.stdout or "") + (result.stderr or "")
        return ok, tail.strip()[-800:]
    except subprocess.TimeoutExpired:
        return False, "timed out after 600s"
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true",
                        help="Run one polling pass and exit (default).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report pending work without invoking the skill.")
    args = parser.parse_args()

    if not acquire_lock():
        log("another watcher instance is running; skipping")
        return 0

    try:
        pending = find_uploaded_tokens()
        if not pending:
            # Quiet — don't log every empty poll, it floods the log.
            return 0

        log(f"found {len(pending)} pending upload(s)")
        for req in pending:
            token = req.get("token", "")
            name = f"{req.get('first_name','?')} {req.get('last_name','?')}"
            ltype = req.get("letter_type", "?")
            if args.dry_run:
                log(f"  DRY-RUN would draft: {name} ({ltype}) token={token[:10]}…")
                continue
            log(f"  drafting: {name} ({ltype}) token={token[:10]}…")
            ok, tail = run_letter_draft(token)
            status = "ok" if ok else "FAIL"
            log(f"  → {status}: {name}")
            if tail:
                for tline in tail.splitlines()[-10:]:
                    log(f"      {tline}")
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
