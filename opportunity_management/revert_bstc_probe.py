import frappe


def run():
    name = "INQ-048-BsTC-0-25"
    before = frappe.db.get_value("Opportunity", name, "status")
    frappe.db.set_value("Opportunity", name, "status", "Converted")
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Info",
        "reference_doctype": "Opportunity",
        "reference_name": name,
        "content": "Reverted bulk-close: has linked Quotation + Sales Order — restored to Converted per user.",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    after = frappe.db.get_value("Opportunity", name, "status")
    print(f"Before: {before}  After: {after}")
    return {"before": before, "after": after}
