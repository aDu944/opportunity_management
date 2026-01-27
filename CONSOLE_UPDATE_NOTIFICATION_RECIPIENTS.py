# ERPNext Console Script: Backfill Opportunity notification recipients
# Paste this into System Console to update custom_notification_recipients

import frappe


def update_opportunity_notification_recipients(
    fieldname="custom_notification_recipients",
    batch_size=200,
    update_modified=False
):
    print("=" * 70)
    print("UPDATE OPPORTUNITY NOTIFICATION RECIPIENTS")
    print("=" * 70)

    meta = frappe.get_meta("Opportunity")
    if not meta.has_field(fieldname):
        print(f"✗ ERROR: Field '{fieldname}' not found on Opportunity.")
        print("Create the custom field first, then rerun this script.")
        return

    total = frappe.db.count("Opportunity")
    print(f"Total Opportunities: {total}")
    print(f"Batch size: {batch_size}")
    print(f"Update modified: {update_modified}")

    from opportunity_management.opportunity_management import notification_utils

    updated = 0
    failed = 0
    start = 0

    while True:
        names = frappe.get_all(
            "Opportunity",
            fields=["name"],
            start=start,
            page_length=batch_size
        )

        if not names:
            break

        for row in names:
            try:
                doc = frappe.get_doc("Opportunity", row.name)
                recipients = notification_utils.get_opportunity_assignee_recipients_for_notification(doc)
                recipients_value = ", ".join(recipients)

                frappe.db.set_value(
                    "Opportunity",
                    row.name,
                    fieldname,
                    recipients_value,
                    update_modified=update_modified
                )
                updated += 1
            except Exception as e:
                failed += 1
                frappe.log_error(
                    f"Failed updating {row.name}: {str(e)}",
                    "Update Opportunity Notification Recipients"
                )

        frappe.db.commit()
        start += batch_size
        print(f"Processed {min(start, total)}/{total}...")

    print("\n" + "=" * 70)
    print("DONE")
    print(f"Updated: {updated}")
    print(f"Failed: {failed}")
    print("=" * 70)


# Run the update
update_opportunity_notification_recipients()
