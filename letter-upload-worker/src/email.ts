// Resend email client — fires a notification to Aaron's McGill inbox when a
// student successfully uploads their letter-of-rec materials.
//
// One-time setup:
//   1. Create a Resend account at resend.com
//   2. Add aaronerlich.com as a domain; configure SPF, DKIM, DMARC records
//      per Resend's instructions on the Namecheap (or current DNS host) side
//   3. Create an API key, store as Worker secret RESEND_API_KEY
//   4. Set NOTIFICATION_EMAIL = aaron.erlich@mcgill.ca
//
// Once SPF/DKIM are verified, emails from noreply@aaronerlich.com reach
// McGill Outlook cleanly without spam-filter problems.

import type { LetterRequest } from "./tokens";

export type EmailEnv = {
  RESEND_API_KEY: string;
  NOTIFICATION_EMAIL: string;
};

const RESEND_URL = "https://api.resend.com/emails";
const FROM_ADDRESS = "Letter Intake <noreply@aaronerlich.com>";

export async function sendNotificationEmail(
  env: EmailEnv,
  request: LetterRequest,
  uploadedFiles: Array<{ name: string; size: number; slot?: string }>,
): Promise<void> {
  const subject = `Letter request: ${request.first_name} ${request.last_name} (${request.category})`;

  const methodLabel: Record<string, string> = {
    portal: "online portal (student has URL)",
    portal_emailed: "online portal (you'll receive a link by email)",
    email: "email",
    mail: "postal mail",
  };

  const programLines =
    (request.programs ?? [])
      .map((p) => {
        const header = `  • ${p.name} — ${p.institution}`;
        const when = p.deadline ? `\n      deadline: ${p.deadline}` : "";
        const where = p.city ? `\n      location: ${p.city}` : "";
        const how = p.submission_method
          ? `\n      submit via: ${methodLabel[p.submission_method] ?? p.submission_method}${p.portal_url ? ` — ${p.portal_url}` : ""}`
          : "";
        const waived = p.waived_right === true ? "\n      right to access: waived" : "";
        const notes = p.notes ? `\n      notes: ${p.notes}` : "";
        return header + when + where + how + waived + notes;
      })
      .join("\n") || "  (none listed)";

  const fileLines = uploadedFiles
    .map((f) => {
      const tag = f.slot ? `[${f.slot}] ` : "";
      return `  • ${tag}${f.name} (${formatSize(f.size)})`;
    })
    .join("\n");

  const folderDropbox = `$HOME/Dropbox/Apps/letter-upload-worker/LORs/${request.folder_path}`;
  const folderOneDrive = `$HOME/Library/CloudStorage/OneDrive-McGillUniversity/LORs/${request.folder_path}`;

  const body = `New letter-request materials uploaded.

Student:      ${request.first_name} ${request.last_name}
Category:     ${request.category}
Letter type:  ${request.letter_type}
Folder:       LORs/${request.folder_path}${request.returning ? " (returning student — folder reused)" : ""}

Files uploaded:
${fileLines}

Programs:
${programLines}

Next steps:

1. Open the folder in Finder (Dropbox — files land here first):
   open "${folderDropbox}"
   After the rsync mirror runs (launchd, every 5 min), they'll also be at:
   ${folderOneDrive}

2. Run the Claude skill to draft the letter:
   python3 ~/.claude/skills/letter-draft/letter_draft.py --token ${request.token}

3. Review the draft .docx, paste into your Poli Sci letterhead template,
   and send from Outlook. Mark the state in the Flask admin when sent.

— letter-upload-worker
`;

  const resp = await fetch(RESEND_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: FROM_ADDRESS,
      to: [env.NOTIFICATION_EMAIL],
      reply_to: env.NOTIFICATION_EMAIL,
      subject,
      text: body,
    }),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(
      `Resend failed (${resp.status}): ${text.slice(0, 300)}`,
    );
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
