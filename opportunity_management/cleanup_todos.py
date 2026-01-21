"""
Cleanup script to close ToDos for opportunities that already have submitted quotations.

Run this script once to clean up existing data:
    bench --site [your-site] console
    >>> from opportunity_management.cleanup_todos import cleanup_todos
    >>> cleanup_todos()
"""

import frappe
from frappe import _


def cleanup_todos(dry_run=False):
    """
    Find and close all ToDos for opportunities that have submitted quotations.

    Args:
        dry_run: If True, only show what would be closed without actually closing
    """
    print("\n" + "="*70)
    print("CLEANING UP TODOS FOR OPPORTUNITIES WITH SUBMITTED QUOTATIONS")
    print("="*70 + "\n")

    # Find all opportunities with submitted quotations
    quotations = frappe.db.sql("""
        SELECT
            q.name as quotation_name,
            q.opportunity,
            q.docstatus,
            q.transaction_date
        FROM
            `tabQuotation` q
        WHERE
            q.opportunity IS NOT NULL
            AND q.docstatus = 1
        ORDER BY
            q.transaction_date DESC
    """, as_dict=True)

    print(f"Found {len(quotations)} submitted quotations with linked opportunities\n")

    total_opportunities = 0
    total_todos_closed = 0
    total_opps_closed = 0

    for quot in quotations:
        opp_name = quot.opportunity

        # Get opportunity
        try:
            opp = frappe.get_doc("Opportunity", opp_name)
        except frappe.DoesNotExistError:
            print(f"⚠️  Opportunity {opp_name} not found (Quotation: {quot.quotation_name})")
            continue

        total_opportunities += 1

        # Find open ToDos for this opportunity
        todos = frappe.get_all("ToDo",
            filters={
                "reference_type": "Opportunity",
                "reference_name": opp_name,
                "status": "Open"
            },
            fields=["name", "allocated_to", "creation"]
        )

        if not todos:
            continue

        print(f"\n📋 Opportunity: {opp_name}")
        print(f"   Quotation: {quot.quotation_name} (submitted)")
        print(f"   Status: {opp.status}")
        print(f"   Open ToDos: {len(todos)}")

        if dry_run:
            print(f"   [DRY RUN] Would close {len(todos)} ToDo(s)")
            for todo in todos:
                print(f"      - {todo.name} (assigned to: {todo.allocated_to})")
        else:
            # Close the ToDos
            for todo in todos:
                frappe.db.set_value("ToDo", todo.name, "status", "Closed")
                print(f"   ✓ Closed ToDo: {todo.name} (assigned to: {todo.allocated_to})")

            total_todos_closed += len(todos)

            # Close the opportunity if it's not already closed
            if opp.status not in ["Converted", "Closed", "Lost"]:
                opp.status = "Converted"
                opp.add_comment("Comment", f"Auto-closed by cleanup script - Quotation {quot.quotation_name} was already submitted")
                opp.save(ignore_permissions=True)
                total_opps_closed += 1
                print(f"   ✓ Closed Opportunity: {opp_name}")

    if not dry_run:
        frappe.db.commit()

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"Opportunities with submitted quotations: {len(quotations)}")
    print(f"Opportunities processed: {total_opportunities}")

    if dry_run:
        print(f"\n[DRY RUN MODE] - No changes were made")
        print(f"Run with dry_run=False to actually close the ToDos")
    else:
        print(f"\nToDos closed: {total_todos_closed}")
        print(f"Opportunities closed: {total_opps_closed}")
        print(f"\n✅ Cleanup complete!")

    print("="*70 + "\n")

    return {
        "total_quotations": len(quotations),
        "opportunities_processed": total_opportunities,
        "todos_closed": total_todos_closed if not dry_run else 0,
        "opportunities_closed": total_opps_closed if not dry_run else 0
    }


def cleanup_draft_quotations():
    """
    Find opportunities with draft quotations and optionally close their todos.
    This is more cautious - only for review.
    """
    print("\n" + "="*70)
    print("OPPORTUNITIES WITH DRAFT QUOTATIONS")
    print("="*70 + "\n")

    # Find opportunities with draft quotations
    quotations = frappe.db.sql("""
        SELECT
            q.name as quotation_name,
            q.opportunity,
            q.docstatus,
            q.transaction_date,
            q.status
        FROM
            `tabQuotation` q
        WHERE
            q.opportunity IS NOT NULL
            AND q.docstatus = 0
        ORDER BY
            q.transaction_date DESC
    """, as_dict=True)

    print(f"Found {len(quotations)} draft quotations with linked opportunities\n")

    for quot in quotations:
        opp_name = quot.opportunity

        # Find open ToDos for this opportunity
        todos = frappe.get_all("ToDo",
            filters={
                "reference_type": "Opportunity",
                "reference_name": opp_name,
                "status": "Open"
            },
            fields=["name", "allocated_to"]
        )

        if todos:
            print(f"📋 Opportunity: {opp_name}")
            print(f"   Draft Quotation: {quot.quotation_name}")
            print(f"   Open ToDos: {len(todos)}")
            for todo in todos:
                print(f"      - {todo.name} (assigned to: {todo.allocated_to})")
            print()

    print("="*70)
    print("NOTE: Draft quotations are not auto-closed.")
    print("Submit the quotations to trigger auto-close functionality.")
    print("="*70 + "\n")


if __name__ == "__main__":
    # For testing
    cleanup_todos(dry_run=True)
