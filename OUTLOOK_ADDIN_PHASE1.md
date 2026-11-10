# Outlook Add-in — Phase 1 (link emails to Opportunities)

Builds on [Phase 0](OUTLOOK_ADDIN_PHASE0.md) (sign-in with ERPNext login, OAuth + PKCE).
The panel now lets a user, from any email in Outlook:

- see the Opportunities this email **is linked to**, with **Unlink**;
- see **suggested** Opportunities, each with the reason it matched;
- **search** all Opportunities (number, customer, title, tender no./title, INQ number);
- **Link** the email: it appears on the Opportunity's timeline as an email;
- optionally save its **attachments** privately on the Opportunity (and on the email record).

The pane can be **pinned** and follows the user from email to email.

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
| `opportunity_management/opportunity_management/outlook_create.py` | `create_defaults`, `search_parties`, `create_opportunity_from_email` |
| `opportunity_management/public/outlook/v4/` | The panel (`taskpane.html`, `app.js`, `auth.js`, `taskpane.css`), callback, icons, `manifest.xml` |
| `opportunity_management/opportunity_management/tests/test_outlook_email_pure.py` | 20 bench-free tests |

`v1/` stays in place so the Phase 0 manifest keeps working until it is replaced. `v2` and `v3` (already installed by users) also stay, unchanged, so old manifests keep working and a rollback never hits cached 404s. Never edit or delete a published folder.

## Deploying (self-hosted)

Production: Hetzner, bench `/home/frappe/frappe-bench`, site `erp.local`,
host `https://bms.alkhora.com`, git remote **`upstream`** (fetch refspec tracks `main` only).

```bash
cd /home/frappe/frappe-bench
bench --site erp.local backup
cd apps/opportunity_management
git fetch upstream feature/outlook-addin-phase1:feature/outlook-addin-phase1
git checkout feature/outlook-addin-phase1
cd /home/frappe/frappe-bench
bench --site erp.local migrate     # expect "Outlook add-in v4: OAuth Client ... has the v4 redirect"
bench build --app opportunity_management
bench --site erp.local clear-cache
sudo supervisorctl restart frappe-bench-web:
```

Rollback: `git checkout feature/outlook-addin-phase0` (or `main`), then migrate / build /
clear-cache / restart. The custom field and the extra redirect URI are harmless to leave.

## Install / update in Outlook

Download `https://bms.alkhora.com/assets/opportunity_management/outlook/v4/manifest.xml`
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
