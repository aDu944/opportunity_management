"""
Outlook add-in: create and assign an Opportunity from the open email.

Same rules as "Create opportunity" in the WhatsApp inbox
(whatsapp_api_opportunity), whose helpers are reused for the naming series,
company group, the caller's Company and the responsible parties:

* `create_defaults` – what the create form is prefilled with: Customer / Lead
                      candidates from the email's addresses, a "new lead from
                      sender" suggestion, series, groups, responsible parties;
* `search_parties`  – Customer / Lead search for the form's party picker;
* `create_opportunity_from_email` – reuses the picked Customer / Lead (or
                      creates the Lead), inserts the Opportunity as Open with
                      permissions enforced, and assigns it through the
                      `custom_responsible_party` table, which the existing
                      Opportunity hooks turn into notifications.

The panel then links the email (outlook_api.link_email) and saves the chosen
attachments exactly as for an existing Opportunity.
"""

import frappe
from frappe import _
from frappe.utils import add_days, escape_html, nowdate

from opportunity_management.opportunity_management import opportunity_pure as OP
from opportunity_management.opportunity_management import outlook_email_pure as P
from opportunity_management.opportunity_management.outlook_api import (
    OPP,
    OutlookError,
    _contacts_parties,
    _json,
)
from opportunity_management.opportunity_management.whatsapp_api_opportunity import (
    _caller_company,
    _options,
    _responsible_parties,
    _rp_rows,
)

PARTY_TYPES = ("Customer", "Lead")
EXPECTED_CLOSING_DAYS = 7
MAX_PARTIES = 10
DISPLAY_FIELDS = {"Customer": ("customer_name",), "Lead": ("lead_name", "company_name")}


def _require_create():
    if not frappe.has_permission(OPP, "create"):
        frappe.throw(_("You are not permitted to create Opportunities"), OutlookError)


def _has_abr_field(party_type):
    return frappe.get_meta(party_type).has_field("custom_abr")


def _party_row(party_type, name, reason=None):
    fields = list(DISPLAY_FIELDS[party_type])
    if _has_abr_field(party_type):
        fields.append("custom_abr")
    values = frappe.db.get_value(party_type, name, fields, as_dict=True) or {}
    parts = [values.get(f) for f in DISPLAY_FIELDS[party_type] if values.get(f)]
    display = " · ".join(dict.fromkeys(parts)) or name
    return {"type": party_type, "name": name, "display": display,
            "abr": values.get("custom_abr") or "", "reason": reason}


def _readable(party_type, name):
    try:
        return bool(frappe.has_permission(party_type, "read", doc=name))
    except Exception:
        return False


def _candidate_parties(people):
    """[(type, name, reason)] for the email's customer-side addresses."""
    found = []
    if not people:
        return found
    contacts = set(frappe.get_all("Contact Email",
                                  filters={"email_id": ["in", people], "parenttype": "Contact"},
                                  pluck="parent"))
    for pt, names in _contacts_parties(contacts).items():
        found += [(pt, n, "Sender's contact") for n in sorted(names)]
    found += [("Lead", n, "Sender's lead") for n in
              frappe.get_all("Lead", filters={"email_id": ["in", people]}, pluck="name")]
    for domain in P.company_domains(people):
        like = f"%@{domain}"
        dom = set(frappe.get_all("Contact Email",
                                 filters={"email_id": ["like", like], "parenttype": "Contact"},
                                 pluck="parent", limit=200)) - contacts
        for pt, names in _contacts_parties(dom).items():
            found += [(pt, n, "Same company domain") for n in sorted(names)]
    seen, out = set(), []
    for pt, name, reason in found:
        if pt in PARTY_TYPES and (pt, name) not in seen and _readable(pt, name):
            seen.add((pt, name))
            out.append((pt, name, reason))
        if len(out) >= MAX_PARTIES:
            break
    return out


# ── endpoints ────────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def create_defaults(sender=None, sender_name=None, to=None, cc=None, mailbox=None, subject=None):
    _require_create()
    people = P.counterparts(sender, _json(to, []), _json(cc, []), mailbox)
    parties = [_party_row(pt, n, reason) for pt, n, reason in _candidate_parties(people)]

    series, series_default = _options(OPP, "naming_series")
    groups, _unused = _options(OPP, "custom_company")
    me = frappe.session.user
    rps = _responsible_parties()
    for p in rps:
        p["selected"] = p["user"] == me
    return {
        "parties": parties,
        "new_lead": P.new_lead_suggestion(sender, sender_name)
        if P.direction(sender, mailbox) == "Received" else
        P.new_lead_suggestion(people[0] if people else "", ""),
        "naming_series": series,
        "default_naming_series": OP.default_series(series, series_default),
        "abr_placeholder": OP.ABR_PLACEHOLDER,
        "companies": groups,
        "default_company_group": OP.pick_default(groups, OP.DEFAULT_COMPANY_GROUP),
        "company": _caller_company(),
        "responsible_parties": rps,
        "title": P.title_from_subject(subject),
        "expected_closing": add_days(nowdate(), EXPECTED_CLOSING_DAYS),
        "can_create_lead": bool(frappe.has_permission("Lead", "create")),
    }


@frappe.whitelist(methods=["GET", "POST"])
def search_parties(q=None):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    out = []
    for pt, search_fields in (("Customer", ("name", "customer_name")),
                              ("Lead", ("name", "lead_name", "company_name", "email_id"))):
        names = frappe.get_list(pt, or_filters=[[f, "like", like] for f in search_fields],
                                pluck="name", order_by="modified desc", limit_page_length=8)
        out += [_party_row(pt, n) for n in names]
    return out


def _new_lead(data, abr):
    data = _json(data, {})
    lead_name = (data.get("lead_name") or "").strip()
    if not lead_name:
        frappe.throw(_("Enter the new lead's name"), OutlookError)
    email = P.normalize_email(data.get("email_id"))
    if email:
        existing = frappe.db.get_value("Lead", {"email_id": email}, "name")
        if existing:  # never two Leads for one address
            if not _readable("Lead", existing):
                frappe.throw(_("A lead with {0} already exists ({1}) and you don't have access "
                               "to it").format(email, existing), OutlookError)
            return existing, False
    # Unlike the WhatsApp flow, the Outlook form is open to every Opportunity creator,
    # and some roles here may create Opportunities but not Leads.
    if not frappe.has_permission("Lead", "create"):
        frappe.throw(_("You are not permitted to create Leads; pick an existing customer or lead"),
                     OutlookError)
    payload = {
        "doctype": "Lead",
        "lead_name": lead_name,
        "company_name": (data.get("company_name") or "").strip() or None,
        "email_id": email or None,
    }
    if frappe.db.exists("Lead Source", P.LEAD_SOURCE):
        payload["source"] = P.LEAD_SOURCE
    if abr and _has_abr_field("Lead"):
        payload["custom_abr"] = abr
    lead = frappe.get_doc({k: v for k, v in payload.items() if v is not None})
    lead.insert(ignore_permissions=True)  # create permission checked above
    return lead.name, True


def _ensure_abr(party_type, party_name, series, abr):
    """The INQ series embeds the party's abbreviation; set it from the form
    when the party has none (needs write access), else refuse."""
    if not OP.series_uses_abr(series):
        return
    if not _has_abr_field(party_type):
        frappe.throw(_("{0} has no Abbreviation field yet — run bench migrate").format(_(party_type)),
                     OutlookError)
    current = (frappe.db.get_value(party_type, party_name, "custom_abr") or "").strip()
    if current:
        return
    if not abr:
        frappe.throw(_("{0} {1} has no Abbreviation, which this naming series needs. Enter one.")
                     .format(_(party_type), party_name), OutlookError)
    if not frappe.has_permission(party_type, "write", doc=party_name):
        frappe.throw(_("{0} {1} has no Abbreviation and you can't edit it. Ask someone to set it, "
                       "or pick another series.").format(_(party_type), party_name), OutlookError)
    frappe.db.set_value(party_type, party_name, "custom_abr", abr, update_modified=False)


@frappe.whitelist(methods=["POST"])
def create_opportunity_from_email(
    naming_series=None, custom_company=None, title=None, party_type=None, party_name=None,
    new_lead=None, abr=None, responsible_parties=None, expected_closing=None, notes=None,
    tender_no=None,
):
    _require_create()
    series, _unused = _options(OPP, "naming_series")
    if naming_series not in series:
        frappe.throw(_("Unknown naming series: {0}").format(naming_series or ""), OutlookError)
    groups, _unused = _options(OPP, "custom_company")
    if groups and custom_company not in groups:
        frappe.throw(_("Pick a company group"), OutlookError)
    company = _caller_company()
    if not company or not frappe.db.exists("Company", company):
        frappe.throw(_("No Company found for you; set one on your Employee record"), OutlookError)

    abr = (abr or "").strip().upper()
    if abr and not P.valid_abr(abr):
        frappe.throw(_("Abbreviation must be 1-10 letters or digits"), OutlookError)

    users = OP.parse_list(responsible_parties) or [frappe.session.user]
    rp_rows = _rp_rows(users, _responsible_parties())

    lead_created = False
    if new_lead:
        party_type = "Lead"
        party_name, lead_created = _new_lead(new_lead, abr)
    elif party_type in PARTY_TYPES and party_name and frappe.db.exists(party_type, party_name):
        if not _readable(party_type, party_name):
            frappe.throw(_("You don't have access to {0} {1}").format(_(party_type), party_name),
                         OutlookError)
    else:
        frappe.throw(_("Pick a customer or lead, or create a new lead"), OutlookError)
    _ensure_abr(party_type, party_name, naming_series, abr)

    meta = frappe.get_meta(OPP)
    values = {
        "doctype": OPP,
        "naming_series": naming_series,
        "opportunity_from": party_type,
        "party_name": party_name,
        "status": "Open",
        "company": company,
        "transaction_date": nowdate(),
        "custom_company": custom_company,
        "custom_tender_no": (tender_no or "").strip() or "0",
        "custom_responsible_party": rp_rows,
        "title": (title or "").strip()[:140] or None,
        "expected_closing": expected_closing or add_days(nowdate(), EXPECTED_CLOSING_DAYS),
        "source": P.LEAD_SOURCE if frappe.db.exists("Lead Source", P.LEAD_SOURCE) else None,
    }
    status_df = meta.get_field("custom_agent_status")
    if status_df and "Received" in OP.split_options(status_df.options):
        values["custom_agent_status"] = "Received"
    values = {k: v for k, v in values.items()
              if k == "doctype" or (meta.has_field(k) and v is not None)}

    opp = frappe.get_doc(values)
    opp.insert()  # permissions enforced; validate hooks set notification recipients

    if not OP.is_well_formed_name(opp.name):
        bad = opp.name
        frappe.delete_doc(OPP, bad, ignore_permissions=True, force=True)
        frappe.throw(_("The Opportunity name came out malformed ({0}) and was discarded. Check "
                       "the party's Abbreviation and try again.").format(bad), OutlookError)

    if (notes or "").strip():
        opp.add_comment("Comment", escape_html(notes.strip()))
    return {"opportunity": opp.name, "party_type": party_type, "party_name": party_name,
            "lead_created": lead_created}
