# Outlook Add-in — Phase 1 (link emails to Opportunities)

Builds on [Phase 0](OUTLOOK_ADDIN_PHASE0.md) (sign-in with ERPNext login, OAuth + PKCE).
The panel now lets a user, from any email in Outlook:

- see the Opportunities this email **is linked to**, with **Unlink**;
- see **suggested** Opportunities, each with the reason it matched;
- **search** all Opportunities (number, customer, title, tender no./title, INQ number);
- **Link** the email: it appears on the Opportunity's timeline as an email;
- optionally save its **attachments** privately on the Opportunity (and on the email record).

The pane can be **pinned** and follows the user from email to email.

## v6 additions (install once from here on)

- **Install once, auto-update** — the manifest now lives in the stable folder
  `public/outlook/app/` (`manifest.xml`, `taskpane.html` loader, `auth-callback.html`, icons). The loader
  asks `get_config` for `asset_version` and loads `outlook/<version>/` (`body.html`, `taskpane.css`,
  `auth.js`, `app.js`). A new version = a new folder + bumping `ASSET_VERSION`; nobody reinstalls.
  **Files in `app/` are never edited after publishing** (year-long edge cache); if the manifest itself
  must change (new permission / button), that is a new stable folder and one more install.
- **Share page** — `https://bms.alkhora.com/outlook` (`www/outlook.html`): a download button for the
  stable manifest and the install steps. Send colleagues this link.
- **Opportunity number in the subject** — in a reply / forward / new email, the same button opens the
  panel in compose mode: suggested Opportunities (thread, recipients, domain rules) or search, then
  **Add to subject** appends `[INQ-577-IC-2041-26]` once. Customers' replies keep it, and the lookup now
  treats a number in the subject as the strongest match (`INQ-` / `ER-` / `FB-` names, mixed case,
  spaces and extra hyphens included; only names that exist count).
- **Email Domain Rule** (new DocType) — "emails from this domain always suggest this Customer/Lead",
  shown with its reason ("Company rule for this email domain"), not hiding other candidates. Seeded:
  `badraproject.com` → **IC LLC Badra Petroleum** (Ahmed, 2026-11-10). Sub-domains match; public mail
  domains are refused. Sales Managers can add more under *Email Domain Rule*.
- **Tags** — Outlook categories don't exist on IMAP mailboxes (one.com). The pane now probes once and
  skips tagging quietly there, and never claims "tagged" when it wasn't. A **✓ Linked to …** line under
  the subject shows the link at a glance instead.

## v5 additions

- **Parse the email text** — "Include the email text when parsing items" (on by default) sends the
  linked email as `email.txt` (text/plain: From/To/Cc/Date/Subject, then the body as text, tables
  kept as `cell | cell` rows) along with the chosen files. Reading it needs the agents-host change
  (text support in `maya._blocks_for`); until that is live the parser lists `email.txt` under
  "skipped" and the pane says only the files were parsed. **Parse items** works with the email
  text alone (no attachments needed).
- **Add files from your computer** — "+ Add files from your computer" in the files box (email view
  and create form). Those files are saved to the **Opportunity only** (`outlook_api.add_file`,
  needs write access), can be ticked for parsing like attachments, and stay in the list while you
  stay on the same email.

## v4 additions

- **Responsible party** — the create form's assignee list is now every **Responsible Party**
  record (by its display name), exactly what the Opportunity's own field offers — including
  people with no ERPNext user. The caller's own record is pre-selected.
- **Parse items** — like the desk's **Parse Items from File** (`alkhora_erp.opportunity_parse.parse_files`,
  Maya on the agents host). From a linked Opportunity (**Parse items**) or right after creating
  one (checkbox), the selected PDF / image / .xlsx / .xlsm / .docx attachments (max 15 MB together;
  .xls/.doc are refused by the parser) are saved to the Opportunity and parsed **in the background**
  (`outlook_parse.py`: a parse can take minutes, longer than Cloudflare's ~100 s request limit;
  the pane polls). Then **Review parsed lines**: tick the lines to keep (low-confidence lines are
  flagged), **Add selected** appends them to the items (never replaces), sets the title only if
  empty, and appends conditions + notes to the tender notes without duplicates. Unlike the desk
  form, the Opportunity is saved (permissions enforced). Needs Opportunity **create** (the parser's
  own check) and **write** on that Opportunity. The email body itself is not parsed — the parser
  does not accept plain text yet (an agents-host change).

## v3 additions

- **Create & assign** — "+ Create Opportunity from this email" opens a form: Customer / Lead
  (the sender's contacts and leads are offered first, any other can be searched, or a **new
  Lead** is made from the sender), abbreviation (only when the INQ series needs one and the
  party has none), title (from the subject, without RE:/FW:), company group, naming series,
  tender no., expected closing, **Assign to** (responsible parties — the existing Opportunity
  hooks send the assignment emails), notes. Same rules as "Create opportunity" in the WhatsApp
  inbox (`outlook_create.py` reuses its helpers). The email is then linked and the chosen files saved.
- **Choose attachments** — every attachment has its own checkbox (Select all / none);
  only ticked files are saved. A linked Opportunity also gets a **Save files** button.
- **Outlook tags** — a linked email gets an Outlook **category named after the Opportunity**
  (e.g. `ER-022-25`, blue), so it shows in the message list and can be searched/filtered.
  Unlink removes it. Opening an email someone else linked tags your copy too. This needs the
  manifest's `ReadWriteMailbox` permission (to add the category to your master list).
- Lead Source **Email** is created and set on Leads / Opportunities made from Outlook.

## How suggestions are found (strongest first)

| Reason | Meaning |
|---|---|
| This email is linked | A Communication with this Message-ID is already on the Opportunity |
| Same email thread | Another email of this Outlook thread was linked to it |
| Reply to an email sent from ERPNext | The email's `In-Reply-To` / `References` point at an email ERPNext sent (11k+ stored) for the Opportunity, or for a Quotation / RFQ / Supplier Quotation of it |
| Sender's contact / lead | The customer-side address belongs to a Contact (linked Customer / Lead / Prospect) or a Lead |
| Opportunity contact | The address is the Opportunity's `contact_email` |
| Same company domain | Another Contact / Lead on the same (non-Gmail etc.) domain |

"Customer side" = the sender of a received email, the recipients of a sent one; anyone on
the user's own domain (`alkhora.com`) is ignored. Results are filtered by the user's own
ERPNext permissions; open Opportunities are listed before Lost / Closed / Won ones.

## What a link writes

- One **Communication** (`communication_medium = Email`, `Received` or `Sent`) with
  `reference_doctype = Opportunity`, the Outlook Message-ID (without `< >`, Frappe's format),
  subject, sender, To/Cc, original date and HTML body. Frappe's own sanitising applies.
- If the same Message-ID is already in ERPNext (a colleague linked it, or it is on another
  document), the existing record gets a timeline link instead of a duplicate.
- `Communication.custom_outlook_conversation_id` — new hidden, indexed field holding the Outlook
  thread ID, so later emails in the thread are suggested.
- Attachments: each file is saved **private** on the Communication and on the Opportunity
  (Frappe stores the bytes once). Inline images and cloud links are skipped; files over the
  site limit (25 MB, Frappe default) are skipped. Re-linking does not duplicate files.

Standard Frappe behaviour to know: linking a **received** email to an Opportunity whose status
is `Replied` sets it back to `Open` (no Opportunity currently uses `Replied`).

Who can do what: anyone who can **read** an Opportunity can link an email to it (like
commenting). **Unlink** is allowed for the person who linked it or anyone who can edit the
Opportunity; if nothing else references the email afterwards, its record (and its own
attachment copies) is deleted. Files saved on the Opportunity stay.

## Files

| File | Purpose |
|---|---|
| `opportunity_management/opportunity_management/outlook_api.py` | `lookup`, `search`, `link_email`, `add_attachment`, `unlink_email` |
| `opportunity_management/opportunity_management/outlook_email_pure.py` | Address / Message-ID / header parsing, ranking, Communication values (unit-tested) |
| `opportunity_management/opportunity_management/outlook_addin.py` | + `ensure_conversation_field()`, `get_config()` now returns `max_file_size` |
| `opportunity_management/patches/setup_outlook_addin_phase1.py` | Creates the conversation field; adds the current redirect URI to the OAuth Client |
| `opportunity_management/patches/setup_outlook_addin_v3.py` | v3 redirect URI, conversation field, Lead Source "Email" |
| `opportunity_management/opportunity_management/outlook_parse.py` | `start_parse` (background job), `get_parse`, `add_parsed_items` |
| `opportunity_management/patches/setup_outlook_addin_v4.py` | v4 redirect URI |
| `opportunity_management/patches/setup_outlook_addin_v5.py` | v5 redirect URI |
| `opportunity_management/opportunity_management/outlook_create.py` | `create_defaults`, `search_parties`, `create_opportunity_from_email` |
| `opportunity_management/public/outlook/v5/` | The panel (`taskpane.html`, `app.js`, `auth.js`, `taskpane.css`), callback, icons, `manifest.xml` |
| `opportunity_management/opportunity_management/tests/test_outlook_email_pure.py` | 20 bench-free tests |

`v1/` stays in place so the Phase 0 manifest keeps working until it is replaced. `v2`, `v3` and `v4` (published, possibly installed) also stay, unchanged, so old manifests keep working and a rollback never hits cached 404s. Never edit or delete a published folder.

## Deploying (self-hosted)

Production: Hetzner, bench `/home/frappe/frappe-bench`, site `erp.local`,
host `https://bms.alkhora.com`, git remote **`upstream`** (fetch refspec tracks `main` only).

```bash
cd /home/frappe/frappe-bench
bench --site erp.local backup
cd apps/opportunity_management
git fetch upstream feature/outlook-addin:feature/outlook-addin
git checkout feature/outlook-addin
cd /home/frappe/frappe-bench
bench --site erp.local migrate     # expect "Outlook add-in v6: ... stable app/ redirect" and "Email Domain Rule badraproject.com -> ..."
bench build --app opportunity_management
bench --site erp.local clear-cache
sudo supervisorctl restart frappe-bench-web:
```

Rollback: `git checkout feature/outlook-addin-phase0` (or `main`), then migrate / build /
clear-cache / restart. The custom field and the extra redirect URI are harmless to leave.

## Install / update in Outlook

Open `https://bms.alkhora.com/outlook` and click **Download the add-in file** (stable manifest `outlook/app/manifest.xml`)
(Cmd/Ctrl+S), then **Add from file** as in Phase 0. It has the same add-in ID, so it replaces
the Phase 0 test add-in (if Outlook complains, remove the old one first). Sign-in carries over.

## Test checklist

1. A received email from a known customer → suggestions appear with reasons.
2. A customer reply to a quotation emailed from ERPNext → "Reply to an email sent from ERPNext".
3. Link with attachments → email on the Opportunity timeline, files in its attachments sidebar.
4. Open the same email again → shown under **Linked to**; Link again elsewhere → both.
5. Next email in the same thread → "Same email thread" suggestion.
6. Sent email (Sent Items) → matched on the recipients, saved as `Sent`.
7. Search by Opportunity no., customer, tender no., INQ number.
8. Unlink → gone from the timeline.
9. Pin the pane, click through several emails → it follows.
