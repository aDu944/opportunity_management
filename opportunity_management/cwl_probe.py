import frappe


def cancel():
    name = "HR-LAP-2026-00056"
    doc = frappe.get_doc("Leave Application", name)
    print(f"Before: docstatus={doc.docstatus} status={doc.status}")
    if doc.docstatus == 1:
        doc.cancel()
    else:
        # Draft — delete outright since it should never have been created
        frappe.delete_doc("Leave Application", name, force=True)
    frappe.db.commit()
    print("Removed.")
    return {"ok": True}
