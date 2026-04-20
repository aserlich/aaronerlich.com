#!/bin/bash
#
# sync-lors-dropbox-to-onedrive.sh
#
# One-way mirror: files uploaded by students via the Cloudflare
# letter-upload-worker land first in the Dropbox App folder sandbox,
# then this script rsyncs them into the canonical OneDrive LORs archive.
#
# --ignore-existing is load-bearing: it prevents the mirror from
# clobbering any edits Aaron makes to files already in OneDrive (drafts,
# signed final letters, etc.). Only brand-new files flow from Dropbox
# into OneDrive.
#
# Usage:
#   bash scripts/sync-lors-dropbox-to-onedrive.sh           # verbose
#   bash scripts/sync-lors-dropbox-to-onedrive.sh --quiet   # summary only
#
# To run on a schedule, wire this into a launchd agent — a template
# plist lives alongside this script at scripts/com.aaronerlich.lors-mirror.plist.

# Explicit exits at the critical spots; avoid strict mode because
# `find` / `rsync` pipes can produce spurious non-zero exits on healthy
# runs (e.g., empty Dropbox folder, OneDrive cloud-file stubs that `find`
# can't stat while the OS is busy materializing them).
set -u

DROPBOX_ROOT="$HOME/Dropbox/Apps/letter-upload-worker/LORs"
ONEDRIVE_ROOT="$HOME/Library/CloudStorage/OneDrive-McGillUniversity/LORs"
# NOTE: ~/Library/Logs is root-owned with mode 700 on Aaron's machine (stale
# sudo state), so we write our log to ~/Library/Caches/ which is always
# user-writable. If the Library/Logs perm ever gets fixed:
#   sudo chown -R "$USER" ~/Library/Logs
# — we can move this back.
LOG_FILE="$HOME/Library/Caches/lors-sync.log"
LOCK_FILE="/tmp/lors-sync.lock"

QUIET=0
if [ "${1:-}" = "--quiet" ]; then
    QUIET=1
fi

log() {
    local msg="[$(date '+%Y-%m-%dT%H:%M:%S')] $*"
    mkdir -p "$(dirname "$LOG_FILE")"
    printf '%s\n' "$msg" >> "$LOG_FILE"
    if [ "$QUIET" = "0" ]; then
        printf '%s\n' "$msg" >&2
    fi
}

# Prevent overlapping runs (important if launchd is ticking every 5 min
# and a big file is mid-rsync).
if [ -e "$LOCK_FILE" ]; then
    lock_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        log "another lors-sync is running (pid $lock_pid); skipping"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ ! -d "$DROPBOX_ROOT" ]; then
    log "source missing: $DROPBOX_ROOT — no submissions received yet, nothing to mirror"
    exit 0
fi

if [ ! -d "$ONEDRIVE_ROOT" ]; then
    log "ERROR: destination missing: $ONEDRIVE_ROOT (is OneDrive mounted?)"
    exit 1
fi

# Count candidate files before / after for a meaningful summary line.
pre_count=$(find "$ONEDRIVE_ROOT" -type f 2>/dev/null | wc -l | tr -d ' ')

rsync_args=(
    -a                 # archive mode: preserve perms, times, symlinks
    --ignore-existing  # NEVER overwrite files already on the OneDrive side
    --exclude '.DS_Store'
    --exclude '.dropbox'
    --exclude '.dropbox.cache'
    --exclude '*.tmp'
    --exclude '~$*'    # Word lock files
)
if [ "$QUIET" = "0" ]; then
    rsync_args+=(-v)
fi

rsync "${rsync_args[@]}" "$DROPBOX_ROOT/" "$ONEDRIVE_ROOT/" 2>&1 | while IFS= read -r line; do
    # Route rsync output through log() so both log file + stderr get a
    # timestamped trail when run interactively.
    log "rsync: $line"
done

post_count=$(find "$ONEDRIVE_ROOT" -type f 2>/dev/null | wc -l | tr -d ' ')
delta=$((post_count - pre_count))

if [ "$delta" -gt 0 ]; then
    log "mirrored $delta new file(s) (OneDrive LORs: $pre_count → $post_count)"
else
    log "no new files (OneDrive LORs unchanged: $post_count)"
fi
