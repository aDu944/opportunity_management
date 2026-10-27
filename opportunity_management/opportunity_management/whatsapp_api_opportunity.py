"""
"Create opportunity" from a WhatsApp / Messenger conversation.

Three whitelisted endpoints the customer info panel calls:

* `get_opportunity_defaults` — what the create sheet is prefilled with;
* `create_opportunity_from_conversation` — Customer / Lead reused (else a
  Lead created, the same way "Create lead" does), Opportunity inserted as
  Open with permissions enforced, conversation linked back;
* `parse_attachments_into_opportunity` — the chat's RFQ PDFs / photos read by
  `alkhora_erp.opportunity_parse.parse_files` into the Opportunity's items.

Errors a user can hit are 417s (`frappe.ValidationError` subclasses), not
403: the mobile client treats any 401/403 as a dead session (see
whatsapp_api_common.NotAssigneeError). The pure logic is in
`opportunity_pure`.
"""

import base64
import json

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

from opportunity_management.opportunity_management import inbox_channels as IC
from opportunity_management.opportunity_management import opportunity_pure as P
from opportunity_management.opportunity_management import whatsapp_crm
from opportunity_management.opportunity_management import whatsapp_hooks
from opportunity_management.opportunity_management.whatsapp_api_common import (
    _get_conv,
    _note,
    _require_inbox_access,
)
from opportunity_management.opportunity_management.whatsapp_api_crm import (
    insert_lead_for_conversation,
)
from opportunity_management.opportunity_management.whatsapp_api_inbox import get_conversation
from opportunity_management.opportunity_management.whatsapp_identity import display_label

OPP = "Opportunity"
PARSE_METHOD = "alkhora_erp.opportunity_parse.parse_files"
ATTACH_METHOD = "alkhora_erp.opportunity_parse.attach_parsed_files"
ATTACHMENT_LIMIT = 100
EXPECTED_CLOSING_DAYS = 7


class OpportunityError(frappe.ValidationError):
    """Create / parse refused (permission, already linked, bad name, …)."""


# ── helpers ──────────────────────────────────────────────────────────────────

def can_create_opportunity() -> bool:
    try:
        return bool(frappe.has_permission(OPP, "create"))
    except Exception:
        return False


def _require_create():
    if not can_create_opportunity():
        frappe.throw(_("You are not permitted to create Opportunities"), OpportunityError)


def _options(doctype, fieldname):
    df = frappe.get_meta(doctype).get_field(fieldname)
    return (P.split_options(df.options) if df else []), (df.default if df else None)


def _caller_company():
    user = frappe.session.user
    company = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "company")
    company = company or frappe.db.get_value("Employee", {"user_id": user}, "company")
    company = company or frappe.defaults.get_user_default("Company")
    if not company:
        first = frappe.get_all("Company", pluck="name", order_by="creation asc", limit_page_length=1)
        company = first[0] if first else None
    return company


def _responsible_parties():
    """Responsible Party records that resolve to a user (user_id, else the
    Employee's user, else an email that is a User): [{user, full_name,
    responsible_party}]."""
    rows = frappe.get_all(
        "Responsible Party", fields=["name", "user_id", "email", "employee", "display_name"],
        order_by="name asc", limit_page_length=500,
    )
    emp_users = {}
    emps = [r.employee for r in rows if r.employee and not r.user_id]
    if emps:
        emp_users = dict(frappe.get_all("Employee", filters={"name": ["in", emps]},
                                        fields=["name", "user_id"], as_list=True))
    out, seen = [], set()
    for r in rows:
        user = r.user_id or emp_users.get(r.employee)
        if not user and r.email and frappe.db.exists("User", r.email):
            user = r.email
        if not user or user in seen:
            continue
        seen.add(user)
        full = frappe.db.get_value("User", user, "full_name") or r.display_name or user
        out.append({"user": user, "full_name": full, "responsible_party": r.name})
    return out


def _rp_rows(users, parties):
    by_user = {p["user"].lower(): p["responsible_party"] for p in parties}
    rows, unknown = [], []
    for user in users:
        rp = by_user.get(user.lower()) or frappe.db.get_value(
            "Responsible Party", {"email": user}, "name")
        if rp:
            if rp not in [r["responsible_party"] for r in rows]:
                rows.append({"responsible_party": rp})
        else:
            unknown.append(user)
    if unknown:
        frappe.throw(_("No Responsible Party record for: {0}").format(", ".join(unknown)),
                     OpportunityError)
    if not rows:
        frappe.throw(_("Pick at least one responsible party"), OpportunityError)
    return rows


def conversation_attachments(conversation, limit=ATTACHMENT_LIMIT):
    """The conversation's PDF / image messages parse_files can read."""
    rows = frappe.db.sql(
        """SELECT m.name, m.content_type, m.attach,
                  (SELECT f.file_name FROM `tabFile` f WHERE f.file_url = m.attach
                   ORDER BY f.creation DESC LIMIT 1) AS file_name,
                  (SELECT f.file_size FROM `tabFile` f WHERE f.file_url = m.attach
                   ORDER BY f.creation DESC LIMIT 1) AS file_size
           FROM `tabWhatsApp Message` m
           WHERE m.custom_conversation = %(conv)s
             AND m.content_type IN ('document', 'image')
             AND m.attach IS NOT NULL AND m.attach != ''
           ORDER BY m.creation DESC
           LIMIT %(limit)s""",
        {"conv": conversation, "limit": int(limit)},
        as_dict=True,
    )
    return P.filter_attachments(rows)


def _party_display(party_type, party_name, conv):
    if party_type == "Customer":
        return frappe.db.get_value("Customer", party_name, "customer_name") or party_name
    if party_type == "Lead":
        return frappe.db.get_value("Lead", party_name, "lead_name") or party_name
    return display_label(conv.display_name, conv.phone, conv.get("wa_username"), "")


def _party_abr(party_type, party_name, series):
    """The abbreviation the name will carry; fixes / refuses an empty one
    BEFORE inserting when the series needs it. Opportunity.custom_abr is
    fetched from party_name.custom_abr ahead of naming, so the party is what
    must carry it."""
    if not P.series_uses_abr(series):
        return None
    if not frappe.get_meta(party_type).has_field("custom_abr"):
        frappe.throw(_("{0} has no Abbreviation field yet — run bench migrate").format(_(party_type)),
                     OpportunityError)
    abr = (frappe.db.get_value(party_type, party_name, "custom_abr") or "").strip()
    if abr:
        return abr
    if party_type == "Lead" and frappe.has_permission("Lead", "write", doc=party_name):
        frappe.db.set_value("Lead", party_name, "custom_abr", P.WA_ABR, update_modified=False)
        return P.WA_ABR
    frappe.throw(
        _("{0} {1} has no Abbreviation, which this naming series needs. Set it on the {0} "
          "first, or pick another series.").format(_(party_type), party_name),
        OpportunityError,
    )


# ── endpoints ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_opportunity_defaults(conversation):
    _require_inbox_access()
    conv = _get_conv(conversation)
    channel = IC.conv_channel(conv)
    party_type, party_name = P.resolve_party(conv.customer, conv.lead)
    display = _party_display(party_type, party_name, conv)

    series, series_default = _options(OPP, "naming_series")
    default_series = P.default_series(series, series_default)
    groups, _unused = _options(OPP, "custom_company")
    default_group = P.pick_default(groups, P.DEFAULT_COMPANY_GROUP)

    me = frappe.session.user
    parties = _responsible_parties()
    for p in parties:
        p["selected"] = p["user"] == me
    already = conv.opportunity if conv.opportunity and frappe.db.exists(OPP, conv.opportunity) else None

    return {
        "can_create": can_create_opportunity(),
        "already_linked": already,
        "party": {"type": party_type, "name": party_name, "display": display},
        "will_create_lead": party_type is None,
        "channel": channel,
        "naming_series": series,
        "default_naming_series": default_series,
        "companies": groups,
        "default_company_group": default_group,
        "company": _caller_company(),
        "responsible_parties": parties,
        "default_responsible_parties": [p["user"] for p in parties if p["selected"]],
        "attachments": conversation_attachments(conv.name),
        "title_suggestion": P.title_suggestion(display, channel),
        "expected_closing": add_days(nowdate(), EXPECTED_CLOSING_DAYS),
    }


@frappe.whitelist()
def create_opportunity_from_conversation(
    conversation, naming_series, custom_company, company=None, title=None,
    responsible_parties=None, notes=None, expected_closing=None,
):
    _require_inbox_access()
    conv = _get_conv(conversation)
    _require_create()
    if conv.opportunity and frappe.db.exists(OPP, conv.opportunity):
        frappe.throw(_("This conversation is already linked to Opportunity {0}")
                     .format(conv.opportunity), OpportunityError)

    series, _unused = _options(OPP, "naming_series")
    if naming_series not in series:
        frappe.throw(_("Unknown naming series: {0}").format(naming_series), OpportunityError)
    groups, _unused = _options(OPP, "custom_company")
    if groups and custom_company not in groups:
        frappe.throw(_("Unknown company group: {0}").format(custom_company), OpportunityError)
    company = company or _caller_company()
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("Company {0} not found").format(company or ""), OpportunityError)

    users = P.parse_list(responsible_parties) or [frappe.session.user]
    rp_rows = _rp_rows(users, _responsible_parties())

    channel = IC.conv_channel(conv)
    party_type, party_name = P.resolve_party(conv.customer, conv.lead)
    lead_created = False
    if party_type is None:
        lead = insert_lead_for_conversation(
            conv, source=P.lead_source_for_channel(channel), extra={"custom_abr": P.WA_ABR},
        )
        party_type, party_name, lead_created = "Lead", lead.name, True
    _party_abr(party_type, party_name, naming_series)

    meta = frappe.get_meta(OPP)
    display = _party_display(party_type, party_name, conv)
    values = {
        "doctype": OPP,
        "naming_series": naming_series,
        "opportunity_from": party_type,
        "party_name": party_name,
        "status": "Open",
        "company": company,
        "transaction_date": nowdate(),
        "custom_company": custom_company,
        "custom_tender_no": "0",
        "custom_responsible_party": rp_rows,
        "title": (title or "").strip() or P.title_suggestion(display, channel),
        "expected_closing": expected_closing or add_days(nowdate(), EXPECTED_CLOSING_DAYS),
        "source": P.lead_source_for_channel(channel),
    }
    if values["source"] and not frappe.db.exists("Lead Source", values["source"]):
        values.pop("source")
    status_df = meta.get_field("custom_agent_status")
    if status_df and "Received" in P.split_options(status_df.options):
        values["custom_agent_status"] = "Received"
    values = {k: v for k, v in values.items() if k == "doctype" or meta.has_field(k)}

    opp = frappe.get_doc(values)
    opp.insert()  # permissions enforced: this is a sales document

    if not P.is_well_formed_name(opp.name):
        bad = opp.name
        frappe.delete_doc(OPP, bad, ignore_permissions=True, force=True)
        frappe.throw(_("The Opportunity name came out malformed ({0}) and was discarded. Check "
                       "the party's Abbreviation and try again.").format(bad), OpportunityError)

    if (notes or "").strip():
        opp.add_comment("Comment", frappe.utils.escape_html(notes.strip()))

    whatsapp_crm.link_conversation_to_crm(conv, OPP, opp.name)
    if lead_created and conv.lead != party_name:
        frappe.db.set_value("WhatsApp Conversation", conv.name, "lead", party_name,
                            update_modified=False)
        conv.lead = party_name
    _note(conv.name, _("Opportunity {0} created by {1}").format(opp.name, frappe.session.user))
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return {
        "opportunity": opp.name,
        "lead_created": lead_created,
        "party_type": party_type,
        "party_name": party_name,
        "conversation": get_conversation(conv.name),
    }


def _load_file(url):
    name = frappe.db.get_value("File", {"file_url": url}, "name")
    if not name:
        frappe.throw(_("File {0} not found").format(url), OpportunityError)
    content = frappe.get_doc("File", name).get_content()
    if isinstance(content, str):
        content = content.encode()
    return content


@frappe.whitelist()
def parse_attachments_into_opportunity(conversation, opportunity, messages):
    _require_inbox_access()
    conv = _get_conv(conversation)
    _require_create()  # parse_files itself requires Opportunity create
    if not opportunity or opportunity != conv.opportunity:
        frappe.throw(_("Opportunity {0} is not the one linked to this conversation")
                     .format(opportunity or ""), OpportunityError)
    opp = frappe.get_doc(OPP, opportunity)
    if opp.docstatus != 0 or (opp.status or "Open") != "Open":
        frappe.throw(_("Opportunity {0} is {1}; items can only be added while it is Open")
                     .format(opp.name, opp.status), OpportunityError)
    if not frappe.has_permission(OPP, "write", doc=opp):
        frappe.throw(_("You are not permitted to edit Opportunity {0}").format(opp.name),
                     OpportunityError)

    wanted = P.parse_list(messages)
    if not wanted:
        frappe.throw(_("Pick at least one attachment"), OpportunityError)
    readable = {a["message"]: a for a in conversation_attachments(conv.name, limit=1000)}
    files, refused = [], []
    for name in wanted:
        att = readable.get(name)
        if not att:
            refused.append(name)
            continue
        url = frappe.db.get_value("WhatsApp Message", name, "attach")
        files.append({
            "filename": att["filename"],
            "content_type": att["content_type"],
            "data_b64": base64.b64encode(_load_file(url)).decode("ascii"),
        })
    if refused:
        frappe.throw(_("Only PDF and image attachments of this conversation can be parsed: {0}")
                     .format(", ".join(refused)), OpportunityError)

    if "alkhora_erp" not in frappe.get_installed_apps():
        frappe.throw(_("RFQ parsing is not installed"), OpportunityError)
    try:
        parse_files = frappe.get_attr(PARSE_METHOD)
    except Exception:
        frappe.throw(_("RFQ parsing is not installed"), OpportunityError)

    result = parse_files(files=json.dumps(files), target=OPP) or {}
    child_meta = frappe.get_meta(frappe.get_meta(OPP).get_field("items").options)
    added = 0
    for row in result.get("items") or []:
        opp.append("items", P.map_parsed_row(row, child_meta.has_field))
        added += 1
    if added:
        opp.save()  # permissions enforced
        try:  # the accepted source documents belong on the record (ERP's own flow)
            frappe.get_attr(ATTACH_METHOD)(opportunity=opp.name, files=json.dumps(files))
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Inbox opportunity: attach sources failed")
        _note(conv.name, _("{0} item(s) parsed into Opportunity {1} by {2}")
              .format(added, opp.name, frappe.session.user))
        whatsapp_hooks.publish_inbox_event("conversation", conv)
    return {"rows_added": added, "opportunity": opp.name, "parsed": P.parse_metadata(result)}
