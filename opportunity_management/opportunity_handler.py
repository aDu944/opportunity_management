import frappe
from frappe import _
from frappe.utils import nowdate, getdate, add_days
from datetime import date


def on_opportunity_insert(doc, method):
    """Handle new opportunity creation"""
    create_assignments_and_notify(doc, is_new=True)


def on_opportunity_update(doc, method):
    """Handle opportunity updates - check if assignees changed"""
    if doc.has_value_changed("custom_resp_eng"):
        # Remove old todos and create new ones
        handle_assignee_changes(doc)


def create_assignments_and_notify(doc, is_new=False):
    """
    Create ToDos for each responsible engineer and the assigner.
    Send initial assignment email with items to quote.
    """
    if not doc.custom_resp_eng:
        return
    
    assigner = frappe.session.user
    items_html = get_items_html(doc)
    
    # Track created todos to avoid duplicates
    created_for = []
    
    # Create ToDo for each responsible engineer
    for row in doc.custom_resp_eng:
        engineer_user = get_user_from_engineer(row)
        
        if engineer_user and engineer_user not in created_for:
            # Create ToDo
            create_todo_for_user(doc, engineer_user, is_assigner=False)
            created_for.append(engineer_user)
            
            # Send assignment email
            if is_new:
                send_assignment_email(doc, engineer_user, items_html)
    
    # Create ToDo for assigner (current user) if not already in list
    if assigner not in created_for:
        create_todo_for_user(doc, assigner, is_assigner=True)
    
    # Log the assignment
    log_assignment(doc, created_for, assigner)


def get_user_from_engineer(engineer_row):
    """
    Get the user email from the Responsible Engineer doctype.
    The engineer_row links to Employee or Shareholder.
    """
    user = None
    
    # Try to get user from Employee link
    if engineer_row.get("responsible_engineer"):
        resp_eng_doc = frappe.get_doc("Responsible Engineer", engineer_row.responsible_engineer)
        
        if resp_eng_doc.get("employee"):
            employee = frappe.get_doc("Employee", resp_eng_doc.employee)
            user = employee.get("user_id")
        
        # If no employee, try shareholder
        elif resp_eng_doc.get("shareholder"):
            shareholder = frappe.get_doc("Shareholder", resp_eng_doc.shareholder)
            # Shareholders might have a linked contact or user
            if shareholder.get("user"):
                user = shareholder.user
            elif shareholder.get("email"):
                user = shareholder.email
    
    return user


def create_todo_for_user(doc, user, is_assigner=False):
    """Create a ToDo linked to the Opportunity"""
    
    # Check if ToDo already exists
    existing = frappe.db.exists("ToDo", {
        "reference_type": "Opportunity",
        "reference_name": doc.name,
        "allocated_to": user,
        "status": "Open"
    })
    
    if existing:
        return existing
    
    description = f"""
    <b>Opportunity:</b> {doc.name}<br>
    <b>Customer:</b> {doc.party_name or 'N/A'}<br>
    <b>Closing Date:</b> {doc.expected_closing or 'Not set'}<br>
    <b>Role:</b> {'Assigner' if is_assigner else 'Responsible Engineer'}
    """
    
    todo = frappe.get_doc({
        "doctype": "ToDo",
        "status": "Open",
        "priority": "Medium",
        "allocated_to": user,
        "assigned_by": frappe.session.user,
        "reference_type": "Opportunity",
        "reference_name": doc.name,
        "description": description,
        "date": doc.expected_closing or nowdate(),
        # Custom fields for tracking (you'll need to add these to ToDo doctype)
        # "custom_is_assigner": is_assigner,
        # "custom_closing_date": doc.expected_closing,
    })
    todo.insert(ignore_permissions=True)
    
    return todo.name


def get_items_html(doc):
    """Generate HTML table of items from Opportunity"""
    if not doc.items:
        return "<p>No items specified</p>"
    
    html = """
    <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <thead>
            <tr style="background-color: #f5f5f5;">
                <th>Item Code</th>
                <th>Item Name</th>
                <th>Qty</th>
                <th>UOM</th>
                <th>Description</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for item in doc.items:
        html += f"""
            <tr>
                <td>{item.item_code or ''}</td>
                <td>{item.item_name or ''}</td>
                <td>{item.qty or 0}</td>
                <td>{item.uom or ''}</td>
                <td>{item.description or ''}</td>
            </tr>
        """
    
    html += "</tbody></table>"
    return html


def send_assignment_email(doc, user, items_html):
    """Send assignment notification email"""
    
    subject = f"New Opportunity Assignment: {doc.name}"
    
    message = f"""
    <h3>You have been assigned to a new Opportunity</h3>
    
    <p><b>Opportunity:</b> {doc.name}</p>
    <p><b>Customer:</b> {doc.party_name or 'N/A'}</p>
    <p><b>Closing Date:</b> {doc.expected_closing or 'Not set'}</p>
    <p><b>Assigned By:</b> {frappe.session.user}</p>
    
    <h4>Items to Quote:</h4>
    {items_html}
    
    <p>
        <a href="{frappe.utils.get_url()}/app/opportunity/{doc.name}" 
           style="background-color: #5e64ff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
            View Opportunity
        </a>
    </p>
    """
    
    try:
        frappe.sendmail(
            recipients=[user],
            subject=subject,
            message=message,
            now=True
        )
    except Exception as e:
        frappe.log_error(f"Failed to send assignment email to {user}: {str(e)}")


def handle_assignee_changes(doc):
    """Handle when assignees are changed on an existing opportunity"""
    
    # Get current assignees from the child table
    current_assignees = set()
    for row in doc.custom_resp_eng:
        user = get_user_from_engineer(row)
        if user:
            current_assignees.add(user)
    
    # Get existing open todos for this opportunity
    existing_todos = frappe.get_all("ToDo", 
        filters={
            "reference_type": "Opportunity",
            "reference_name": doc.name,
            "status": "Open"
        },
        fields=["name", "allocated_to"]
    )
    
    existing_users = {t.allocated_to for t in existing_todos}
    
    # Close todos for removed assignees (except assigner)
    assigner = frappe.session.user
    for todo in existing_todos:
        if todo.allocated_to not in current_assignees and todo.allocated_to != assigner:
            frappe.db.set_value("ToDo", todo.name, "status", "Cancelled")
    
    # Create todos for new assignees
    items_html = get_items_html(doc)
    for user in current_assignees:
        if user not in existing_users:
            create_todo_for_user(doc, user, is_assigner=False)
            send_assignment_email(doc, user, items_html)


def log_assignment(doc, assignees, assigner):
    """Log the assignment for tracking purposes"""
    
    # Check if Opportunity Assignment Log doctype exists
    if frappe.db.exists("DocType", "Opportunity Assignment Log"):
        log = frappe.get_doc({
            "doctype": "Opportunity Assignment Log",
            "opportunity": doc.name,
            "assigned_by": assigner,
            "assigned_to": ", ".join(assignees),
            "assignment_date": nowdate(),
            "closing_date": doc.expected_closing
        })
        log.insert(ignore_permissions=True)
