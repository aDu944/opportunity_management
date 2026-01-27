"""
Scheduled Tasks for Opportunity Management

This module handles:
1. Sending reminder emails at 7, 3, 1, and 0 days before closing date
2. Tracking which reminders have been sent to avoid duplicates
3. Color-coded urgency levels matching company design
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, add_days, date_diff, get_datetime, format_date
from datetime import datetime, timedelta


def send_opportunity_reminders():
    """
    Main scheduled task that runs daily.
    Checks all open opportunities and sends reminders based on closing date.
    """
    frappe.logger().info("Starting Opportunity Reminder Task")
    
    today = getdate(nowdate())
    
    # Get all open opportunities with a closing date
    opportunities = frappe.get_all(
        "Opportunity",
        filters={
            "status": ["not in", ["Lost", "Closed", "Converted"]],
            "expected_closing": ["is", "set"]
        },
        fields=["name", "expected_closing", "party_name", "status"]
    )
    
    for opp in opportunities:
        try:
            process_opportunity_reminders(opp, today)
        except Exception as e:
            frappe.log_error(
                f"Error processing reminders for {opp.name}: {str(e)}",
                "Opportunity Reminder Error"
            )
    
    frappe.db.commit()
    frappe.logger().info("Completed Opportunity Reminder Task")


def process_opportunity_reminders(opp, today):
    """
    Process reminders for a single opportunity.
    
    Reminder schedule with color coding:
    - 7 days before: Yellow/Orange (Important Reminder)
    - 3 days before: Yellow/Orange (Important Reminder)
    - 1 day before: Coral/Salmon (Urgent Reminder)
    - On closing date: Red (CRITICAL ALERT)
    """
    closing_date = getdate(opp.expected_closing)
    days_until_closing = date_diff(closing_date, today)
    
    # Define reminder thresholds
    reminder_config = [
        {"days": 7, "field": "custom_reminder_7_sent", "label": "7 days"},
        {"days": 3, "field": "custom_reminder_3_sent", "label": "3 days"},
        {"days": 1, "field": "custom_reminder_1_sent", "label": "1 day"},
        {"days": 0, "field": "custom_reminder_0_sent", "label": "today"},
    ]
    
    # Get full opportunity doc to check reminder flags
    doc = frappe.get_doc("Opportunity", opp.name)
    
    for config in reminder_config:
        if days_until_closing == config["days"]:
            # Check if this reminder was already sent
            reminder_sent = doc.get(config["field"]) or 0
            
            if not reminder_sent:
                send_reminder_to_all_engineers(doc, config["days"])
                
                # Mark reminder as sent
                frappe.db.set_value("Opportunity", doc.name, config["field"], 1)
                frappe.db.commit()
                
                frappe.logger().info(
                    f"Sent {config['label']} reminder for Opportunity {doc.name}"
                )


def send_reminder_to_all_engineers(doc, days_remaining):
    """
    Send reminder emails to all responsible engineers AND department managers.

    Recipients:
    1. Responsible engineers assigned to the opportunity
    2. Managers/System Managers from the department of the assigner
    """
    # Get all recipients (engineers + managers)
    recipients = get_all_recipients(doc)

    if not recipients:
        frappe.logger().warning(f"No recipients found for Opportunity {doc.name}")
        return

    for user_id in recipients:
        send_reminder_email(doc, user_id, days_remaining)


def get_assigned_engineers(doc):
    """Get all user IDs assigned to this opportunity (engineers only)."""
    users = set()

    # From custom_resp_eng child table
    if doc.get("custom_resp_eng"):
        for row in doc.custom_resp_eng:
            user_id = get_user_from_engineer(row.responsible_engineer)
            if user_id:
                users.add(user_id)

    # Also include users with open ToDos for this opportunity
    todos = frappe.get_all("ToDo", filters={
        "reference_type": "Opportunity",
        "reference_name": doc.name,
        "status": "Open"
    }, fields=["allocated_to"])

    for todo in todos:
        if todo.allocated_to:
            users.add(todo.allocated_to)

    return users


def get_all_recipients(doc):
    """
    Get all recipients for opportunity notifications.

    Returns:
        Set of user IDs including:
        - Responsible engineers
        - Department managers of the assigner
    """
    recipients = set()

    # 1. Get responsible engineers
    engineers = get_assigned_engineers(doc)
    recipients.update(engineers)

    # 2. Get department managers of the person who assigned/created
    try:
        from opportunity_management.opportunity_management.notification_utils import get_department_managers

        # Try owner first (creator), then modified_by (last editor)
        assigner_email = doc.owner or doc.modified_by

        if assigner_email:
            dept_managers = get_department_managers(assigner_email)
            if dept_managers:
                recipients.update(dept_managers)
                frappe.logger().info(
                    f"Added {len(dept_managers)} department managers for {doc.name}: {dept_managers}"
                )

        # Also check ToDos for assigned_by field
        todos = frappe.get_all("ToDo", filters={
            "reference_type": "Opportunity",
            "reference_name": doc.name,
            "status": "Open"
        }, fields=["assigned_by"])

        for todo in todos:
            if todo.assigned_by:
                todo_managers = get_department_managers(todo.assigned_by)
                if todo_managers:
                    recipients.update(todo_managers)

    except Exception as e:
        frappe.log_error(
            f"Error getting department managers for {doc.name}: {str(e)}",
            "Get All Recipients Error"
        )
        # Continue with just engineers if manager lookup fails
        pass

    return recipients


def get_user_from_engineer(engineer_name):
    """Get User ID from Responsible Engineer doctype."""
    if not engineer_name:
        return None
    
    try:
        engineer = frappe.get_doc("Responsible Engineer", engineer_name)
        
        # Try employee link first
        if hasattr(engineer, "employee") and engineer.employee:
            employee = frappe.get_doc("Employee", engineer.employee)
            return employee.user_id
        
        # Try direct user link
        if hasattr(engineer, "user") and engineer.user:
            return engineer.user
        
        # Try email
        if hasattr(engineer, "email") and engineer.email:
            return frappe.db.get_value("User", {"email": engineer.email}, "name")
        
        return None
    except Exception:
        return None


def get_urgency_config(days_remaining):
    """
    Get color and text configuration based on urgency level.
    
    Returns dict with:
    - header_color: Background color for header
    - header_title: Title text in header
    - alert_bg: Alert box background color
    - alert_border: Alert box border color
    - alert_text_color: Alert box text color
    - alert_message: Message in alert box
    - intro_prefix: Bold prefix for intro paragraph
    - intro_message: Main intro message
    - subject_prefix: Email subject prefix
    - link_color: Color for links and dates
    """
    if days_remaining == 0:
        return {
            "header_color": "#DC3545",
            "header_title": "🚨 CRITICAL ALERT 🚨",
            "alert_bg": "#FDECEC",
            "alert_border": "#DC3545",
            "alert_text_color": "#DC3545",
            "alert_message": "🚨 CLOSING TODAY - FINAL REMINDER!",
            "intro_prefix": "CRITICAL:",
            "intro_message": "Your assigned opportunity is closing <strong>TODAY</strong>! This is your final reminder.",
            "subject_prefix": "🚨 CRITICAL ALERT 🚨",
            "link_color": "#DC3545",
            "button_color": "#DC3545",
        }
    elif days_remaining == 1:
        return {
            "header_color": "#FF6B6B",
            "header_title": "Urgent Reminder",
            "alert_bg": "#FFEBEE",
            "alert_border": "#FF6B6B",
            "alert_text_color": "#D32F2F",
            "alert_message": "⏰ Closing Tomorrow - Immediate Action Required!",
            "intro_prefix": "URGENT:",
            "intro_message": "Your assigned opportunity is closing <strong>TOMORROW</strong>! Please take immediate action.",
            "subject_prefix": "Urgent Reminder -",
            "link_color": "#D32F2F",
            "button_color": "#FF6B6B",
        }
    elif days_remaining == 3:
        return {
            "header_color": "#F5A623",
            "header_title": "Important Reminder",
            "alert_bg": "#FFF9E6",
            "alert_border": "#F5A623",
            "alert_text_color": "#D4880F",
            "alert_message": "⏰ Closing in 3 days - Action Required",
            "intro_prefix": "",
            "intro_message": "This is an important reminder! Your assigned opportunity is closing in <strong>3 days</strong>.",
            "subject_prefix": "Reminder -",
            "link_color": "#D4880F",
            "button_color": "#F5A623",
        }
    else:  # 7 days or other
        return {
            "header_color": "#F5A623",
            "header_title": "Important Reminder",
            "alert_bg": "#FFF9E6",
            "alert_border": "#F5A623",
            "alert_text_color": "#D4880F",
            "alert_message": f"⏰ Closing in {days_remaining} days - Action Required",
            "intro_prefix": "",
            "intro_message": f"This is an important reminder! Your assigned opportunity is closing in <strong>{days_remaining} days</strong>.",
            "subject_prefix": "Reminder -",
            "link_color": "#D4880F",
            "button_color": "#F5A623",
        }


def send_reminder_email(doc, user_id, days_remaining):
    """Send a reminder email with color-coded urgency level."""
    try:
        user = frappe.get_doc("User", user_id)
        if not user.email:
            return
        
        # Get user's first name for greeting
        user_name = user.first_name or user.full_name or user_id
        
        # Format closing date
        closing_date_formatted = format_date(doc.expected_closing, "dd/MM/yyyy") if doc.expected_closing else "Not set"
        
        # Get urgency configuration
        config = get_urgency_config(days_remaining)
        
        # Build subject
        if days_remaining == 0:
            days_text = "today"
            subject = f"{config['subject_prefix']} Opportunity {doc.name} Closing TODAY"
        elif days_remaining == 1:
            days_text = "1 day"
            subject = f"{config['subject_prefix']} Opportunity {doc.name} Closing in {days_text}"
        else:
            days_text = f"{days_remaining} days"
            subject = f"{config['subject_prefix']} Opportunity {doc.name} Closing in {days_text}"
        
        # Get company name
        company_name = frappe.db.get_single_value("System Settings", "company") or frappe.db.get_default("Company") or "ALKHORA for General Trading Ltd"
        
        # Get site URL
        site_url = frappe.utils.get_url()
        
        # Build intro paragraph
        if config["intro_prefix"]:
            intro_html = f'<p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;"><strong style="color: {config["link_color"]};">{config["intro_prefix"]}</strong> {config["intro_message"]}</p>'
        else:
            intro_html = f'<p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;">{config["intro_message"]}</p>'
        
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
                    
                    <!-- Colored Header -->
                    <tr>
                        <td style="background-color: {config['header_color']}; padding: 30px; text-align: center;">
                            <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: bold;">{config['header_title']}</h1>
                            <p style="margin: 10px 0 0 0; color: #ffffff; font-size: 14px;">Opportunity ID: #{doc.name}</p>
                        </td>
                    </tr>
                    
                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 30px 40px;">
                            
                            <!-- Greeting -->
                            <p style="margin: 0 0 20px 0; color: #333333; font-size: 16px;">Dear {user_name},</p>
                            
                            {intro_html}
                            
                            <!-- Alert Box -->
                            <div style="background-color: {config['alert_bg']}; border-left: 4px solid {config['alert_border']}; padding: 15px 20px; margin-bottom: 25px;">
                                <p style="margin: 0; color: {config['alert_text_color']}; font-size: 15px; font-weight: 600;">
                                    {config['alert_message']}
                                </p>
                            </div>
                            
                            <!-- Details Table -->
                            <table width="100%" cellpadding="0" cellspacing="0" style="border-left: 4px solid {config['alert_border']}; margin-bottom: 25px;">
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; width: 40%; color: #666666; font-size: 14px;">Opportunity No.</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: {config['link_color']}; font-size: 14px; font-weight: 600;">
                                        <a href="{site_url}/app/opportunity/{doc.name}" style="color: {config['link_color']}; text-decoration: none;">{doc.name}</a>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Customer</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.party_name or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #666666; font-size: 14px;">Opportunity Type</td>
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: #333333; font-size: 14px; font-weight: 600;">{doc.opportunity_type or 'N/A'}</td>
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
                                    <td style="padding: 12px 20px; border-bottom: 1px solid #eeeeee; color: {config['link_color']}; font-size: 14px; font-weight: 600;">{closing_date_formatted}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px 20px; color: #666666; font-size: 14px;">Status</td>
                                    <td style="padding: 12px 20px; color: #333333; font-size: 14px; font-weight: 600;">{doc.status or 'Open'}</td>
                                </tr>
                            </table>
                            
                            <p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;">
                                Please ensure you complete your quotation and follow up accordingly.
                            </p>
                            
                            <!-- Action Button -->
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <a href="{site_url}/app/opportunity/{doc.name}" 
                                           style="background-color: {config['button_color']}; color: #ffffff; padding: 14px 35px; 
                                                  text-decoration: none; border-radius: 25px; font-size: 16px; 
                                                  font-weight: bold; display: inline-block;">
                                            Take Action Now
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
                                This is an automated reminder from your ERP system.<br>
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
        frappe.log_error(
            f"Error sending reminder to {user_id} for {doc.name}: {str(e)}",
            "Opportunity Reminder Email Error"
        )


def reset_reminder_flags(opportunity_name):
    """
    Utility function to reset reminder flags (useful if closing date changes).
    Can be called from a doc_event if needed.
    """
    frappe.db.set_value("Opportunity", opportunity_name, {
        "custom_reminder_7_sent": 0,
        "custom_reminder_3_sent": 0,
        "custom_reminder_1_sent": 0,
        "custom_reminder_0_sent": 0,
    })
    frappe.db.commit()


def _get_department_for_user(user_id):
    if not user_id:
        return None
    return frappe.db.get_value(
        "Employee",
        {"user_id": user_id, "status": "Active"},
        "department"
    )


def _get_department_managers_by_department(department):
    if not department:
        return []

    managers = []

    dept_managers = frappe.db.sql("""
        SELECT DISTINCT e.user_id
        FROM `tabEmployee` e
        WHERE e.department = %(department)s
            AND e.status = 'Active'
            AND e.user_id IS NOT NULL
            AND e.user_id != ''
            AND (
                e.designation LIKE '%%Manager%%'
                OR e.designation LIKE '%%Head%%'
                OR e.designation LIKE '%%Director%%'
            )
    """, {"department": department}, as_dict=True)

    for mgr in dept_managers:
        if mgr.user_id and mgr.user_id not in managers:
            managers.append(mgr.user_id)

    system_managers = frappe.db.sql("""
        SELECT DISTINCT e.user_id
        FROM `tabEmployee` e
        INNER JOIN `tabHas Role` hr ON hr.parent = e.user_id
        WHERE e.department = %(department)s
            AND e.status = 'Active'
            AND e.user_id IS NOT NULL
            AND e.user_id != ''
            AND hr.role = 'System Manager'
            AND hr.parenttype = 'User'
    """, {"department": department}, as_dict=True)

    for mgr in system_managers:
        if mgr.user_id and mgr.user_id not in managers:
            managers.append(mgr.user_id)

    return managers


def send_manager_weekly_digest():
    """
    Weekly digest to department managers.
    Includes overdue and due-soon opportunities for their departments.
    """
    today = getdate(nowdate())
    upcoming = add_days(today, 7)

    from opportunity_management.opportunity_management.notification_utils import get_opportunity_assigned_users

    opportunities = frappe.get_all(
        "Opportunity",
        filters={
            "status": ["not in", ["Lost", "Closed", "Converted"]],
            "expected_closing": ["is", "set"]
        },
        fields=["name", "expected_closing", "party_name", "status"]
    )

    dept_opportunities = {}
    user_department_cache = {}

    for opp in opportunities:
        doc = frappe.get_doc("Opportunity", opp.name)
        assigned_users = get_opportunity_assigned_users(doc)

        for user_id in assigned_users:
            if user_id not in user_department_cache:
                user_department_cache[user_id] = _get_department_for_user(user_id)
            department = user_department_cache[user_id]

            if not department:
                continue

            if department not in dept_opportunities:
                dept_opportunities[department] = {}

            dept_opportunities[department][opp.name] = {
                "name": opp.name,
                "party_name": opp.party_name,
                "expected_closing": opp.expected_closing,
                "status": opp.status
            }

    site_url = frappe.utils.get_url()

    for department, opp_map in dept_opportunities.items():
        managers = _get_department_managers_by_department(department)
        if not managers:
            continue

        opp_list = list(opp_map.values())
        for opp in opp_list:
            opp["days_remaining"] = date_diff(getdate(opp["expected_closing"]), today)

        overdue = [o for o in opp_list if o["days_remaining"] < 0]
        due_soon = [o for o in opp_list if 0 <= o["days_remaining"] <= 7]

        overdue.sort(key=lambda x: x["days_remaining"])
        due_soon.sort(key=lambda x: x["days_remaining"])

        def build_rows(items, limit=10):
            rows = ""
            for opp in items[:limit]:
                rows += f"""
                    <tr>
                        <td><a href="{site_url}/app/opportunity/{opp['name']}">{opp['name']}</a></td>
                        <td>{opp['party_name'] or '-'}</td>
                        <td>{format_date(opp['expected_closing'], 'dd/MM/yyyy')}</td>
                        <td style="text-align:center;">{opp['days_remaining']}</td>
                    </tr>
                """
            return rows

        overdue_rows = build_rows(overdue)
        due_rows = build_rows(due_soon)

        message = f"""
        <div style="font-family: Arial, sans-serif;">
            <h2>Weekly Opportunity Digest - {department}</h2>
            <p>Summary for the next 7 days:</p>
            <ul>
                <li>Total open: {len(opp_list)}</li>
                <li>Overdue: {len(overdue)}</li>
                <li>Due in 7 days: {len(due_soon)}</li>
            </ul>

            <h3>Overdue Opportunities</h3>
            <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Opportunity</th>
                        <th>Customer</th>
                        <th>Closing Date</th>
                        <th>Days Overdue</th>
                    </tr>
                </thead>
                <tbody>
                    {overdue_rows or '<tr><td colspan="4">None</td></tr>'}
                </tbody>
            </table>

            <h3>Due in 7 Days</h3>
            <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; width: 100%;">
                <thead>
                    <tr>
                        <th>Opportunity</th>
                        <th>Customer</th>
                        <th>Closing Date</th>
                        <th>Days Remaining</th>
                    </tr>
                </thead>
                <tbody>
                    {due_rows or '<tr><td colspan="4">None</td></tr>'}
                </tbody>
            </table>
        </div>
        """

        subject = f"Weekly Opportunity Digest - {department}"
        try:
            frappe.sendmail(recipients=managers, subject=subject, message=message, now=True)
        except Exception as e:
            frappe.log_error(
                f"Digest email failed for {department}: {str(e)}",
                "Manager Digest Error"
            )


def send_management_daily_closing_summary():
    """
    Daily summary of opportunities closing today, sent to users with "Management" role.
    """
    today = getdate(nowdate())
    site_url = frappe.utils.get_url()

    closings = frappe.get_all(
        "Opportunity",
        filters={
            "status": ["not in", ["Lost", "Closed", "Converted"]],
            "expected_closing": today
        },
        fields=["name", "party_name", "status", "expected_closing"]
    )

    users = frappe.get_all(
        "Has Role",
        filters={
            "role": "Management",
            "parenttype": "User"
        },
        fields=["parent"]
    )
    recipients = sorted({u.parent for u in users if u.parent})

    if not recipients:
        frappe.logger().warning("No recipients found for Management role")
        return

    def build_rows(items):
        rows = ""
        for opp in items:
            rows += f"""
                <tr>
                    <td style="padding: 8px 10px; border-bottom: 1px solid #e9ecef;">
                        <a href="{site_url}/app/opportunity/{opp.name}" style="color: #ff9800; text-decoration: none; font-weight: 600;">{opp.name}</a>
                    </td>
                    <td style="padding: 8px 10px; border-bottom: 1px solid #e9ecef;">{opp.party_name or '-'}</td>
                    <td style="padding: 8px 10px; border-bottom: 1px solid #e9ecef; color: #FF0000; font-weight: 700;">
                        {format_date(opp.expected_closing, 'dd/MM/yyyy')}
                    </td>
                    <td style="padding: 8px 10px; border-bottom: 1px solid #e9ecef;">{opp.status or 'Open'}</td>
                </tr>
            """
        return rows

    rows = build_rows(closings)

    message = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Closing Summary</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {{font-family: Arial, Helvetica, sans-serif !important;}}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; min-width: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; background-color: #f5f7fa; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f5f7fa;">
        <tr>
            <td align="center" style="padding: 20px 15px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 650px; border-collapse: collapse; background-color: #ffffff; border-radius: 12px; box-shadow: 0 10px 25px rgba(255,193,7,0.15); overflow: hidden;">
                    <!-- Header Banner -->
                    <tr>
                        <td align="center" style="background-color: #ffc107; padding: 25px 20px;">
                            <h1 style="color: #ffffff; margin: 0; font-weight: 600; font-size: 24px;">Daily Closing Summary</h1>
                            <p style="color: #fff3cd; margin: 10px 0 0 0; font-size: 16px;">Date: {format_date(today, 'dd/MM/yyyy')}</p>
                        </td>
                    </tr>

                    <!-- Content Area -->
                    <tr>
                        <td style="padding: 30px 20px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 20px;">
                                        Here is today's summary of opportunities closing <strong>today</strong>.
                                    </td>
                                </tr>

                                <!-- Alert Box -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #fff3cd; border-left: 4px solid #ffc107; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    <p style="color: #856404; margin: 0; font-weight: 700; font-size: 16px;">⏰ Closing Today - {len(closings)} Opportunity(ies)</p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>

                                <!-- Opportunity Info Card -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8f9fa; border-left: 4px solid #ffc107; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 20px;">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                                        <thead>
                                                            <tr>
                                                                <th style="text-align: left; padding: 8px 10px; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px; width: 30%;">Opportunity</th>
                                                                <th style="text-align: left; padding: 8px 10px; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Customer</th>
                                                                <th style="text-align: left; padding: 8px 10px; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Closing Date</th>
                                                                <th style="text-align: left; padding: 8px 10px; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Status</th>
                                                            </tr>
                                                        </thead>
                                                        <tbody>
                                                            {rows or '<tr><td colspan="4" style="padding: 10px;">None</td></tr>'}
                                                        </tbody>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>

                                <!-- CTA Button -->
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{site_url}/app/opportunity" style="height:45px;v-text-anchor:middle;width:230px;" arcsize="50%" stroke="f" fillcolor="#ff9800">
                                        <w:anchorlock/>
                                        <center>
                                        <![endif]-->
                                        <a href="{site_url}/app/opportunity" style="display: inline-block; background-color: #ff9800; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 25px; border-radius: 50px; font-size: 16px; box-shadow: 0 4px 10px rgba(255,152,0,0.3); mso-padding-alt: 0; text-underline-color: #ff9800;"><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%;mso-text-raise:20pt">&nbsp;</i><![endif]--><span style="mso-text-raise:10pt;">Open Opportunities</span><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%">&nbsp;</i><![endif]--></a>
                                        <!--[if mso]>
                                        </center>
                                        </v:roundrect>
                                        <![endif]-->
                                    </td>
                                </tr>

                                <tr>
                                    <td style="padding-top: 10px;">
                                        <p style="color: #444; margin: 0 0 5px 0; font-size: 16px;">Best regards,</p>
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">ALKHORA for General Trading Ltd</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                            <p style="color: #6c757d; margin: 0; font-size: 13px;">This is an automated summary from your ERP system.</p>
                            <p style="color: #6c757d; margin: 5px 0 0 0; font-size: 13px;">Please do not reply to this email.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
    """

    subject = f"Daily Closing Summary - {format_date(today, 'dd/MM/yyyy')}"
    try:
        frappe.sendmail(recipients=recipients, subject=subject, message=message, now=True)
    except Exception as e:
        frappe.log_error(
            f"Daily closing summary failed: {str(e)}",
            "Management Daily Closing Summary Error"
        )
