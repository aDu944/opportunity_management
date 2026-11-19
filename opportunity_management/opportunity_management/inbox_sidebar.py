"""
Frappe side of the web Team Inbox sidebar (pure logic: inbox_sidebar_pure):

    list_select / add_opportunity_filter   list_conversations(opportunity=…)
    conv_fields / fill_opportunity          the four `opportunity_*` ConvRow keys
    opportunity_card                         get_customer_info["opportunity_card"]

The Opportunity columns are read through the list query's LEFT JOIN
(`o`); a single conversation (get_conversation, realtime rows) costs one
`get_value` when it has an Opportunity linked, a page from another query
one batched `get_all`.
"""

import frappe
from frappe import _

from opportunity_management.opportunity_management import inbox_sidebar_pure as P

OPP = "Opportunity"
LIST_JOIN = P.OPPORTUNITY_LIST_JOIN
STAGE_FIELD = "custom_agent_status"
RESPONSIBLE_FIELD = "custom_responsible_party"


def _has_field(fieldname) -> bool:
    try:
        return bool(frappe.get_meta(OPP).has_field(fieldname))
    except Exception:
        return False


def list_select() -> str:
    """The four Opportunity columns for the list query (trailing comma)."""
    return P.opportunity_select(_has_field(STAGE_FIELD), _has_field("expected_closing"))


def add_opportunity_filter(clauses, params, value):
    """Append the `opportunity` filter of list_conversations; frappe.throw
    on an unknown value."""
    try:
        sql, extra = P.opportunity_clause(value)
    except ValueError:
        frappe.throw(_("Unknown opportunity filter {0}").format(value))
    if sql:
        clauses.append(sql)
        params.update(extra)


def _lookup_fields():
    """Opportunity field → ConvRow source key, for the fields this site has."""
    pairs = [("status", "opportunity_status"), ("title", "opportunity_title")]
    if _has_field(STAGE_FIELD):
        pairs.append((STAGE_FIELD, "opportunity_stage"))
    if _has_field("expected_closing"):
        pairs.append(("expected_closing", "opportunity_closing"))
    return pairs


def _lookup(names):
    """{opportunity: {opportunity_status, …}} for existing Opportunities."""
    wanted = sorted({n for n in names if n})
    if not wanted:
        return {}
    pairs = _lookup_fields()
    try:
        rows = frappe.get_all(
            OPP, filters={"name": ["in", wanted]},
            fields=["name"] + [f for f, _key in pairs], limit_page_length=0,
        )
    except Exception:
        return {}
    return {r["name"]: {key: r.get(f) for f, key in pairs} for r in rows}


def conv_fields(conv, g):
    """The four ConvRow keys. The list query (or `fill_opportunity`) has
    put the columns on dict rows; a Document is looked up."""
    if isinstance(conv, dict) and "opportunity_status" in conv:
        return P.opportunity_fields(conv)
    name = g(conv, "opportunity")
    if not name:
        return P.opportunity_fields(None)
    return P.opportunity_fields(_lookup([name]).get(name))


def fill_opportunity(rows, g):
    """Batch the Opportunity columns onto dict rows that lack them."""
    todo = [r for r in rows if isinstance(r, dict) and "opportunity_status" not in r]
    if not todo:
        return
    found = _lookup([g(r, "opportunity") for r in todo])
    for row in todo:
        src = found.get(g(row, "opportunity")) or {}
        for key in P.OPPORTUNITY_KEYS:
            row[key] = src.get(key)


# ── customer drawer card ─────────────────────────────────────────────────────

def card_fields():
    """Extra Opportunity fields the card needs on top of the customer info
    list (whatsapp_api_customer._opportunities)."""
    return [STAGE_FIELD] if _has_field(STAGE_FIELD) else []


def _stages():
    df = frappe.get_meta(OPP).get_field(STAGE_FIELD)
    if not df or df.fieldtype != "Select":
        return []
    return P.stages_from_options(df.options)


def _responsible(name):
    """Display names of the Opportunity's Responsible Party rows, in order."""
    df = frappe.get_meta(OPP).get_field(RESPONSIBLE_FIELD)
    if not df or not df.options:
        return []
    rows = frappe.get_all(
        df.options,
        filters={"parent": name, "parenttype": OPP, "parentfield": RESPONSIBLE_FIELD},
        fields=["responsible_party"], order_by="idx asc", limit_page_length=0,
    )
    parties = [r.get("responsible_party") for r in rows if r.get("responsible_party")]
    if not parties:
        return []
    labels = {}
    try:
        labels = {
            r["name"]: r.get("display_name")
            for r in frappe.get_all("Responsible Party", filters={"name": ["in", parties]},
                                    fields=["name", "display_name"], limit_page_length=0)
        }
    except Exception:
        labels = {}
    out = []
    for party in parties:
        label = labels.get(party) or party
        if label not in out:
            out.append(label)
    return out


def opportunity_card(conv, linked_row, fields, iso):
    """The card of the conversation's linked Opportunity, or None (nothing
    linked, deleted, or not readable by the caller). `linked_row` is the
    row the customer info list already read; only when the list did not
    reach it is the Opportunity read again (permission-aware)."""
    name = conv.get("opportunity")
    if not name:
        return None
    row = linked_row
    if not row:
        try:
            found = frappe.get_list(OPP, filters={"name": name}, fields=fields, limit_page_length=1)
        except Exception:
            found = []
        row = found[0] if found else None
    if not row:
        return None
    try:
        stages = _stages()
        responsible = _responsible(name)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Inbox customer info: opportunity card failed")
        stages, responsible = [], []
    return P.opportunity_card(row, stages, responsible, iso)
