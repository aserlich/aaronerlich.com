# Letter-of-Recommendation Intake System — Operations Manual

This document is the reference for the letter-of-rec intake system built into
`aaronerlich.com`. It covers: how it works end-to-end, where every piece
lives, how to use it day-to-day, how to rotate credentials, and how to fix
things when they break. Your future self is the intended audience.

Last substantive update: 2026-04-20.

---

## What the system does

Replaces "student emails me a messy bundle of materials and I chase them for
missing docs" with a structured intake:

1. **You** generate a secret per-student upload URL in the Flask admin
2. **You** email that URL to the student in your reply accepting the ask
3. **The student** fills a web form (one fieldset per program + four required
   document uploads) at that URL
4. **The Cloudflare Worker** validates, uploads the files to your Dropbox App
   folder, and writes the structured program data back to Cloudflare KV
5. **A launchd job on your laptop** runs every 5 min:
   - Pulls the program data from KV into `_data/letter-requests.yml`
   - Mirrors the Dropbox folder into your OneDrive LORs archive
   - Runs the `letter-draft` Claude skill on any new entries → writes a
     draft `.docx` into the student folder
6. **You** get two emails in McGill Outlook: one when the student submits,
   one when the draft is ready for review
7. **You** open the `.docx`, edit, paste into your letterhead template,
   send from Outlook, mark state in the Flask admin

**Design principles** that inform every choice:

- *Invisible from the public site.* The website is a normal-looking static
  informational page at `/resources/letters.html`. No "AI-powered" branding,
  no public form, no token shows up in any sitemap. Each student only sees
  the pipeline via the one-off link you personally email them.
- *No outbound mail as you.* Automation never sends mail impersonating you.
  All letters to admissions committees are sent manually from Outlook.
  Automation only sends notifications TO you from `noreply@aaronerlich.com`.
- *Dropbox is the ingestion tip, OneDrive is the canonical archive.* The
  Worker writes to Dropbox because McGill's Entra tenant blocks third-party
  OAuth apps. A one-way `rsync --ignore-existing` mirrors into OneDrive so
  your 834-file style corpus grows alongside new submissions without ever
  clobbering files you've edited on the OneDrive side.

---

## End-to-end architecture

```
                                                         ┌──────────────────┐
                                                         │  resources/      │
                                                         │  letters.qmd     │
                                                         │ (public info     │
                                                         │  page — no form) │
                                                         └──────────────────┘

  You                                                        Student
  (Flask admin, localhost:5000)                              (personal email)
        │                                                            │
        │ 1. "New letter request" form                                │
        │    (LastName, FirstName, FirstYear, Category,               │
        │     LetterType)                                             │
        ▼                                                            │
  ┌─────────────────────┐        3. subprocess (async)                │
  │ _data/letter-       │  ◀─────────────  sync-letter-tokens-to-kv.py│
  │ requests.yml        │                       │                     │
  │ (state: pending_    │                       ▼                     │
  │  upload)            │                 ┌───────────────┐           │
  └─────────────────────┘                 │ Cloudflare KV │           │
        │                                 │ TOKENS        │           │
        │ 2. you copy the URL             │ namespace     │           │
        │    https://letter-              └───────┬───────┘           │
        │    upload-worker.aaron-                 │                   │
        │    erlich.workers.dev/                  │ 4. GET /upload/T  │
        │    upload/<TOKEN>                       ▼                   │
        │                                 ┌───────────────────────┐   │
        │ 5. email the URL ──────────────▶│ Cloudflare Worker     │◀──┘
        │                                 │ letter-upload-worker  │
        │                                 │ • renders form        │
        │                                 │ • accepts POST:       │
        │                                 │   - programs JSON     │
        │                                 │   - 4 files           │
        │                                 │ • uploads to Dropbox  │
        │                                 │ • updates KV          │
        │                                 │ • fires Resend email  │
        │                                 └────┬────────┬─────────┘
        │                                      │        │
        │                  Dropbox API         │        │ 6. Resend API
        │                  (refresh token      │        ▼
        │                   flow — permanent)  │   ┌──────────────┐
        │                                      │   │  McGill      │
        │                                      ▼   │  Outlook     │
        │                         ┌─────────────────┐              │
        │                         │ ~/Dropbox/Apps/ │  (student    │
        │                         │ letter-upload-  │   submission │
        │                         │ worker/LORs/... │   notif)     │
        │                         │ <Category>/     │              │
        │                         │ <LastName_      │              │
        │                         │  FirstName_Year>│              │
        │                         │ 01-statement_...│              │
        │                         │ 02-transcript...│              │
        │                         │ 03-cv_...       │              │
        │                         │ 04-self-brief_..│              │
        │                         └────────┬────────┘              │
        │                                  │                       │
        │                launchd every     │                       │
        │                  5 minutes:      │                       │
        │       ┌──────────────────────────┼──────────────────────┐│
        │       │  letter-pipeline.sh      │                      ││
        │       │                          │                      ││
        │       │  stage 1: pull-letter-forms-from-kv.py          ││
        │       │     KV → _data/letter-requests.yml              ││
        │       │     (state: uploaded, programs populated)       ││
        │       │                                                 ││
        │       │  stage 2: sync-lors-dropbox-to-onedrive.sh      ││
        │       │     ~/Dropbox/Apps/... → ~/Library/CloudStorage/││
        │       │                 OneDrive-McGillUniversity/LORs/ ││
        │       │                                                 ││
        │       │  stage 3: watch-letter-requests.py              ││
        │       │     for each uploaded entry:                    ││
        │       │       letter_draft.py --token T                 ││
        │       │         • reads 4 files + programs              ││
        │       │         • samples 6 style letters from corpus   ││
        │       │         • calls Claude sonnet-4-6               ││
        │       │         • writes <Last>_<First>_LOR_draft.docx  ││
        │       │         • fires Resend "draft ready" email ─────┘│
        │       │         • transitions state: drafting→draft_ready│
        │       └─────────────────────────────────────────────────┘│
        │                                                          │
        ▼                                                          ▼
 (you edit .docx in Word, paste into letterhead,          (you see drafts
  send from Outlook, mark as sent in Flask admin)          in McGill Outlook)
```

---

## Where each piece lives

### In this repo (`~/Dropbox/admin_projects/aaronerlich.com`)

| Path | Purpose |
|---|---|
| `resources/letters.qmd` | Public informational page at `aaronerlich.com/resources/letters.html` |
| `_data/letter-requests.yml` | State store — one entry per letter request, source of truth for tokens/state/programs |
| `scripts/cv_admin.py` | Flask admin at `localhost:5000`. Generates tokens, state dashboard, tracks drafts through states `pending_upload → uploaded → drafting → draft_ready → approved → sent → closed` |
| `scripts/sync-letter-tokens-to-kv.py` | Pushes active tokens → Cloudflare KV so the Worker can validate them |
| `scripts/pull-letter-forms-from-kv.py` | Reverse direction — reads KV, merges submitted programs + advanced state back into yaml |
| `scripts/sync-lors-dropbox-to-onedrive.sh` | One-way rsync: Dropbox App folder → OneDrive LORs archive. `--ignore-existing` protects your edits. |
| `scripts/watch-letter-requests.py` | Polls yaml for `uploaded`-state entries, runs letter-draft skill on each |
| `scripts/letter-pipeline.sh` | Orchestrator that runs the three scripts above in order. Called by launchd every 5 min |
| `scripts/com.aaronerlich.letter-pipeline.plist` | Launchd agent definition. Copy to `~/Library/LaunchAgents/` to install |
| `letter-upload-worker/` | Cloudflare Worker project (TypeScript) — form UI + file upload + KV write-back + Resend notification |

### Outside this repo

| Path | Purpose |
|---|---|
| `~/Library/CloudStorage/OneDrive-McGillUniversity/LORs/` | 834-file style corpus + canonical archive. Read by `letter-draft` skill as style reference |
| `~/Dropbox/Apps/letter-upload-worker/LORs/` | Ingestion tip. Worker writes uploads here; rsync mirrors to OneDrive within 5 min |
| `~/.claude/skills/letter-draft/` | Claude skill — reads materials, drafts letter in your voice, writes `.docx`, fires reminder email |
| `~/.config/cloudflare/letter-worker.env` | Cloudflare API token + account ID + KV namespace ID (mode 600) |
| `~/.config/resend/api_key` | Resend API key used by the letter-draft skill to send the "draft ready" email (mode 600) |
| `~/.config/anthropic/api_key` | Reused across this system and the translation pipeline (mode 600) |
| `~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist` | Installed launchd agent — runs pipeline every 5 min |
| `~/Library/Caches/letter-pipeline.log` | Timestamped log for the pipeline orchestrator |
| `~/Library/Caches/letter-watcher.log` | Log for the drafting stage |
| `~/Library/Caches/lors-sync.log` | Log for the rsync stage |

### In the cloud

| Thing | Provider | Dashboard |
|---|---|---|
| `letter-upload-worker` Worker | Cloudflare (account `aaron.erlich@gmail.com`) | https://dash.cloudflare.com/ → Workers |
| `TOKENS` KV namespace | Cloudflare | Same dashboard → KV |
| `aaronerlich.com` domain | Namecheap | https://ap.www.namecheap.com/ |
| SPF / DKIM / MX / DMARC records | Namecheap DNS (Advanced DNS tab) | Same |
| Resend sending account | Resend | https://resend.com/domains |
| Dropbox app `letter-upload-worker` | Dropbox (personal) | https://www.dropbox.com/developers/apps |

---

## Day-to-day: the workflow for one student

**1. Student asks you for a letter.**

Reply within 3 business days to say yes or no. If yes, keep their email open.

**2. Create the letter request in the Flask admin.**

```bash
cd ~/Dropbox/admin_projects/aaronerlich.com
python3 scripts/cv_admin.py   # opens at http://localhost:5000
```

Click **Letters** → **New letter request**. Fill in last name, first name,
the year you first wrote them a letter (for returning students use
**Re-upload link** instead), category (`Undergrad_LORs`, `MA_toPHDJOB_LORs`,
etc.), and letter type (`ma`, `phd`, `job_or_internship`). Submit.

The Flask admin generates a 24-char token and **automatically syncs it to
Cloudflare KV** (via `sync_tokens_to_kv_async()`).

**3. Copy the upload URL** shown on the request detail page. It'll look like:

```
https://letter-upload-worker.aaron-erlich.workers.dev/upload/<TOKEN>
```

(Or if you've set up the custom domain: `https://upload.aaronerlich.com/upload/<TOKEN>`)

**4. Paste the URL into your reply email** and send. The student now has
everything they need.

**5. Wait.** You don't need to do anything else until the student submits.

**6. Student submits the form.** The Worker uploads the 4 files to Dropbox
with slot-tagged filenames (`01-statement_*`, `02-transcript_*`, `03-cv_*`,
`04-self-brief_*`), writes the programs array back to KV, and fires a Resend
email to your McGill inbox:

> Subject: Letter request: <First> <Last> (<Category>)

**7. Within 5 minutes** the launchd pipeline runs:

- `_data/letter-requests.yml` gets the programs + `state: uploaded`
- The 4 files land in `~/Library/CloudStorage/OneDrive-McGillUniversity/LORs/<Category>/<folder>/`
- The `letter-draft` skill runs, writes `<Last>_<First>_LOR_draft.docx`
  into the same folder, and fires a second Resend email:

> Subject: Draft ready: <First> <Last> — <type>

**8. Open the draft in Word.** The email body tells you the exact path.
Edit the draft, paste into your Poli Sci letterhead template, send from
Outlook to each program on the student's list, and when done mark the
request as `sent` in the Flask admin.

---

## Credentials reference

All credentials are stored **outside the repo** in `~/.config/*` (mode 600)
or as Cloudflare Worker secrets. Never commit any of these.

### Cloudflare

- **OAuth login for wrangler**: `npx wrangler login` (one-time, browser flow)
- **API token for Python scripts**: created at
  `https://dash.cloudflare.com/profile/api-tokens` using the
  "Edit Cloudflare Workers" template. Stored in
  `~/.config/cloudflare/letter-worker.env`.
- **Account ID**: `d5d22e8579d75b6db4d17f532e978b2c`
- **KV namespace ID (TOKENS)**: `5df261b8e3a94338817aedaf3284b0f5`

### Worker secrets (set via `wrangler secret put <NAME>` from
`letter-upload-worker/` directory)

| Name | Purpose | Rotation |
|---|---|---|
| `DROPBOX_APP_KEY` | Public identifier for the Dropbox app | Rarely; regenerated only if you delete the app |
| `DROPBOX_APP_SECRET` | App password. Lives under "Show" button at https://www.dropbox.com/developers/apps | Rarely; if you suspect leak, regenerate in Dropbox dashboard and update secret |
| `DROPBOX_REFRESH_TOKEN` | Long-lived user OAuth credential. Does not expire unless revoked | Only if you revoke or lose it |
| `DROPBOX_ACCESS_TOKEN` | Short-lived fallback (4 hr). Unused while refresh flow is working — remove after confirming | Remove entirely once stable |
| `RESEND_API_KEY` | Sending key for notification emails | Rotate by creating new key in Resend dashboard + `wrangler secret put` |
| `NOTIFICATION_EMAIL` | Your McGill address (where all notifications land) | Static unless your email changes |

### Rotating the Dropbox refresh token (rare)

If the refresh token gets revoked somehow, redo the OAuth flow:

1. Open this URL in browser (replace `APP_KEY`):
   `https://www.dropbox.com/oauth2/authorize?client_id=<APP_KEY>&response_type=code&token_access_type=offline`
2. Click **Allow** → Dropbox displays an auth code
3. Exchange the code for a refresh token:
   ```bash
   curl -X POST https://api.dropboxapi.com/oauth2/token \
     -u '<APP_KEY>:<APP_SECRET>' \
     -d 'grant_type=authorization_code' \
     --data-urlencode 'code=<AUTH_CODE>'
   ```
4. Copy the `refresh_token` value from the response
5. `printf '%s' '<REFRESH_TOKEN>' | npx wrangler secret put DROPBOX_REFRESH_TOKEN`
   (run from `letter-upload-worker/` directory)

### Rotating the Resend API key

1. Resend dashboard → **API Keys** → create a new one, same sending access
2. `printf '%s' '<NEW_KEY>' | npx wrangler secret put RESEND_API_KEY`
3. Also update the local file for the draft-ready email:
   `echo '<NEW_KEY>' > ~/.config/resend/api_key && chmod 600 ~/.config/resend/api_key`
4. Delete the old key in the Resend dashboard

---

## Running things manually (when automation is off or broken)

```bash
cd ~/Dropbox/admin_projects/aaronerlich.com

# Force one pipeline pass right now
bash scripts/letter-pipeline.sh
tail ~/Library/Caches/letter-pipeline.log

# Or run individual stages
python3 scripts/sync-letter-tokens-to-kv.py       # push active tokens to KV
python3 scripts/pull-letter-forms-from-kv.py      # pull submissions from KV
bash   scripts/sync-lors-dropbox-to-onedrive.sh   # mirror Dropbox → OneDrive
python3 scripts/watch-letter-requests.py          # draft for any uploaded entries

# Draft a specific student manually (bypassing the watcher queue)
python3 ~/.claude/skills/letter-draft/letter_draft.py --token <TOKEN>

# Retroactive test against an old student folder (useful for prompt tuning)
python3 ~/.claude/skills/letter-draft/letter_draft.py \
  --folder Undergrad_LORs/Ducharme_Tanner_2020 \
  --type ma \
  --no-write        # print to stdout, don't write docx
```

---

## Managing the launchd pipeline

```bash
# Check if the pipeline is loaded
launchctl list | grep letter-pipeline

# Install (one-time after clone, or after editing the plist)
cp scripts/com.aaronerlich.letter-pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist

# Disable (e.g., while traveling, or for debugging)
launchctl unload ~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist
cp scripts/com.aaronerlich.letter-pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.aaronerlich.letter-pipeline.plist

# Force-run right now (launchd will still tick every 5 min after)
launchctl kickstart -k gui/$(id -u)/com.aaronerlich.letter-pipeline

# Watch live
tail -f ~/Library/Caches/letter-pipeline.log
```

---

## Troubleshooting

### "Student submitted but I got no email"

1. Check the Worker got the POST: `npx wrangler tail` in `letter-upload-worker/`
   while the student retries.
2. Check Resend didn't bounce: https://resend.com/logs
3. Check McGill spam — Resend-sent mail from `noreply@aaronerlich.com`
   should not be spammed (SPF+DKIM are verified), but it happens.

### "I got the submission email but no draft-ready email"

The student-submission email comes from the Worker (cloud). The
draft-ready email comes from `letter_draft.py` on your laptop, fired by the
launchd pipeline. So:

1. Is your Mac on? The pipeline only runs while the laptop is awake.
2. `launchctl list | grep letter-pipeline` — is it loaded?
3. `tail ~/Library/Caches/letter-pipeline.log` — did stage 3 run? What did it say?
4. `ls -t ~/Library/CloudStorage/OneDrive-McGillUniversity/LORs/<folder>/` —
   did the rsync land the files? If not, is Dropbox synced?
5. If stage 3 ran but emailed failed, check `~/.config/resend/api_key` exists
   and matches the active key in your Resend dashboard.

### "The form returns 'This link has already been used'"

The token is single-use and transitions to `uploaded` on successful submit.
If the student closed the tab during upload and retried, they may hit this.

Fix: in Flask admin, delete the row, create a fresh request, send the new
URL. Don't reset state manually — clean-slate is safer.

### "The form gives 'Missing required file'"

All four slots (statement, transcript, CV, self-brief) must be filled. The
browser enforces this client-side too, so usually the student just needs to
attach the missing slot and resubmit.

### "Dropbox upload fails with 401 unauthorized"

Refresh token probably revoked (happens if you delete the Dropbox app or
revoke the authorization at dropbox.com/account/connected_apps). Redo the
OAuth refresh flow in the Credentials section above.

### "I'm getting 'Could not parse the programs data' errors"

This is unusual — means the form's inline JS didn't emit a valid JSON blob.
Have the student try again in a different browser (most likely cause is a
browser extension or blocker). If persistent, check `src/html.ts` for
recent edits to the inline `<script>`.

### "The pipeline is skipping stages silently"

Each stage has its own lockfile in `/tmp/`:

- `/tmp/lors-sync.lock`
- `/tmp/letter-watcher.lock`

Stale locks (process died without cleanup) block re-runs. The scripts check
whether the pid in the lock is alive and delete stale locks, but if
something's weird you can manually `rm /tmp/*.lock`.

---

## Public website integration

- `resources/letters.qmd` — static informational page. Describes the
  process, lead times, self-assessment, and what the four required
  documents are.
- `_quarto.yml` — "Letter of Rec" link in the navbar (line 14-15).
- `lab.qmd` (generated from `_data/lab.yml` via `scripts/build-lab.py`) —
  links alumni to the letters page so they know they can come back for a
  letter years later.

**The upload URL is never linked from the public site.** It's generated
per-student in the Flask admin, emailed by you, and expires on first use.
Search engines never see it; students who don't know you can't guess it
(24 chars of url-safe base64 = 144 bits of entropy).

---

## The `letter-draft` Claude skill

Lives at `~/.claude/skills/letter-draft/letter_draft.py`. Reads:

- Letter request metadata from `_data/letter-requests.yml` by token
- All files in the student's OneDrive folder (PDFs via `pdfplumber`,
  `.docx` via `python-docx`, `.xlsx` via `openpyxl`)
- 6 randomly-sampled style-reference letters from the same `(category,
  type)` combination in the existing corpus

Calls Claude Sonnet 4.6 by default (~$0.09/letter). Enforces
type-specific length constraints (MA = 1 page, PhD = unlimited, job = 1
page hard cap). Writes `<Last>_<First>_LOR_draft.docx` into the student
folder, transitions state to `draft_ready`, and fires the reminder email.

Override model per call with `--model opus` (higher quality, ~5× cost) or
`--local` (Ollama, free but slower and lower quality).

Full docs: `~/.claude/skills/letter-draft/SKILL.md`.

---

## What's NOT automated

Deliberate scope boundaries:

- **Sending the final letter.** All outbound mail to admissions committees
  is manual from Outlook. Automation never impersonates you.
- **Uploading to program portals.** You still manually paste/upload into
  each school's Interfolio / portal / etc. (See `_planning/` and GitHub
  issue #2 for the plan to auto-match portal-emailed links via a future
  Gmail MCP integration.)
- **Deletion of uploaded student materials.** Everything is archived
  indefinitely on OneDrive. If you need to purge, do it manually.
- **Multilingual drafts.** Letters are always in English regardless of
  whatever language the student or the program uses.
- **Public status dashboard.** Students can't check "where's my letter".
  Communicate status by reply email if asked.

---

## Changing things

- **Copy on the public letters page**: edit `resources/letters.qmd`,
  `quarto render resources/letters.qmd`, commit.
- **Form text or fields**: edit `letter-upload-worker/src/html.ts`,
  `cd letter-upload-worker && npx wrangler deploy`.
- **Notification email body**: `letter-upload-worker/src/email.ts` for
  submission notifications, `~/.claude/skills/letter-draft/letter_draft.py`
  (`send_draft_ready_email`) for draft-ready notifications.
- **Letter-drafting prompt**: `~/.claude/skills/letter-draft/letter_draft.py`
  (`build_system_prompt`). Iterate by running the skill against old
  folders with `--no-write` to compare against your historical letter.
- **What filename prefixes apply to uploaded files**: `SLOTS` array in
  `letter-upload-worker/src/index.ts`.

---

## Still-to-do

Planned improvements (open GitHub issues on `aserlich/aaronerlich.com`):

- **#2** Auto-process portal-emailed submission links via Apple Mail MCP.
  When a program emails you a link to upload the letter, match it against
  pending requests in the dashboard instead of you digging through your
  inbox.
- **Custom domain** `upload.aaronerlich.com` instead of the
  `*.workers.dev` URL. Requires moving `aaronerlich.com` DNS from
  Namecheap to Cloudflare (nameserver change + re-import of all records).
  Non-blocking — the workers.dev URL works fine.
- **Flask admin dashboard "draft quality" loop**. Show a diff of
  current-Claude-draft vs. your-edited-final, train the next draft on
  your edits.
