"""
Outlook add-in: parse an Opportunity's items from the email's attachments,
the same way the desk's "Parse Items from File" button does
(alkhora_erp.opportunity_parse.parse_files → Maya on the agents host).

A parse can run for minutes, longer than Cloudflare lets one request live
(~100 s), so it runs as a background job and the task pane polls:

* `start_parse(opportunity, files)` – `files` are File records already
  attached to the Opportunity (the pane saves the chosen attachments first);
  queues the job and returns a parse id;
* `get_parse(parse_id)`             – queued / running / done (+ result) / failed;
* `add_parsed_items(...)`           – the rows the user ticked in the review list
  are APPENDED to the items (never replacing), the title is set only when
  empty, conditions + notes are appended to the tender notes without
  duplicates — the desk button's rules. Unlike the desk form (left unsaved
  for the user), there is no open form here, so the Opportunity is saved,
  with permissions enforced.

Results live in Redis for a day, readable only by the user who started them.
The agents host caches parses for 30 days, so re-parsing a file is quick.
"""

import base64
import json

import frappe
from frappe import _

from opportunity_management.opportunity_management import opportunity_pure as OP
from opportunity_management.opportunity_management import outlook_email_pure as P
from opportunity_management.opportunity_management.outlook_api import OPP, OutlookError, _get_opp, _json

PARSE_METHOD = "alkhora_erp.opportunity_parse.parse_files"
CACHE_PREFIX = "outlook_parse:"
CACHE_SECONDS = 24 * 3600
JOB_TIMEOUT = 600  # parse_files itself gives the agents host 280 s
NOTES_FIELD = "custom_tender_notes"
MAX_ROWS = 500


def _key(parse_id):
    return CACHE_PREFIX + parse_id


def _store(parse_id, data):
    frappe.cache.set_value(_key(parse_id), json.dumps(data, default=str), expires_in_sec=CACHE_SECONDS)


def _load(parse_id):
    raw = frappe.cache.get_value(_key(parse_id))
    if not raw:
        return None
    return json.loads(raw) if isinstance(raw, (str, bytes)) else raw


def _parser():
    if "alkhora_erp" not in frappe.get_installed_apps():
        frappe.throw(_("Item parsing is not installed on this site"), OutlookError)
    try:
        return frappe.get_attr(PARSE_METHOD)
    except Exception:
        frappe.throw(_("Item parsing is not installed on this site"), OutlookError)


def _require_parse_access(opp):
    # parse_files itself requires Opportunity create; adding rows needs write on this one.
    if not frappe.has_permission(OPP, "create"):
        frappe.throw(_("Parsing items needs permission to create Opportunities"), OutlookError)
    if not frappe.has_permission(OPP, "write", doc=opp):
        frappe.throw(_("You are not permitted to edit Opportunity {0}").format(opp), OutlookError)


@frappe.whitelist(methods=["POST"])
def start_parse(opportunity=None, files=None):
    opp = _get_opp(opportunity)
    _require_parse_access(opp)
    _parser()
    names = list(dict.fromkeys(_json(files, [])))
    if not names:
        frappe.throw(_("Pick at least one PDF, image, Excel or Word attachment to parse"), OutlookError)
    rows = frappe.get_all("File", filters={"name": ["in", names], "attached_to_doctype": OPP,
                                           "attached_to_name": opp},
                          fields=["name", "file_name", "file_size"])
    if len(rows) != len(names):
        frappe.throw(_("Some files are not attached to Opportunity {0}").format(opp), OutlookError)
    unreadable = [r.file_name for r in rows if not P.parse_kind(r.file_name)]
    if unreadable:
        frappe.throw(_("These files can't be parsed (PDF, images, .xlsx and .docx only): {0}")
                     .format(", ".join(unreadable)), OutlookError)
    total = sum(int(r.file_size or 0) for r in rows)
    if total > P.PARSE_MAX_BYTES:
        frappe.throw(_("The files add up to {0} MB; parsing takes at most {1} MB at once")
                     .format(round(total / 1048576, 1), P.PARSE_MAX_BYTES // 1048576), OutlookError)

    parse_id = frappe.generate_hash(length=20)
    _store(parse_id, {"status": "queued", "user": frappe.session.user, "opportunity": opp,
                      "files": [r.file_name for r in rows]})
    frappe.enqueue(
        "opportunity_management.opportunity_management.outlook_parse.run_parse",
        queue="long", timeout=JOB_TIMEOUT, enqueue_after_commit=True,
        parse_id=parse_id, opportunity=opp, files=names,
    )
    return {"parse_id": parse_id}


def run_parse(parse_id, opportunity, files):
    """Background job (runs as the user who started it)."""
    state = _load(parse_id) or {"user": frappe.session.user, "opportunity": opportunity}
    state["status"] = "running"
    _store(parse_id, state)
    try:
        payload = []
        for name in files:
            f = frappe.get_doc("File", name)
            content = f.get_content()
            if isinstance(content, str):
                content = content.encode()
            kind = P.parse_kind(f.file_name)
            payload.append({"filename": f.file_name, "content_type": kind[1] if kind else "",
                            "data_b64": base64.b64encode(content).decode("ascii")})
        result = _parser()(files=json.dumps(payload), target=OPP) or {}
        meta = OP.parse_metadata(result)
        rows = []
        for i, row in enumerate((result.get("items") or [])[:MAX_ROWS]):
            mapped = OP.map_parsed_row(row)
            mapped["_index"] = i
            mapped["_confidence"] = row.get("_confidence")
            rows.append(mapped)
        state.update({"status": "done", "rows": rows, "meta": meta,
                      "conditions": result.get("conditions"), "notes": result.get("notes")})
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Outlook add-in: parse failed")
        message = getattr(e, "message", None) or str(e) or e.__class__.__name__
        state.update({"status": "failed", "error": frappe.utils.strip_html(message)[:500]})
    _store(parse_id, state)


@frappe.whitelist(methods=["GET", "POST"])
def get_parse(parse_id=None):
    state = _load(parse_id or "")
    if not state:
        return {"status": "expired"}
    if state.get("user") != frappe.session.user:
        frappe.throw(_("That parse belongs to someone else"), OutlookError)
    return state


@frappe.whitelist(methods=["POST"])
def add_parsed_items(opportunity=None, rows=None, title=None, conditions=None, notes=None):
    opp_name = _get_opp(opportunity)
    _require_parse_access(opp_name)
    rows = _json(rows, [])
    if not rows:
        frappe.throw(_("Pick at least one line"), OutlookError)
    opp = frappe.get_doc(OPP, opp_name)
    child_meta = frappe.get_meta(frappe.get_meta(OPP).get_field("items").options)
    for row in rows[:MAX_ROWS]:
        opp.append("items", OP.map_parsed_row(row, child_meta.has_field))
    if title and not (opp.get("title") or "").strip() and opp.meta.has_field("title"):
        opp.title = str(title).strip()[:140]
    if opp.meta.has_field(NOTES_FIELD):
        merged = P.merge_notes(opp.get(NOTES_FIELD), conditions, notes)
        if merged != (opp.get(NOTES_FIELD) or "").strip():
            opp.set(NOTES_FIELD, merged)
    opp.save()  # permissions enforced
    return {"rows_added": min(len(rows), MAX_ROWS), "opportunity": opp.name}
