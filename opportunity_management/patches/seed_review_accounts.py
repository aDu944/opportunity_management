"""
App-store review accounts:

* `custom_review_account` (Check) on `Employee` — created here because
  fixtures sync only after post_model_sync patches;
* set to 1 for the Employees linked to the store reviewer logins
  (checkin_exempt.SEED_REVIEW_USERS).

Flagged employees are left out of team attendance, its stats and the daily
attendance report, but keep the normal check-in card and reminders.

Idempotent: re-running creates nothing twice and only sets the flag where it
is still 0. Users with no Employee record are logged, not fatal.
"""

import frappe

from opportunity_management.opportunity_management.checkin_exempt import (
    REVIEW_FIELDNAME,
    SEED_REVIEW_USERS,
    split_found,
)

REVIEW_ACCOUNT_CUSTOM_FIELDS = {
    "Employee": [
        {
            "fieldname": REVIEW_FIELDNAME,
            "fieldtype": "Check",
            "label": "App review account",
            "insert_after": "custom_checkin_exempt",
            "default": "0",
            "description": "Store reviewer login, not staff: left out of team "
                           "attendance and stats. Still gets the check-in card "
                           "so reviewers can test it.",
        },
    ]
}


def execute():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(REVIEW_ACCOUNT_CUSTOM_FIELDS, update=True)

    rows = frappe.get_all(
        "Employee",
        filters={"user_id": ["in", list(SEED_REVIEW_USERS)]},
        fields=["name", "user_id", REVIEW_FIELDNAME],
    )
    found, missing = split_found(SEED_REVIEW_USERS, [r.user_id for r in rows])

    flagged = 0
    for r in rows:
        if not r.get(REVIEW_FIELDNAME):
            frappe.db.set_value("Employee", r.name, REVIEW_FIELDNAME, 1,
                                update_modified=False)
            flagged += 1

    frappe.db.commit()
    print(
        f"Review accounts: field ensured, {flagged} employee(s) newly flagged, "
        f"{len(found)} matched"
        + (f"; no Employee for: {', '.join(missing)}" if missing else "")
    )
