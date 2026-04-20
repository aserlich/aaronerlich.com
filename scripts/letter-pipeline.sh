#!/bin/bash
#
# letter-pipeline.sh
#
# Runs one pass of the full letter-of-rec submission pipeline:
#
#   1. pull-letter-forms-from-kv.py
#        Pulls any newly-submitted form data (programs + state) from
#        Cloudflare KV back into _data/letter-requests.yml locally.
#
#   2. sync-lors-dropbox-to-onedrive.sh
#        Mirrors the Dropbox App folder (where the Worker writes student
#        uploads) into the canonical OneDrive LORs archive. --ignore-existing
#        protects Aaron's edits/drafts from being clobbered.
#
#   3. watch-letter-requests.py
#        Runs the letter-draft skill on any yaml entries in `uploaded`
#        state. Writes a draft .docx into each student's folder and fires
#        the reminder email to Aaron's McGill inbox.
#
# Stages are independent — each has its own lock file and short-circuits
# cleanly on empty queues. Intended to be invoked by launchd every 5 min
# (see ~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist).

set -u

REPO_ROOT="$HOME/Dropbox/admin_projects/aaronerlich.com"
LOG="$HOME/Library/Caches/letter-pipeline.log"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*" >> "$LOG"
}

mkdir -p "$(dirname "$LOG")"

log "=== pipeline start (pid $$) ==="

# Stage 1 — pull new form submissions from KV
if python3 "$REPO_ROOT/scripts/pull-letter-forms-from-kv.py" >> "$LOG" 2>&1; then
    log "stage 1 (pull-forms): ok"
else
    log "stage 1 (pull-forms): FAIL rc=$?"
fi

# Stage 2 — Dropbox → OneDrive rsync mirror
if bash "$REPO_ROOT/scripts/sync-lors-dropbox-to-onedrive.sh" --quiet >> "$LOG" 2>&1; then
    log "stage 2 (rsync-mirror): ok"
else
    log "stage 2 (rsync-mirror): FAIL rc=$?"
fi

# Stage 3 — run letter-draft skill on uploaded-state entries
if python3 "$REPO_ROOT/scripts/watch-letter-requests.py" >> "$LOG" 2>&1; then
    log "stage 3 (letter-draft): ok"
else
    log "stage 3 (letter-draft): FAIL rc=$?"
fi

log "=== pipeline end ==="
