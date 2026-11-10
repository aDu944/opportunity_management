"""
WhatsApp AI Settings: persona and knowledge v2 (no narration to the customer,
nothing after a handoff, which team handles what). Replaces a field ONLY when
it still holds the v1 seed text byte for byte, so anything edited in Desk is
kept.
"""

import hashlib

import frappe

from opportunity_management.opportunity_management import ai_agent_seed as S

V1 = {
    "persona_en": "dfe0df438c362f05d8c772953ebfbaf68e862b10",
    "persona_ar": "184876ce00f6c76bb06d04bba7a544057e909f44",
    "knowledge_en": "3b2b44e62e8afa465bb6886830d807ebfa787b68",
    "knowledge_ar": "7c19a191616d3d0e314f6a56061541d4b70a8122",
}


def execute():
    if not frappe.db.exists("DocType", "WhatsApp AI Settings"):
        return
    doc = frappe.get_single("WhatsApp AI Settings")
    changed = []
    for field, digest in V1.items():
        current = hashlib.sha1(str(doc.get(field) or "").strip().encode()).hexdigest()
        if current == digest or not doc.get(field):
            doc.set(field, S.DEFAULTS[field])
            changed.append(field)
    if changed:
        doc.flags.ignore_permissions = True
        doc.save()
        frappe.db.commit()
    print("WhatsApp AI seed v2 — updated: {0}".format(", ".join(changed) or "nothing (edited in Desk)"))
    _backfill_handoff_drafts()


def _backfill_handoff_drafts():
    """Replay / Shadow turns recorded before v2 show a blank draft when the
    model only called handoff; give them the handoff line graders now see."""
    import json

    from opportunity_management.opportunity_management import ai_agent_pure as P

    rows = frappe.get_all("WhatsApp AI Turn", filters={"source": ["in", ["Replay", "Shadow"]], "draft": ["in", ["", None]]},
                          fields=["name", "tools_json"])
    done = 0
    for row in rows:
        try:
            tools = json.loads(row.tools_json or "[]")
        except ValueError:
            continue
        line = P.handoff_line(tools)
        if line:
            frappe.db.set_value("WhatsApp AI Turn", row.name, "draft", line, update_modified=False)
            done += 1
    frappe.db.commit()
    print("WhatsApp AI Turn — handoff lines backfilled: {0}".format(done))
