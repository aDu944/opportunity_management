"""
Assignment Logic for Opportunity Management

This module handles:
1. Sending initial assignment emails with item lists
2. Avoiding duplicate assignments
"""

import frappe
from frappe import _
from frappe.utils import nowdate, get_datetime, getdate, format_date
from frappe.desk.form.assign_to import add as assign_to


def on_opportunity_insert(doc, method):
    """
    Called after a new Opportunity is inserted.
    Sends assignment emails to all responsible engineers.
    """
    process_assignments(doc, is_new=True)


def on_opportunity_update(doc, method):
    """
    Called when an Opportunity is updated.
    Checks for changes in responsible engineers and sends emails for new assignees.
    """
    # Get previous state of the document
    if doc.get("__islocal"):
        return
    
    # Check if custom_resp_eng has changed
    previous_engineers = get_previous_engineers(doc.name)
    current_engineers = get_current_engineers(doc)
    
    # Find new assignments
    new_engineers = current_engineers - previous_engineers
    removed_engineers = previous_engineers - current_engineers
    
    # Process new assignments
    if new_engineers:
        process_assignments(doc, is_new=False, specific_engineers=new_engineers)
    
    # No cleanup needed for removed engineers


def get_previous_engineers(opportunity_name):
    """Get set of engineer user IDs from before the update."""
    engineers = frappe.get_all(
        "Responsible Engineer",
        filters={"parent": opportunity_name, "parenttype": "Opportunity"},
        fields=["responsible_engineer"],
        ignore_permissions=True
    )
    
    result = set()
    for eng in engineers:
        user_id = get_user_from_engineer(eng.responsible_engineer)
        if user_id:
            result.add(user_id)
    
    return result


def get_current_engineers(doc):
    """Get set of engineer user IDs from the current document state."""
    result = set()
    
    if not doc.get("custom_resp_eng"):
        return result
    
    for row in doc.custom_resp_eng:
        user_id = get_user_from_engineer(row.responsible_engineer)
        if user_id:
            result.add(user_id)
    
    return result


def get_user_from_engineer(engineer_name):
    """
    Get the User ID linked to a Responsible Engineer.
    """
    if not engineer_name:
        return None
    
    try:
        engineer = frappe.get_doc("Responsible Engineer", engineer_name)
        
        # Try to get user from employee link
        if hasattr(engineer, "employee") and engineer.employee:
            employee = frappe.get_doc("Employee", engineer.employee)
            return employee.user_id
        
        # If directly linked to User
        if hasattr(engineer, "user") and engineer.user:
            return engineer.user
        
        # If linked via email
        if hasattr(engineer, "email") and engineer.email:
            user = frappe.db.get_value("User", {"email": engineer.email}, "name")
            return user
        
        return None
    except Exception as e:
        frappe.log_error(f"Error getting user from engineer {engineer_name}: {str(e)}")
        return None


def process_assignments(doc, is_new=False, specific_engineers=None):
    """
    Send assignment emails.
    """
    current_user = frappe.session.user
    assigner_name = frappe.db.get_value("User", current_user, "full_name") or current_user
    
    # Get engineers to process
    if specific_engineers:
        engineers_to_process = specific_engineers
    else:
        engineers_to_process = get_current_engineers(doc)
    
    # Get items to be quoted for email
    items_list = get_opportunity_items(doc)
    
    for user_id in engineers_to_process:
        if not user_id:
            continue
        
        # Send assignment email (skip for current user if they're the assigner)
        is_assigner = (user_id == current_user)
        send_assignment_email(doc, user_id, items_list, assigner_name, is_assigner=is_assigner)


def create_opportunity_todo(doc, user_id):
    """Deprecated: ToDo creation removed in Opportunity-only mode."""
    return


def remove_assignments(doc, removed_engineers):
    """Deprecated: no ToDo cleanup required."""
    return


def get_opportunity_items(doc):
    """Get the list of items from the Opportunity for the email."""
    items = []
    
    if doc.get("items"):
        for item in doc.items:
            items.append({
                "item_code": item.item_code or "",
                "item_name": item.item_name or item.item_code or "",
                "qty": item.qty or 0,
                "uom": item.uom or "",
                "description": item.description or ""
            })
    
    return items


def send_assignment_email(doc, user_id, items_list, assigner_name, is_assigner=False):
    """
    Send assignment email with cyan/turquoise header matching company design.
    """
    try:
        user = frappe.get_doc("User", user_id)
        if not user.email:
            return
        
        # Get user's first name for greeting
        user_name = user.first_name or user.full_name or user_id
        
        # Format closing date
        closing_date_formatted = format_date(doc.expected_closing, "dd/MM/yyyy") if doc.expected_closing else "Not set"
        
        # Email subject
        subject = f"New Opportunity Assigned: {doc.name}"
        
        # Get company name
        company_name = frappe.db.get_single_value("System Settings", "company") or frappe.db.get_default("Company") or "ALKHORA for General Trading Ltd"
        
        # Get site URL
        site_url = frappe.utils.get_url()
        
        # Cyan/Turquoise color for assignment emails
        header_color = "#2DD4BF"
        accent_color = "#2DD4BF"
        
        # Build items table HTML if items exist
        items_html = ""
        if items_list:
            items_rows = ""
            for item in items_list:
                items_rows += f"""
                <tr>
                    <td style="padding: 10px 15px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 13px;">{item['item_code']}</td>
                    <td style="padding: 10px 15px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 13px;">{item['item_name']}</td>
                    <td style="padding: 10px 15px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 13px; text-align: center;">{item['qty']}</td>
                    <td style="padding: 10px 15px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 13px;">{item['uom']}</td>
                </tr>
                """
            
            items_html = f"""
            <!-- Items Section -->
            <p style="margin: 25px 0 15px 0; color: #333333; font-size: 16px; font-weight: 600;">Items to be Quoted:</p>
            <table width="100%" cellpadding="0" cellspacing="0" style="border: 1px solid #eeeeee; border-radius: 5px; margin-bottom: 25px;">
                <tr style="background-color: #f8f8f8;">
                    <th style="padding: 12px 15px; text-align: left; color: #666666; font-size: 13px; font-weight: 600; border-bottom: 2px solid {accent_color};">Item Code</th>
                    <th style="padding: 12px 15px; text-align: left; color: #666666; font-size: 13px; font-weight: 600; border-bottom: 2px solid {accent_color};">Item Name</th>
                    <th style="padding: 12px 15px; text-align: center; color: #666666; font-size: 13px; font-weight: 600; border-bottom: 2px solid {accent_color};">Qty</th>
                    <th style="padding: 12px 15px; text-align: left; color: #666666; font-size: 13px; font-weight: 600; border-bottom: 2px solid {accent_color};">UOM</th>
                </tr>
                {items_rows}
            </table>
            """
        
        message = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f5f5f5;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f5f5f5; padding: 20px 0;">
        <tr>
            <td align="center">
                <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                    
                    <!-- Cyan/Turquoise Header -->
                    <tr>
                        <td style="background-color: {header_color}; padding: 30px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: bold;">New Opportunity Assigned</h1>
                            <p style="margin: 10px 0 0 0; color: #ffffff; font-size: 14px;">Opportunity ID: #{doc.name}</p>
                        </td>
                    </tr>
                    
                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 30px 40px;">
                            
                            <!-- Greeting -->
                            <p style="margin: 0 0 20px 0; color: #333333; font-size: 16px;">Dear {user_name},</p>
                            
                            <p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;">
                                A new opportunity has been assigned to you in the ERP system. Please review the details below and prepare your quotation accordingly.
                            </p>
                            
                            <!-- Details Table -->
                            <table width="100%" cellpadding="0" cellspacing="0" style="border-left: 4px solid {accent_color}; margin-bottom: 25px;">
                                <tr>
                                    <td colspan="2" style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">
                                        Assigned By: <a href="#" style="color: {accent_color}; text-decoration: none; font-weight: 600;">{assigner_name}</a>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; width: 40%; color: #666666; font-size: 14px;">Customer</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.party_name or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Opportunity Type</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.opportunity_type or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Opportunity No.</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.name}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Tender No.</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.get('custom_tender_no') or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Tender Title</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.get('custom_tender_title') or doc.get('title') or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Expected Closing</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: {accent_color}; font-size: 14px; font-weight: 600;">{closing_date_formatted}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; color: #666666; font-size: 14px;">Status</td>
                                    <td style="padding: 12px 20px; color: #333333; font-size: 14px; font-weight: 600;">{doc.status or 'Open'}</td>
                                </tr>
                            </table>
                            
                            {items_html}
                            
                            <p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;">
                                Please prepare your quotation and ensure timely completion before the closing date.
                            </p>
                            
                            <!-- Action Button -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <a href="{site_url}/app/opportunity/{doc.name}" 
                                           style="background-color: {accent_color}; color: #ffffff; padding: 14px 35px; 
                                                  text-decoration: none; border-radius: 25px; font-size: 16px; 
                                                  font-weight: bold; display: inline-block;">
                                            View Task
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Signature -->
                            <p style="margin: 0; color: #333333; font-size: 16px;">Best regards,</p>
                            <p style="margin: 5px 0 0 0; color: #333333; font-size: 16px; font-weight: 600;">{company_name}</p>
                            
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f8f8; padding: 20px; text-align: center; border-top: 1px solid #eeeeee;">
                            <p style="margin: 0; color: #999999; font-size: 12px;">
                                This is an automated message from your ERP system.<br>
                                Please do not reply to this email.
                            </p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """
        
        frappe.sendmail(
            recipients=[user.email],
            subject=subject,
            message=message,
            reference_doctype="Opportunity",
            reference_name=doc.name,
            now=True
        )
        
    except Exception as e:
        frappe.log_error(f"Error sending assignment email to {user_id}: {str(e)}")
