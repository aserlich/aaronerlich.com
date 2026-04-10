# letter-upload-worker

Cloudflare Worker that receives student letter-of-recommendation materials via a secret token-gated form and writes them into Aaron's OneDrive LORs archive, then sends a notification to his McGill inbox.

**Scaffolding only — not deployed yet.** Follow the deployment steps below when you're ready to go live. The Flask admin at `scripts/cv_admin.py` already generates tokens and stores them in `_data/letter-requests.yml`; once deployed, `scripts/sync-letter-tokens-to-kv.py` pushes those tokens into the Worker's KV namespace so the upload URLs actually work.

## Architecture

```
Student browser
    │
    ▼
https://upload.aaronerlich.com/upload/<token>    ← Cloudflare Worker
    │                                              ├─ lookupToken (KV)
    │                                              ├─ uploadToOneDrive (MS Graph)
    │                                              └─ sendNotificationEmail (Resend)
    │
    ├──→ OneDrive  LORs/<category>/<LastName_FirstName_Year>/*
    └──→ aaron.erlich@mcgill.ca  (notification email)
```

## One-time setup (~2 hours across 3 external services)

### 1. Cloudflare account + Worker

```bash
cd letter-upload-worker
npm install
npx wrangler login
npx wrangler kv namespace create TOKENS
# Paste the returned id into wrangler.toml under [[kv_namespaces]]
```

### 2. Microsoft Entra app (for OneDrive writes via Graph API)

1. https://entra.microsoft.com → Applications → App registrations → **New registration**
2. Name: `letter-upload-worker`
3. Supported account types: **Accounts in this organizational directory only** (McGill tenant)
4. Redirect URI: `http://localhost:4000/callback` (for the one-time refresh-token capture)
5. After creation, note the **Application (client) ID** and **Directory (tenant) ID**
6. **Certificates & secrets** → **New client secret** — note the **Value**
7. **API permissions** → **Add permission** → **Microsoft Graph** → **Delegated permissions**:
   - `Files.ReadWrite`
   - `offline_access`
8. Click **Grant admin consent** (or ask McGill IT to consent)

Obtain a refresh token (one-time, interactive). See "Refresh token capture" below for a ready-made Node script.

### 3. Resend account (for notification email)

1. Create account at https://resend.com
2. Domains → **Add domain** → `aaronerlich.com`
3. Add the SPF + DKIM records Resend shows you to your DNS provider (wherever `aaronerlich.com` is managed)
4. Wait for verification (~5 minutes)
5. API Keys → **Create API Key** → **Sending access only**

### 4. Store secrets in the Worker

```bash
npx wrangler secret put GRAPH_CLIENT_ID          # Entra Application (client) ID
npx wrangler secret put GRAPH_CLIENT_SECRET      # Entra client secret Value
npx wrangler secret put GRAPH_TENANT_ID          # Entra Directory (tenant) ID
npx wrangler secret put GRAPH_REFRESH_TOKEN      # from step 2
npx wrangler secret put RESEND_API_KEY           # from step 3
npx wrangler secret put NOTIFICATION_EMAIL       # aaron.erlich@mcgill.ca
```

### 5. Deploy and point DNS

```bash
npx wrangler deploy
```

Add a custom domain via the Cloudflare dashboard:
1. Workers & Pages → `letter-upload-worker` → Settings → Domains & Routes
2. **Add Custom Domain** → `upload.aaronerlich.com`
3. Follow the DNS instructions (add a CNAME at your DNS provider)
4. Wait 5–10 minutes for SSL cert provisioning

### 6. Configure the token sync script

```bash
mkdir -p ~/.config/cloudflare
cat > ~/.config/cloudflare/letter-worker.env << 'EOF'
CLOUDFLARE_ACCOUNT_ID=<from dashboard URL>
CLOUDFLARE_KV_NAMESPACE_ID=<from `wrangler kv namespace create TOKENS`>
CLOUDFLARE_API_TOKEN=<create at dashboard → My Profile → API Tokens; scope Workers KV:Edit>
EOF
chmod 600 ~/.config/cloudflare/letter-worker.env
```

### 7. (Optional) Hook sync into Flask admin

Edit `scripts/cv_admin.py` — in `letters_new()` after `save_letters(data)`:

```python
subprocess.run(
    [sys.executable, str(REPO / "scripts" / "sync-letter-tokens-to-kv.py")],
    cwd=str(REPO),
)
```

Every new letter request auto-syncs to KV. Or run the script manually after creating a request.

## Local development

```bash
npx wrangler dev    # runs at http://localhost:8787
npx wrangler tail   # tail production logs
```

Put secrets for local dev in `.dev.vars` (gitignored).

## End-to-end test after deployment

1. Flask admin → **New letter request** → fill form → submit
2. Copy the generated upload URL
3. `python3 scripts/sync-letter-tokens-to-kv.py`
4. Open URL in incognito browser
5. Upload test files
6. Verify:
   - Files in `LORs/<category>/<LastName_FirstName_Year>/` on OneDrive
   - Email arrives at `aaron.erlich@mcgill.ca`
   - Flask admin shows state `uploaded`

## Refresh token capture (one-time helper)

```javascript
// save as capture-refresh-token.mjs, run: npm install @azure/msal-node && node capture-refresh-token.mjs
import { PublicClientApplication } from "@azure/msal-node";
import http from "http";
import { URL } from "url";

const CLIENT_ID = "YOUR_ENTRA_APP_CLIENT_ID";
const TENANT_ID = "YOUR_MCGILL_TENANT_ID";
const REDIRECT = "http://localhost:4000/callback";

const pca = new PublicClientApplication({
  auth: { clientId: CLIENT_ID, authority: `https://login.microsoftonline.com/${TENANT_ID}` },
});

const authUrl = await pca.getAuthCodeUrl({
  scopes: ["Files.ReadWrite", "offline_access"],
  redirectUri: REDIRECT,
});
console.log("Open in browser:", authUrl);

http.createServer(async (req, res) => {
  const url = new URL(req.url, REDIRECT);
  const code = url.searchParams.get("code");
  if (code) {
    await pca.acquireTokenByCode({
      code,
      scopes: ["Files.ReadWrite", "offline_access"],
      redirectUri: REDIRECT,
    });
    const cache = pca.getTokenCache().serialize();
    console.log("\n=== TOKEN CACHE ===\n");
    console.log(cache);
    console.log("\nExtract the refreshToken field and run:");
    console.log("  npx wrangler secret put GRAPH_REFRESH_TOKEN");
    res.end("OK — check terminal");
    process.exit(0);
  }
}).listen(4000, () => console.log("Waiting on :4000"));
```

## Security notes

- **Tokens are single-use**: Worker marks them `uploaded` on success; further GETs return 410 Gone.
- **Token entropy**: 24 chars of url-safe base64 = 144 bits. Brute force infeasible.
- **File limits**: `MAX_FILE_SIZE` = 50 MB/file, `MAX_FILES` = 12/upload. Enforced server-side.
- **No public index**: `/` returns a health check JSON, not an index page. Search engines see nothing.
- **Outbound email is notification only**: the Worker never sends AS Aaron. Actual letters to programs go through Outlook manually.

## TODO for production hardening

- [ ] Add Cloudflare Turnstile to the upload form
- [ ] Per-IP rate limiting via Cloudflare rules
- [ ] Auto-hook `sync-letter-tokens-to-kv.py` into Flask `letters_new` handler
- [ ] Retry logic around Graph API chunked upload for flaky networks
- [ ] Virus scan step (ClamAV via Cloudflare queue or AWS Lambda)
