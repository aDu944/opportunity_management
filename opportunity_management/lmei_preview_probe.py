import frappe


def preview():
    # Match anything whose name contains LMEI-1389-25 (that's the tender key).
    rows = frappe.db.sql(
        """SELECT o.name, o.status, o.party_name, o.expected_closing,
                  COUNT(q.name) AS q_count
           FROM `tabOpportunity` o
           LEFT JOIN `tabQuotation` q
                  ON q.opportunity = o.name AND q.docstatus != 2
           WHERE o.name LIKE '%LMEI-1389-25%'
           GROUP BY o.name
           ORDER BY o.name""",
        as_dict=True,
    )
    print(f"=== {len(rows)} opportunities matching LMEI-1389-25 ===\n")
    to_close, keep = [], []
    for r in rows:
        marker = "KEEP (has quotation)" if r["q_count"] > 0 else "→ close"
        print(f"  {r['name']:32s}  {r['status']:12s}  quotations={r['q_count']}   {marker}")
        (keep if r["q_count"] > 0 else to_close).append(r["name"])

    print(f"\n=== Summary ===")
    print(f"  {len(to_close)} to close: {', '.join(to_close)}")
    if keep:
        print(f"  {len(keep)} to keep : {', '.join(keep)}")
    return {"to_close": to_close, "keep": keep}
