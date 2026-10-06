"""
Shareholder app (shareholder_contract.md):

* `custom_share_pct` (Percent) and `custom_user` (Link User) on ERPNext's
  `Shareholder` — created here because fixtures sync only after
  post_model_sync patches and the distributions endpoint reads them;
* ESS Mobile Settings `shareholder_company` = "AL KHORA" when empty;
* when exactly two `Shareholder` rows exist and none has a share yet, 50 % each
  (the agreed ownership).

Idempotent: re-running creates nothing twice and only fills empty values.
"""

import frappe

SHAREHOLDER_CUSTOM_FIELDS = {
    "Shareholder": [
        {
            "fieldname": "custom_share_pct",
            "fieldtype": "Percent",
            "label": "Share %",
            "insert_after": "title",
            "description": "Ownership share used by the shareholder app (indicative entitlement).",
        },
        {
            "fieldname": "custom_user",
            "fieldtype": "Link",
            "label": "User",
            "options": "User",
            "insert_after": "custom_share_pct",
            "description": "The ERPNext user of this shareholder in the mobile app.",
        },
    ]
}

COMPANY = "AL KHORA"


def execute():
    if not frappe.db.exists("DocType", "Shareholder"):
        print("Shareholder settings: no Shareholder doctype, skipped")
        return
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    create_custom_fields(SHAREHOLDER_CUSTOM_FIELDS, update=True)

    company_set = False
    current = frappe.db.get_single_value("ESS Mobile Settings", "shareholder_company")
    if not current and frappe.db.exists("Company", COMPANY):
        frappe.db.set_single_value("ESS Mobile Settings", "shareholder_company", COMPANY)
        company_set = True

    split = False
    rows = frappe.get_all("Shareholder", fields=["name", "custom_share_pct"])
    if len(rows) == 2 and all(not r.custom_share_pct for r in rows):
        for r in rows:
            frappe.db.set_value("Shareholder", r.name, "custom_share_pct", 50,
                                update_modified=False)
        split = True

    frappe.db.commit()
    print(
        "Shareholder settings: fields ensured"
        + (", company set to " + COMPANY if company_set else "")
        + (", 50/50 split seeded" if split else "")
    )
