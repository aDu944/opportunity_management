"""
Check-in exemption:

* `custom_checkin_exempt` (Check) on `Employee` — created here because
  fixtures sync only after post_model_sync patches;
* set to 1 for the Employees linked to the four System Managers who are not
  required to check in or out (checkin_exempt.SEED_EXEMPT_USERS).

Idempotent: re-running creates nothing twice and only sets the flag where it
is still 0. Users with no Employee record are logged, not fatal.
"""

import frappe

from opportunity_management.opportunity_management.checkin_exempt import (
    FIELDNAME,
    SEED_EXEMPT_USERS,
    split_found,
)

CHECKIN_EXEMPT_CUSTOM_FIELDS = {
    "Employee": [
        {
            "fieldname": FIELDNAME,
            "fieldtype": "Check",
            "label": "Exempt from check-in / check-out",
            "insert_after": "status",
            "default": "0",
            "description": "Not required to check in or out: no reminders, "
                           "no late check-in leave, no auto-checkout",
        },
    ]
}


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(CHECKIN_EXEMPT_CUSTOM_FIELDS, update=True)

    rows = frappe.get_all(
        "Employee",
        filters={"user_id": ["in", list(SEED_EXEMPT_USERS)]},
        fields=["name", "user_id", FIELDNAME],
    )
    found, missing = split_found(SEED_EXEMPT_USERS, [r.user_id for r in rows])

    flagged = 0
    for r in rows:
        if not r.get(FIELDNAME):
            frappe.db.set_value("Employee", r.name, FIELDNAME, 1, update_modified=False)
            flagged += 1

    frappe.db.commit()
    print(
        f"Check-in exemption: field ensured, {flagged} employee(s) newly flagged, "
        f"{len(found)} matched"
        + (f"; no Employee for: {', '.join(missing)}" if missing else "")
    )
