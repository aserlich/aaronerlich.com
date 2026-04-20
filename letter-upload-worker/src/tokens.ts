// Token storage + lookup for the upload pipeline.
//
// Source of truth is _data/letter-requests.yml in the website repo.
// scripts/sync-letter-tokens-to-kv.py pushes active tokens (state=pending_upload)
// into this Worker's KV namespace. The Worker only reads.
//
// KV layout:
//   key   = <token>
//   value = JSON-serialized LetterRequest

export type Program = {
  name: string;
  institution: string;
  city?: string;
  deadline: string;                    // ISO date YYYY-MM-DD
  submission_method: "portal" | "portal_emailed" | "email" | "mail";
  portal_url?: string;
  waived_right?: boolean;
  notes?: string;
};

export type LetterState =
  | "pending_upload"
  | "uploaded"
  | "drafting"
  | "draft_ready"
  | "approved"
  | "sent"
  | "closed";

export type StateLogEntry = {
  state: LetterState;
  at: string; // ISO timestamp
};

export type LetterRequest = {
  token: string;
  last_name: string;
  first_name: string;
  first_year: string | number;
  category: string;
  letter_type: "ma" | "phd" | "job_or_internship";
  folder_path: string;
  programs?: Program[];
  state: LetterState;
  created: string;
  returning?: boolean;
  state_log?: StateLogEntry[];
};

export async function lookupToken(
  kv: KVNamespace,
  token: string,
): Promise<LetterRequest | null> {
  // Minimum length sanity check — our tokens are ~24 chars url-safe base64
  if (!token || token.length < 16 || token.length > 64) return null;
  if (!/^[A-Za-z0-9_-]+$/.test(token)) return null;

  const raw = await kv.get(token);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as LetterRequest;
  } catch {
    return null;
  }
}

export async function markTokenState(
  kv: KVNamespace,
  token: string,
  newState: LetterRequest["state"],
): Promise<void> {
  const raw = await kv.get(token);
  if (!raw) return;
  try {
    const req = JSON.parse(raw) as LetterRequest;
    req.state = newState;
    await kv.put(token, JSON.stringify(req));
  } catch {
    // ignore — token remains in its previous state
  }
}
