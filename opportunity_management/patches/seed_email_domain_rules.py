"""
Seed Email Domain Rules (Outlook add-in): emails from these domains always
suggest this customer. Ahmed, 2026-11-10: "always suggest IC LLC Badra
Petroleum for @badraproject.com emails".

Finds the Customer by ID, then by exact customer_name, then by a unique
partial match; skips (and says so) rather than guessing between several.
Idempotent: an existing rule for the domain is left as it is.
"""

import frappe

SEEDS = [
    ("badraproject.com", "Customer", "IC LLC Badra Petroleum", "Badra Petroleum"),
]


def _find_customer(exact, partial):
    if frappe.db.exists("Customer", exact):
        return exact
    by_name = frappe.get_all("Customer", filters={"customer_name": exact}, pluck="name")
    if len(by_name) == 1:
        return by_name[0]
    like = f"%{partial}%"
    hits = frappe.get_all("Customer", or_filters=[["name", "like", like], ["customer_name", "like", like]],
                          filters={"disabled": 0}, pluck="name")
    return hits[0] if len(hits) == 1 else None


def execute():
    if not frappe.db.table_exists("Email Domain Rule"):
        frappe.reload_doc("opportunity_management", "doctype", "email_domain_rule")
    for domain, party_type, exact, partial in SEEDS:
        if frappe.db.exists("Email Domain Rule", domain):
            print(f"Email Domain Rule {domain}: already set")
            continue
        party = _find_customer(exact, partial) if party_type == "Customer" else None
        if not party:
            print(f"Email Domain Rule {domain}: no single Customer matches '{exact}', not seeded "
                  "- add it under Email Domain Rule")
            continue
        frappe.get_doc({"doctype": "Email Domain Rule", "domain": domain, "party_type": party_type,
                        "party": party, "is_active": 1,
                        "notes": "Seeded for the Outlook add-in"}).insert(ignore_permissions=True)
        print(f"Email Domain Rule {domain} -> {party_type} {party}")
    frappe.db.commit()
