import frappe


def run():
    completed = ("Closed", "Lost", "Converted", "Quotation")
    rows = frappe.db.sql(
        """SELECT o.name, COUNT(q.name) AS q_count
           FROM `tabOpportunity` o
           LEFT JOIN `tabQuotation` q
                  ON q.opportunity = o.name AND q.docstatus != 2
           WHERE (o.expected_closing IS NULL OR o.expected_closing = '')
             AND o.status NOT IN %(completed)s
           GROUP BY o.name
           ORDER BY o.name""",
        {"completed": completed},
        as_dict=True,
    )
    print(f"=== Found {len(rows)} open + undated opportunities ===\n")

    closed, had_quotation, errors = [], [], []
    for r in rows:
        name = r["name"]
        try:
            frappe.db.set_value("Opportunity", name, "status", "Closed")
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Opportunity",
                "reference_name": name,
                "content": "Bulk-closed: open + no expected_closing (staleness sweep).",
            }).insert(ignore_permissions=True)
            closed.append(name)
            if r["q_count"]:
                had_quotation.append(name)
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    frappe.db.commit()

    print(f"CLOSED ({len(closed)})")
    if had_quotation:
        print(f"\nOf those, {len(had_quotation)} had a linked Quotation — review these:")
        for n in had_quotation:
            print(f"  {n}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    return {"closed": len(closed), "with_quotation": len(had_quotation), "errors": len(errors)}
