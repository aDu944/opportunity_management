"""
Outlook add-in (Phase 1): link an Outlook email to an Opportunity.

The task pane (public/outlook/v2/) calls these with an ERPNext OAuth bearer
token (see outlook_addin.py), so every call runs as the signed-in user:

* `lookup`        – Opportunities this email belongs to or probably belongs
                    to (already linked, same thread, sender's contact / lead,
                    same company domain), filtered by the user's permissions;
* `search`        – free-text Opportunity search for the manual pick;
* `link_email`    – the email becomes a Communication on the Opportunity
                    timeline. Keyed on the Message-ID: an email already in
                    ERPNext (e.g. pulled in by an Email Account) gets a timeline
                    link instead of a duplicate;
* `add_attachment`– one attachment, saved privately on the Communication and on
                    the Opportunity (Frappe shares the stored file by hash);
* `unlink_email`  – undo a wrong link.

Linking needs read access to the Opportunity (like adding a comment).
Errors a user can hit are OutlookError (HTTP 417), never 403: the pane treats
401/403 as an expired token. Pure logic lives in outlook_email_pure.
"""

import base64
import binascii
import json

import frappe
from frappe import _
from frappe.utils import now_datetime
from frappe.utils.data import convert_utc_to_system_timezone

from opportunity_management.opportunity_management import outlook_email_pure as P

OPP = "Opportunity"
CONV_FIELD = "custom_outlook_conversation_id"
PARTY_DOCTYPES = ("Customer", "Lead", "Prospect")
MAX_CANDIDATES = 300   # Opportunity names considered before permission filtering
MAX_RESULTS = 25
DOMAIN_CONTACT_LIMIT = 200
OPTIONAL_FIELDS = ("title", "customer_name", "custom_tender_no", "custom_tender_title",
                   "custom_inq_number", "custom_company", "contact_email")
SEARCH_FIELDS = ("title", "customer_name", "custom_tender_no", "custom_tender_title",
                 "custom_inq_number")
# Documents a sent ERPNext email can reference, and the field leading to the Opportunity.
REPLY_PARENT_FIELDS = {"Quotation": "opportunity", "Request for Quotation": "opportunity",
                       "Supplier Quotation": "opportunity"}


class OutlookError(frappe.ValidationError):
    """A request the panel should show as a message (not found, no access, …)."""


# ── helpers ──────────────────────────────────────────────────────────────────

def _json(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        frappe.throw(_("Malformed request"), OutlookError)


def _opp_fields():
    meta = frappe.get_meta(OPP)
    fields = ["name", "status", "party_name", "opportunity_from", "expected_closing", "modified"]
    return fields + [f for f in OPTIONAL_FIELDS if meta.has_field(f)]


def _has_conv_field():
    return frappe.get_meta("Communication").has_field(CONV_FIELD)


def _get_opp(name):
    if not name or not frappe.db.exists(OPP, name):
        frappe.throw(_("Opportunity {0} not found").format(name or ""), OutlookError)
    if not frappe.has_permission(OPP, "read", doc=name):
        frappe.throw(_("You don't have access to Opportunity {0}").format(name), OutlookError)
    return name


def _opp_row(name):
    rows = frappe.get_list(OPP, filters={"name": name}, fields=_opp_fields(), limit_page_length=1)
    return P.present(rows[0]) if rows else {"name": name}


def _comm_opps(comm_names):
    """Opportunities the given Communications are attached to (reference or
    timeline link)."""
    if not comm_names:
        return set()
    opps = set(frappe.get_all(
        "Communication",
        filters={"name": ["in", comm_names], "reference_doctype": OPP},
        pluck="reference_name",
    ))
    opps.update(frappe.get_all(
        "Communication Link",
        filters={"parenttype": "Communication", "parent": ["in", comm_names], "link_doctype": OPP},
        pluck="link_name",
    ))
    opps.discard(None)
    return opps


def _comms_by_message_id(mid):
    if not mid:
        return []
    return frappe.get_all("Communication", filters={"message_id": mid}, pluck="name", limit=20)


def _comm_linked_to(comm_name, opp):
    return opp in _comm_opps([comm_name])


def _party_opps(party_doctype, party_names):
    if not party_names:
        return []
    return frappe.get_all(
        OPP,
        filters={"opportunity_from": party_doctype, "party_name": ["in", list(party_names)]},
        pluck="name",
        order_by="modified desc",
        limit=MAX_CANDIDATES,
    )


def _contacts_parties(contact_names):
    """{party doctype: {names}} the given Contacts are linked to."""
    out = {}
    if not contact_names:
        return out
    for row in frappe.get_all(
        "Dynamic Link",
        filters={"parenttype": "Contact", "parent": ["in", list(contact_names)],
                 "link_doctype": ["in", PARTY_DOCTYPES]},
        fields=["link_doctype", "link_name"],
    ):
        out.setdefault(row.link_doctype, set()).add(row.link_name)
    return out


def _reply_opps(ids):
    """Opportunities behind the ERPNext-sent emails this one replies to: the
    sent Communication's own Opportunity link, or the Opportunity of the
    Quotation / RFQ / Supplier Quotation it was sent for."""
    if not ids:
        return set()
    comms = frappe.get_all("Communication", filters={"message_id": ["in", ids]},
                           fields=["name", "reference_doctype", "reference_name"], limit=100)
    opps = _comm_opps([c.name for c in comms])
    for c in comms:
        field = REPLY_PARENT_FIELDS.get(c.reference_doctype)
        if field and c.reference_name and frappe.get_meta(c.reference_doctype).has_field(field):
            opp = frappe.db.get_value(c.reference_doctype, c.reference_name, field)
            if opp:
                opps.add(opp)
    return opps


def _add_party_matches(found, parties, reason):
    for doctype, names in parties.items():
        for opp in _party_opps(doctype, names):
            found.append((opp, reason))


# ── endpoints ────────────────────────────────────────────────────────────────

@frappe.whitelist(methods=["GET", "POST"])
def lookup(sender=None, to=None, cc=None, mailbox=None, message_id=None, conversation_id=None,
           headers=None):
    """Opportunities for the open email, strongest match first. `headers` is
    the raw internet header block (only In-Reply-To / References are read)."""
    to, cc = _json(to, []), _json(cc, [])
    people = P.counterparts(sender, to, cc, mailbox)
    mid = P.normalize_message_id(message_id)
    found = []

    linked_comms = _comms_by_message_id(mid)
    for opp in _comm_opps(linked_comms):
        found.append((opp, "linked"))

    if conversation_id and _has_conv_field():
        thread = frappe.get_all("Communication", filters={CONV_FIELD: conversation_id},
                                pluck="name", limit=200)
        for opp in _comm_opps(thread):
            found.append((opp, "thread"))

    replied_to = P.reference_ids(P.header_value(headers, "In-Reply-To"),
                                 P.header_value(headers, "References"))
    for opp in _reply_opps(replied_to):
        found.append((opp, "reply"))

    if people:
        if frappe.get_meta(OPP).has_field("contact_email"):
            for opp in frappe.get_all(OPP, filters={"contact_email": ["in", people]},
                                      pluck="name", limit=MAX_CANDIDATES):
                found.append((opp, "contact_email"))

        contacts = set(frappe.get_all("Contact Email", filters={"email_id": ["in", people],
                                                                "parenttype": "Contact"},
                                      pluck="parent"))
        _add_party_matches(found, _contacts_parties(contacts), "contact")

        leads = set(frappe.get_all("Lead", filters={"email_id": ["in", people]}, pluck="name"))
        _add_party_matches(found, {"Lead": leads}, "lead")

        for domain in P.company_domains(people):
            like = f"%@{domain}"
            dom_contacts = set(frappe.get_all(
                "Contact Email", filters={"email_id": ["like", like], "parenttype": "Contact"},
                pluck="parent", limit=DOMAIN_CONTACT_LIMIT))
            _add_party_matches(found, _contacts_parties(dom_contacts - contacts), "domain")
            dom_leads = set(frappe.get_all("Lead", filters={"email_id": ["like", like]},
                                           pluck="name", limit=DOMAIN_CONTACT_LIMIT))
            _add_party_matches(found, {"Lead": dom_leads - leads}, "domain")

    merged = P.merge_candidates(found)
    rows = []
    if merged:
        # get_list applies the user's permissions; anything they can't read drops out here.
        rows = frappe.get_list(OPP, filters={"name": ["in", list(merged)]},
                               fields=_opp_fields(), limit_page_length=0)
    ranked = [P.present(r) for r in P.rank(rows, merged)[:MAX_RESULTS]]
    return {
        "people": people,
        "message_id": mid,
        "linked": [r for r in ranked if "linked" in r["reasons"]],
        "suggestions": [r for r in ranked if "linked" not in r["reasons"]],
        "can_create": bool(frappe.has_permission(OPP, "create")),
    }


@frappe.whitelist(methods=["GET", "POST"])
def search(q=None, limit=20):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    meta = frappe.get_meta(OPP)
    like = f"%{q}%"
    or_filters = [["name", "like", like], ["party_name", "like", like]]
    for f in SEARCH_FIELDS:
        if meta.has_field(f):
            or_filters.append([f, "like", like])
    rows = frappe.get_list(OPP, or_filters=or_filters, fields=_opp_fields(),
                           order_by="modified desc", limit_page_length=min(int(limit or 20), 50))
    return [P.present(r) for r in rows]


@frappe.whitelist(methods=["POST"])
def link_email(opportunity=None, email=None):
    """Put the email on the Opportunity's timeline. Returns
    {status: created | linked_existing | already, communication, opportunity}."""
    opp = _get_opp(opportunity)
    email = _json(email, {})
    try:
        values = P.communication_values(email, opp, email.get("mailbox"))
    except ValueError as e:
        frappe.throw(str(e), OutlookError)
    conv = values.pop("custom_outlook_conversation_id")
    if conv and _has_conv_field():
        values[CONV_FIELD] = conv

    existing = _comms_by_message_id(values["message_id"])
    for name in existing:
        if _comm_linked_to(name, opp):
            return {"status": "already", "communication": name, "opportunity": _opp_row(opp)}

    if existing:
        comm = frappe.get_doc("Communication", existing[0])
        if not comm.reference_doctype:
            comm.reference_doctype, comm.reference_name = OPP, opp
        else:
            comm.add_link(OPP, opp)
        if conv and _has_conv_field() and not comm.get(CONV_FIELD):
            comm.set(CONV_FIELD, conv)
        comm.save(ignore_permissions=True)
        status = "linked_existing"
    else:
        sent_at = P.parse_iso_utc(email.get("date"))
        values["communication_date"] = (
            convert_utc_to_system_timezone(sent_at).replace(tzinfo=None) if sent_at else now_datetime()
        )
        values["user"] = frappe.session.user
        comm = frappe.get_doc(values)
        comm.insert(ignore_permissions=True)
        status = "created"
    return {"status": status, "communication": comm.name, "opportunity": _opp_row(opp)}


@frappe.whitelist(methods=["POST"])
def add_attachment(communication=None, opportunity=None, filename=None, content_b64=None):
    """Save one attachment privately on the Communication and the Opportunity.
    Re-sending the same file is a no-op (matched by content hash)."""
    from frappe.core.api.file import get_max_file_size
    from frappe.core.doctype.file.utils import get_content_hash

    opp = _get_opp(opportunity)
    if not communication or not _comm_linked_to(communication, opp):
        frappe.throw(_("That email is not linked to Opportunity {0}").format(opp), OutlookError)
    try:
        content = base64.b64decode(content_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        frappe.throw(_("Attachment data is not valid base64"), OutlookError)
    if not content:
        frappe.throw(_("Attachment is empty"), OutlookError)
    limit = get_max_file_size()
    if len(content) > limit:
        frappe.throw(_("{0} is larger than the {1} MB upload limit")
                     .format(filename, limit // (1024 * 1024)), OutlookError)

    name = P.safe_filename(filename)
    digest = get_content_hash(content)
    saved = []
    for doctype, docname in (("Communication", communication), (OPP, opp)):
        existing = frappe.db.get_value("File", {"attached_to_doctype": doctype,
                                                "attached_to_name": docname,
                                                "content_hash": digest}, "name")
        if existing:
            saved.append({"doctype": doctype, "status": "already", "file": existing})
            continue
        f = frappe.get_doc({
            "doctype": "File",
            "file_name": name,
            "attached_to_doctype": doctype,
            "attached_to_name": docname,
            "is_private": 1,
            "content": content,
        })
        f.insert(ignore_permissions=True)
        saved.append({"doctype": doctype, "status": "saved", "file": f.name, "file_url": f.file_url})
    frappe.db.set_value("Communication", communication, "has_attachment", 1, update_modified=False)
    opp_file = next((s["file"] for s in saved if s["doctype"] == OPP), None)
    return {"file_name": name, "saved": saved, "opportunity_file": opp_file}


@frappe.whitelist(methods=["POST"])
def unlink_email(opportunity=None, message_id=None, communication=None):
    """Take the email (by Message-ID, or a Communication name) off this
    Opportunity. When nothing else references it and the caller created it,
    the Communication (and its own files) go too."""
    opp = _get_opp(opportunity)
    if not communication:
        for name in _comms_by_message_id(P.normalize_message_id(message_id)):
            if _comm_linked_to(name, opp):
                communication = name
                break
    if not communication or not _comm_linked_to(communication, opp):
        frappe.throw(_("That email is not linked to Opportunity {0}").format(opp), OutlookError)
    comm = frappe.get_doc("Communication", communication)
    if comm.owner != frappe.session.user and not frappe.has_permission(OPP, "write", doc=opp):
        frappe.throw(_("Only the person who linked this email, or someone who can edit "
                       "Opportunity {0}, can unlink it").format(opp), OutlookError)

    if comm.reference_doctype == OPP and comm.reference_name == opp:
        comm.reference_doctype = comm.reference_name = None
    comm.timeline_links = [l for l in comm.timeline_links
                           if not (l.link_doctype == OPP and l.link_name == opp)]
    other_links = [l for l in comm.timeline_links if l.link_doctype != "Contact"]
    if not comm.reference_doctype and not other_links and comm.owner == frappe.session.user:
        for f in frappe.get_all("File", filters={"attached_to_doctype": "Communication",
                                                 "attached_to_name": comm.name}, pluck="name"):
            frappe.delete_doc("File", f, ignore_permissions=True)
        frappe.delete_doc("Communication", comm.name, ignore_permissions=True)
        return {"status": "deleted"}
    comm.save(ignore_permissions=True)
    return {"status": "unlinked"}
