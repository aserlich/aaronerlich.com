// Program-row validation and normalization for the upload form.
//
// The browser submits a JSON blob in the `programs_json` hidden field; each
// row is a Record<string, unknown>. These helpers coerce the strings,
// trim whitespace, and reject rows that are missing required fields or
// contain obviously bad data (non-ISO dates, non-URL portal links, etc.).

import type { Program } from "./tokens";

const SUBMISSION_METHODS = new Set([
  "portal",
  "portal_emailed",
  "email",
  "mail",
]);

export function normalizeProgram(raw: unknown): Partial<Program> {
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;

  const str = (k: string): string | undefined => {
    const v = r[k];
    if (typeof v !== "string") return undefined;
    const trimmed = v.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  };

  const method = str("submission_method");
  const out: Partial<Program> = {
    name: str("name"),
    institution: str("institution"),
    city: str("city"),
    deadline: str("deadline"),
    submission_method:
      method && SUBMISSION_METHODS.has(method)
        ? (method as Program["submission_method"])
        : undefined,
    portal_url: str("portal_url"),
    notes: str("notes"),
    waived_right: r.waived_right === true || r.waived_right === "1" || r.waived_right === "true",
  };

  return out;
}

export function isValidProgram(p: Partial<Program>): p is Program {
  if (!p.name || !p.institution || !p.deadline || !p.submission_method) {
    return false;
  }
  // Deadline must look like YYYY-MM-DD (HTML5 date input format).
  if (!/^\d{4}-\d{2}-\d{2}$/.test(p.deadline)) return false;
  // Cheap date validity check — Date.parse returns NaN for nonsense.
  if (Number.isNaN(Date.parse(p.deadline))) return false;
  // Portal URL required when submission method is "portal"; must be a valid URL.
  if (p.submission_method === "portal") {
    if (!p.portal_url) return false;
    try {
      const u = new URL(p.portal_url);
      if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    } catch {
      return false;
    }
  }
  return true;
}

export function parsePrograms(raw: string | null | undefined): Program[] | null {
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!Array.isArray(parsed)) return null;
  const normalized = parsed.map(normalizeProgram);
  const valid = normalized.filter(isValidProgram);
  // If the student submitted rows but none validated, that's a form error —
  // signal it by returning an empty array rather than null.
  return valid;
}
