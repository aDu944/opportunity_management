"""Fold legacy top-level ESS Expense Category rows into the ESS Mobile Settings
single as child rows.

The DocType flipped from top-level (autoname=field:category_name) to
istable=1 in commit 395ed45. Frappe's schema updater does NOT add the child
columns (`parent`, `parenttype`, `parentfield`) when a DocType later becomes
a child, so existing rows remain reachable but orphaned. This patch fixes
both: adds the columns if missing, then re-parents legacy rows to
ESS Mobile Settings under the `expense_categories` field.
"""

import frappe


def execute():
    if not frappe.db.table_exists("ESS Expense Category"):
        return

    cols = {c["Field"] for c in frappe.db.sql(
        "SHOW COLUMNS FROM `tabESS Expense Category`", as_dict=True
    )}
    to_add = []
    if "parent" not in cols:
        to_add.append("ADD COLUMN `parent` VARCHAR(140)")
    if "parenttype" not in cols:
        to_add.append("ADD COLUMN `parenttype` VARCHAR(140)")
    if "parentfield" not in cols:
        to_add.append("ADD COLUMN `parentfield` VARCHAR(140)")
    if to_add:
        frappe.db.sql(
            "ALTER TABLE `tabESS Expense Category` " + ", ".join(to_add)
        )
        try:
            frappe.db.sql(
                "CREATE INDEX `parent_parenttype_idx` "
                "ON `tabESS Expense Category`(`parent`, `parenttype`)"
            )
        except Exception:
            pass  # index may already exist

    frappe.db.sql(
        """
        UPDATE `tabESS Expense Category`
           SET parent = 'ESS Mobile Settings',
               parenttype = 'ESS Mobile Settings',
               parentfield = 'expense_categories'
         WHERE (parent IS NULL OR parent = '')
        """
    )

    rows = frappe.db.sql(
        "SELECT name FROM `tabESS Expense Category` "
        "WHERE parent='ESS Mobile Settings' ORDER BY category_name",
        as_dict=True,
    )
    for i, r in enumerate(rows, start=1):
        frappe.db.sql(
            "UPDATE `tabESS Expense Category` SET idx=%s WHERE name=%s",
            (i, r["name"]),
        )

    frappe.db.commit()
    frappe.clear_cache(doctype="ESS Mobile Settings")
