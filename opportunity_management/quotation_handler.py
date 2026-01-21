import frappe
from frappe import _
from frappe.utils import nowdate, getdate


def on_quotation_submit(doc, method):
    """
    When a Quotation is submitted, close all related ToDos
    for the linked Opportunity.
    """
    opportunity_name = doc.get("opportunity")
    
    if not opportunity_name:
        # Try to find opportunity from items or other links
        opportunity_name = find_linked_opportunity(doc)
    
    if opportunity_name:
        close_opportunity_todos(opportunity_name, doc.name)
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


def close_opportunity_todos(opportunity_name, quotation_name):
    """Close all open ToDos linked to the opportunity"""
    
    todos = frappe.get_all("ToDo",
        filters={
            "reference_type": "Opportunity",
            "reference_name": opportunity_name,
            "status": "Open"
        },
        fields=["name", "allocated_to"]
    )
    
    closing_date = getdate(nowdate())
    
    for todo in todos:
        frappe.db.set_value("ToDo", todo.name, {
            "status": "Closed",
            # If you add custom fields:
            # "custom_closed_date": closing_date,
            # "custom_quotation": quotation_name,
        })
        
        # Send completion notification
        send_todo_closed_notification(todo, opportunity_name, quotation_name)
    
    frappe.db.commit()
    
    frappe.msgprint(
        _(f"Closed {len(todos)} ToDo(s) for Opportunity {opportunity_name}"),
        alert=True
    )


def send_todo_closed_notification(todo, opportunity_name, quotation_name):
    """Notify the assignee that their todo was closed"""
    
    subject = f"Task Completed: Opportunity {opportunity_name}"
    
    message = f"""
    <h3>Your task has been completed</h3>
    
    <p>The Opportunity <b>{opportunity_name}</b> has been converted to a Quotation.</p>
    
    <p><b>Quotation:</b> {quotation_name}</p>
    
    <p>
        <a href="{frappe.utils.get_url()}/app/quotation/{quotation_name}" 
           style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
            View Quotation
        </a>
    </p>
    """
    
    try:
        frappe.sendmail(
            recipients=[todo.allocated_to],
            subject=subject,
            message=message,
            now=True
        )
    except Exception as e:
        frappe.log_error(f"Failed to send completion email to {todo.allocated_to}: {str(e)}")


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
    """
    Scheduled task to check for opportunities that have been 
    converted to quotations and close their todos.
    This catches any that might have been missed.
    """
    
    # Find opportunities with status "Quotation" that still have open todos
    opportunities_with_open_todos = frappe.db.sql("""
        SELECT DISTINCT t.reference_name
        FROM `tabToDo` t
        JOIN `tabOpportunity` o ON t.reference_name = o.name
        WHERE t.reference_type = 'Opportunity'
        AND t.status = 'Open'
        AND o.status = 'Quotation'
    """, as_dict=True)
    
    for opp in opportunities_with_open_todos:
        # Find the quotation
        quotation = frappe.db.get_value("Quotation", 
            {"opportunity": opp.reference_name, "docstatus": 1},
            "name"
        )
        
        if quotation:
            close_opportunity_todos(opp.reference_name, quotation)
