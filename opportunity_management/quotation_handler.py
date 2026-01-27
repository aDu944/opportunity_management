import frappe
from frappe import _
from frappe.utils import nowdate, getdate


def on_quotation_submit(doc, method):
    """
    When a Quotation is submitted, close the Opportunity and notify assignees.
    """
    opportunity_name = doc.get("opportunity")

    if not opportunity_name:
        # Try to find opportunity from items or other links
        opportunity_name = find_linked_opportunity(doc)

    if opportunity_name:
        close_opportunity(opportunity_name, doc.name)
        notify_opportunity_assignees(opportunity_name, doc.name)
        update_assignment_log(opportunity_name, doc.name)


def find_linked_opportunity(doc):
    """Try to find linked opportunity from various sources"""

    # Check quotation items for opportunity reference
    for item in doc.items:
        if item.get("prevdoc_docname") and item.get("prevdoc_doctype") == "Opportunity":
            return item.prevdoc_docname

    # Check if there's a direct opportunity field
    if doc.get("opportunity"):
        return doc.opportunity

    return None


def close_opportunity(opportunity_name, quotation_name):
    """Close the Opportunity by updating its status"""

    try:
        opportunity = frappe.get_doc("Opportunity", opportunity_name)

        # Update status to Closed or Converted based on your workflow
        # Check if 'Converted' status exists, otherwise use 'Closed'
        if "Converted" in [d.get("option") for d in frappe.get_meta("Opportunity").get_field("status").options.split("\n") if d]:
            opportunity.status = "Converted"
        else:
            opportunity.status = "Closed"

        # Add reference to the quotation
        opportunity.add_comment("Comment", f"Converted to Quotation {quotation_name}")

        # Save the opportunity
        opportunity.save(ignore_permissions=True)

        frappe.msgprint(
            _(f"Opportunity {opportunity_name} has been closed."),
            alert=True
        )

    except Exception as e:
        frappe.log_error(f"Failed to close Opportunity {opportunity_name}: {str(e)}")
        frappe.msgprint(
            _(f"Warning: Could not close Opportunity {opportunity_name}. Please check manually."),
            alert=True,
            indicator="orange"
        )


def notify_opportunity_assignees(opportunity_name, quotation_name):
    """Notify assignees that their opportunity was converted to a quotation."""
    try:
        from opportunity_management.opportunity_management.notification_utils import (
            get_opportunity_assignee_recipients_for_notification
        )

        opp = frappe.get_doc("Opportunity", opportunity_name)
        recipients = get_opportunity_assignee_recipients_for_notification(opp) or []

        if not recipients:
            return

        subject = f"Opportunity Converted: {opportunity_name}"
        message = f"""
        <h3>Opportunity converted to Quotation</h3>

        <p>The Opportunity <b>{opportunity_name}</b> has been converted to a Quotation.</p>

        <p><b>Quotation:</b> {quotation_name}</p>

        <p>
            <a href=\"{frappe.utils.get_url()}/app/quotation/{quotation_name}\"
               style=\"background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;\">
                View Quotation
            </a>
        </p>
        """

        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            now=True
        )
    except Exception as e:
        frappe.log_error(f"Failed to send conversion email for {opportunity_name}: {str(e)}")


def update_assignment_log(opportunity_name, quotation_name):
    """Update the assignment log with completion details"""
    
    if not frappe.db.exists("DocType", "Opportunity Assignment Log"):
        return
    
    logs = frappe.get_all("Opportunity Assignment Log",
        filters={"opportunity": opportunity_name},
        fields=["name"]
    )
    
    closing_date = getdate(nowdate())
    
    for log in logs:
        log_doc = frappe.get_doc("Opportunity Assignment Log", log.name)
        
        # Calculate if completed on time
        on_time = True
        if log_doc.closing_date:
            on_time = closing_date <= getdate(log_doc.closing_date)
        
        log_doc.db_set({
            "status": "Completed",
            "completed_date": closing_date,
            "quotation": quotation_name,
            "completed_on_time": on_time
        })


def check_and_close_todos():
    """Deprecated: ToDo-based cleanup is no longer used."""
    return
