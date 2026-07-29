import frappe


NAMES = [
    "INQ-241-ANOF-7000210-25",
    "INQ-238-PCIL-31-25-25",
    "INQ-229-ANOF-0-25",
    "INQ-105-G-0-25",
    "INQ-098-IGS-0-25",
    "INQ-219-IGS-0-25",
    "INQ-057-G-0-25",
    "INQ-232-BGCI-3211-24",
]


def run():
    closed, missing, already, has_q = [], [], [], []
    for name in NAMES:
        if not frappe.db.exists("Opportunity", name):
            missing.append(name)
            continue
        current = frappe.db.get_value("Opportunity", name, "status")
        if current == "Closed":
            already.append(name)
            continue
        # Note if a Quotation exists — proceed but flag it in the audit line.
        q_count = frappe.db.count("Quotation", {
            "opportunity": name, "docstatus": ["!=", 2],
        })
        note_q = " (had quotation — closed anyway per user request)" if q_count else ""
        if q_count:
            has_q.append(name)
        frappe.db.set_value("Opportunity", name, "status", "Closed")
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Opportunity",
            "reference_name": name,
            "content": f"Manually closed by explicit user request{note_q}.",
        }).insert(ignore_permissions=True)
        closed.append(name)
    frappe.db.commit()

    print(f"CLOSED ({len(closed)}):")
    for n in closed: print(f"  {n}")
    if missing:
        print(f"\nMISSING ({len(missing)}):")
        for n in missing: print(f"  {n}")
    if already:
        print(f"\nALREADY CLOSED ({len(already)}):")
        for n in already: print(f"  {n}")
    if has_q:
        print(f"\nCLOSED but had a linked Quotation ({len(has_q)}):")
        for n in has_q: print(f"  {n}")
    return {"closed": len(closed), "missing": len(missing), "already": len(already), "with_quotation": len(has_q)}
