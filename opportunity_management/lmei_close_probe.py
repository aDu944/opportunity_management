import frappe


TO_CLOSE = [
    "INQ-259-LMEI-1389-25",
    "INQ-262-LMEI-1389-25", "INQ-263-LMEI-1389-25", "INQ-264-LMEI-1389-25",
    "INQ-265-LMEI-1389-25", "INQ-266-LMEI-1389-25", "INQ-267-LMEI-1389-25",
    "INQ-268-LMEI-1389-25", "INQ-269-LMEI-1389-25", "INQ-270-LMEI-1389-25",
    "INQ-271-LMEI-1389-25", "INQ-272-LMEI-1389-25", "INQ-273-LMEI-1389-25",
    "INQ-274-LMEI-1389-25", "INQ-275-LMEI-1389-25", "INQ-276-LMEI-1389-25",
    "INQ-277-LMEI-1389-25", "INQ-278-LMEI-1389-25", "INQ-279-LMEI-1389-25",
    "INQ-280-LMEI-1389-25", "INQ-281-LMEI-1389-25", "INQ-282-LMEI-1389-25",
    "INQ-283-LMEI-1389-25",
]


def run():
    closed, skipped, errors = [], [], []
    for name in TO_CLOSE:
        try:
            current_status = frappe.db.get_value("Opportunity", name, "status")
            if current_status == "Closed":
                skipped.append(f"{name} (already Closed)")
                continue
            # Bypasses doc_events → no notification storm to responsible parties.
            frappe.db.set_value("Opportunity", name, "status", "Closed")
            # Audit trail — leave a comment naming the bulk-close action.
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Opportunity",
                "reference_name": name,
                "content": "Bulk-closed via LMEI-1389-25 cleanup — no Quotation raised.",
            }).insert(ignore_permissions=True)
            closed.append(name)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    frappe.db.commit()

    print(f"CLOSED ({len(closed)}):")
    for n in closed:
        print(f"  {n}")
    if skipped:
        print(f"\nSKIPPED ({len(skipped)}):")
        for s in skipped:
            print(f"  {s}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    return {"closed": len(closed), "skipped": len(skipped), "errors": len(errors)}
