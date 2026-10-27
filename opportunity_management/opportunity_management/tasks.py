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
            # Quotation is EXCLUDED: once a quotation is out, the live deadline is the
            # quotation's valid_till, not the inquiry's expected_closing, so chasing
            # the owner about the opportunity is noise. send_manager_weekly_digest
            # already excluded it; these two did not, and 544 of the 552
            # Quotation-stage opportunities carry a date (Ahmed, 2026-10-26).
            "status": ["not in", ["Lost", "Closed", "Converted", "Quotation"]],
            "expected_closing": ["is", "set"]
        },
        fields=["name", "expected_closing", "party_name", "status"]
    )
    
    for opp in opportunities:
        try:
            process_opportunity_reminders(opp, today)
        except Exception as e:
            frappe.log_error(
                title="Opportunity Reminder Error",
                message=f"Error processing reminders for {opp.name}: {str(e)}",
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
    # To = the responsible parties, Cc = their department managers. ONE addressed
    # email, where this used to send a separate message to every address - which is
    # why INQ-520 arrived twice yesterday (Ahmed, 2026-10-25).
    from opportunity_management.opportunity_management.notification_utils import (
        split_opportunity_recipients,
    )

    to, cc = split_opportunity_recipients(doc)
    if not to and not cc:
        frappe.logger().warning(f"No recipients found for Opportunity {doc.name}")
        return

    send_reminder_email(doc, to, cc, days_remaining)

    # The push is per device, so it stays per person - everyone who got the email.
    for user_id in list(to) + list(cc):
        push_reminder(doc, user_id, days_remaining)


def get_assigned_engineers(doc):
    """Get all user IDs assigned to this opportunity (engineers only)."""
    users = set()

    # From custom_resp_eng child table
    if doc.get("custom_resp_eng"):
        for row in doc.custom_resp_eng:
            user_id = get_user_from_engineer(row.responsible_engineer)
            if user_id:
                users.add(user_id)

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

    except Exception as e:
        frappe.log_error(
            title="Get All Recipients Error",
            message=f"Error getting department managers for {doc.name}: {str(e)}",
        )
        # Continue with just engineers if manager lookup fails
        pass

    return recipients


def get_user_from_engineer(engineer_name):
    """Get User ID from Responsible Engineer doctype."""
    if not engineer_name:
        return None

    # If it's already an Employee ID, resolve directly to avoid noisy errors
    if frappe.db.exists("Employee", engineer_name):
        employee = frappe.get_doc("Employee", engineer_name)
        return employee.user_id
    
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


def send_reminder_email(doc, to_emails, cc_emails, days_remaining):
    """One reminder email, addressed: To the responsible parties, Cc their managers."""
    try:
        if not to_emails and not cc_emails:
            return

        # Greeting for however many people are in To. Named, because "Dear Haider,
        # Abdulaziz" still reads correctly where a single %s would not.
        # FULL name. There are three Ayas in the office, so a first name names
        # nobody (Ahmed, 2026-10-26).
        names = []
        for addr in (to_emails or cc_emails):
            full = frappe.db.get_value("User", addr, "full_name")
            names.append(full or (addr or "").split("@")[0])
        user_name = ", ".join(names) or "colleague"
        
        # Format closing date
        closing_date_formatted = format_date(doc.expected_closing, "dd/MM/yyyy") if doc.expected_closing else "Not set"
        
        # Get urgency configuration
        config = get_urgency_config(days_remaining)
        
        # Subject leads with the EVENT, then who it is for, then the reference - so a
        # phone preview is useful before anything is opened (Ahmed, 2026-10-25).
        _cust = doc.get("customer_name") or doc.get("party_name") or ""
        if days_remaining == 0:
            days_text = "today"
            _when = "Closing TODAY"
        elif days_remaining == 1:
            days_text = "1 day"
            _when = "Closing tomorrow"
        else:
            days_text = f"{days_remaining} days"
            _when = f"Closing in {days_text}"
        subject = "{0} · {1} — {2}".format(_when, _cust, doc.name) if _cust else \
            "{0} — {1}".format(_when, doc.name)
        
        # Get company name
        # The opportunity's own company first - the email is about that document.
        # NOT System Settings: it has no `company` field, and get_single_value raises
        # on an unknown fieldname rather than returning None, so the `or` chain that
        # used to follow it never ran. This is what broke the 08:00 job every day
        # from 2026-10-18 (Ahmed, 2026-10-24).
        company_name = (doc.get("company") or frappe.db.get_default("Company")
                        or "ALKHORA for General Trading Ltd")
        
        # Get site URL
        site_url = frappe.utils.get_url()
        
        # Build intro paragraph
        if config["intro_prefix"]:
            intro_html = f'<p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;"><strong style="color: {config["link_color"]};">{config["intro_prefix"]}</strong> {config["intro_message"]}</p>'
        else:
            intro_html = f'<p style="margin: 0 0 25px 0; color: #333333; font-size: 16px;">{config["intro_message"]}</p>'
        
        from opportunity_management.opportunity_management import email_design as D

        # Tiers. Today and tomorrow get a SOLID band; the calmer reminders get the 4px
        # rule, so the band still means "a deadline" when one lands (Ahmed, 2026-10-25).
        if days_remaining == 0:
            accent, band, eyebrow = D.URGENT, True, "Closing today"
        elif days_remaining == 1:
            accent, band, eyebrow = "#b5531d", True, "Closing tomorrow"
        else:
            accent, band, eyebrow = D.QTN, False, f"Closing in {days_text}"

        customer = doc.get("customer_name") or doc.get("party_name") or doc.name
        opp_url = f"{site_url}/app/opportunity/{doc.name}"

        rows = [
            D.row(D.label("Opportunity", "الفرصة"),
                  D.link(doc.name, opp_url, accent if not band else D.QTN, mono=True)),
            D.row(D.label("Closing date", "تاريخ الإغلاق"),
                  f'<strong>{D.esc(closing_date_formatted)}</strong>'),
            # The people actually answerable for it, which the old template never named.
            D.row(D.label("Responsible", "المسؤول"), D.name_cell(user_name)),
        ]
        amount = doc.get("opportunity_amount")
        if amount:
            rows.append(D.row(D.label("Value", "القيمة"),
                              D.esc(D.money(amount, doc.get("currency")))))
        if doc.get("status"):
            rows.append(D.row(D.label("Stage", "المرحلة"), D.esc(doc.get("status"))))

        message = D.envelope(
            accent=accent,
            band=band,
            eyebrow=eyebrow,
            headline=customer,
            subline=(config.get("intro_message_plain")
                     or ("This is the final reminder." if days_remaining == 0 else None)),
            rows=rows,
            actions=[D.button("Open the opportunity", opp_url, accent)],
            # envelope() already signs off with the company; naming it here too
            # printed it twice.
            footnote="You are responsible for this opportunity.",
        )
        
        from opportunity_management.opportunity_management.notification_utils import (
            notification_reply_to,
        )

        frappe.sendmail(
            recipients=to_emails or cc_emails,
            cc=cc_emails if to_emails else None,
            # Without this Frappe writes "<!--recipient-->" into To and substitutes
            # each person's OWN address on their copy, so a manager in Cc sees
            # "To: themselves" and cannot tell who is actually responsible - which is
            # the whole point of the To/Cc split (Ahmed, 2026-10-26).
            expose_recipients="header",
            # Sent From the unattended notification mailbox, so without this every
            # Reply-All would mail a box nobody reads.
            reply_to=notification_reply_to(to_emails or cc_emails),
            subject=subject,
            message=message,
            reference_doctype="Opportunity",
            reference_name=doc.name,
            now=True,
        )

    except Exception as e:
        frappe.log_error(
            title="Opportunity Reminder Email Error",
            message=f"Error emailing {to_emails}/{cc_emails} for {doc.name}: {str(e)}",
        )


def push_reminder(doc, user_id, days_remaining):
    """Mirror the reminder to one person's phone. Silent on any error, so a failed
    push never affects email delivery."""
    # Mobile push — mirror the email as an FCM notification so the
    # assigned engineer sees the reminder on their phone too. Silent
    # on any error so email delivery isn't affected.
    try:
        from opportunity_management.opportunity_management.fcm_utils import (
            send_fcm_to_user,
        )
        party = doc.customer_name or doc.party_name or ""
        if days_remaining == 0:
            fcm_title = "🚨 يغلق اليوم • Closes today"
        elif days_remaining == 1:
            fcm_title = "⏰ يغلق غداً • Closes tomorrow"
        elif days_remaining <= 3:
            fcm_title = f"⏳ يغلق خلال {days_remaining} أيام • Closes in {days_remaining} days"
        else:
            fcm_title = f"📅 يغلق خلال {days_remaining} يوماً • Closes in {days_remaining} days"
        fcm_body = f"{doc.name} • {party}".strip(" •")
        send_fcm_to_user(user_id, title=fcm_title, body=fcm_body, data={
            "type": "opportunity_closing",
            "doctype": "Opportunity",
            "name": doc.name,
            "days_remaining": days_remaining,
        })
    except Exception:
        pass


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

    management_role = frappe.db.sql("""
        SELECT DISTINCT e.user_id
        FROM `tabEmployee` e
        INNER JOIN `tabHas Role` hr ON hr.parent = e.user_id
        WHERE e.department = %(department)s
            AND e.status = 'Active'
            AND e.user_id IS NOT NULL
            AND e.user_id != ''
            AND hr.role = 'Management'
            AND hr.parenttype = 'User'
    """, {"department": department}, as_dict=True)

    for mgr in management_role:
        if mgr.user_id and mgr.user_id not in managers:
            managers.append(mgr.user_id)

    return managers



def _fmt_amount(amt, ccy):
    """Compact money format: 12.4M IQD, 173K USD, 847M IQD."""
    amt = float(amt or 0)
    if amt >= 1_000_000_000:
        return f"{amt/1_000_000_000:.1f}B {ccy}"
    if amt >= 1_000_000:
        return f"{amt/1_000_000:.1f}M {ccy}"
    if amt >= 1_000:
        return f"{amt/1_000:.0f}K {ccy}"
    return f"{amt:.0f} {ccy}"


def _effective_amount(opp_name, opp_amount):
    """Use opportunity_amount if set, else fall back to max linked quotation grand_total."""
    if opp_amount and float(opp_amount) > 0:
        return float(opp_amount), None
    q = frappe.db.sql(
        "SELECT MAX(grand_total), MAX(currency) FROM tabQuotation "
        "WHERE opportunity=%s AND docstatus!=2",
        (opp_name,), as_list=True,
    )
    if q and q[0][0]:
        return float(q[0][0]), q[0][1]
    return 0.0, None


def _totals_by_ccy(items):
    """Group items' amounts by currency, return dict."""
    totals = {}
    for opp in items:
        ccy = opp.get("currency") or "IQD"
        totals[ccy] = totals.get(ccy, 0.0) + float(opp.get("amount") or 0)
    return totals


def _fmt_totals(totals):
    """{'IQD': 12400000, 'USD': 173000} → '12.4M IQD · 173K USD'."""
    if not totals or all(v == 0 for v in totals.values()):
        return "—"
    return " · ".join(_fmt_amount(v, k) for k, v in sorted(totals.items()) if v > 0)


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
            # exclude opps that already have a quotation — they are awaiting customer response, not "open"
            "status": ["not in", ["Lost", "Closed", "Converted", "Quotation"]],
            "expected_closing": ["is", "set"]
        },
        fields=["name", "expected_closing", "party_name", "status", "opportunity_amount", "currency"]
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

            _amt, _q_ccy = _effective_amount(opp.name, opp.opportunity_amount)
            dept_opportunities[department][opp.name] = {
                "name": opp.name,
                "party_name": opp.party_name,
                "expected_closing": opp.expected_closing,
                "status": opp.status,
                "amount": _amt,
                "currency": _q_ccy or opp.currency or "IQD",
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

        from opportunity_management.opportunity_management import email_design as D

        def build_rows(items, overdue_view, limit=15):
            out = []
            for opp in items[:limit]:
                days = opp["days_remaining"]
                # Overdue counts UP in red; due-soon counts DOWN in the normal ink.
                when = ('<strong style="color:%s">%s</strong>' % (D.URGENT, abs(days))
                        if overdue_view else D.esc(days))
                out.append([
                    D.link(opp["name"], f"{site_url}/app/opportunity/{opp['name']}",
                           D.QTN, mono=True),
                    D.name_cell(opp["party_name"] or "-"),
                    D.esc(format_date(opp["expected_closing"], "dd/MM/yyyy")),
                    '<span style="white-space:nowrap">%s</span>'
                    % D.esc(_fmt_amount(opp.get("amount"), opp.get("currency") or "IQD")),
                    when,
                ])
            return out

        HEAD = ["Opportunity", "Customer", "Closing", "Value", "Days"]
        ALIGN = ["left", "left", "left", "right", "center"]

        body = D.stat_strip([
            ("%d" % len(opp_list), "Open"),
            ('<span style="color:%s">%d</span>' % (D.URGENT, len(overdue)), "Overdue"),
            ("%d" % len(due_soon), "Due in 7 days"),
        ], D.QTN)
        body += (
            '<p style="margin:10px 0 0;font-size:12.5px;color:%s">%s</p>'
            % (D.MUTED, D.esc("Open value %s · overdue %s"
                              % (_fmt_totals(_totals_by_ccy(opp_list)),
                                 _fmt_totals(_totals_by_ccy(overdue)))))
        )
        body += D.section("Overdue", D.URGENT)
        body += D.data_table(HEAD, build_rows(overdue, True), ALIGN,
                             empty="Nothing overdue.")
        body += D.section("Due in the next 7 days", D.QTN)
        body += D.data_table(HEAD, build_rows(due_soon, False), ALIGN,
                             empty="Nothing closing this week.")
        if len(overdue) > 15 or len(due_soon) > 15:
            body += ('<p style="margin:12px 0 0;font-size:12px;color:%s">'
                     'Longest lists are cut at 15 rows - open the list for the rest.</p>'
                     % D.FAINT)

        message = D.envelope(
            accent=D.QTN,
            eyebrow="Weekly digest",
            headline=department,
            subline="Week of %s" % format_date(getdate(nowdate()), "d MMMM yyyy"),
            extra_html=body,
            actions=[D.button("Open the opportunity list",
                              f"{site_url}/app/opportunity", D.QTN)],
            footnote="You manage this department.",
        )

        # Event first, then who, then the one number worth acting on - the same
        # shape as every other notification subject.
        subject = "Weekly digest · {0} · {1} overdue".format(department, len(overdue))
        try:
            frappe.sendmail(recipients=managers, subject=subject, message=message,
                            reply_to=", ".join(managers),
                            expose_recipients="header", now=True)
        except Exception as e:
            frappe.log_error(
                title="Manager Digest Error",
                message=f"Digest email failed for {department}: {str(e)}",
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
            # Quotation is EXCLUDED: once a quotation is out, the live deadline is the
            # quotation's valid_till, not the inquiry's expected_closing, so chasing
            # the owner about the opportunity is noise. send_manager_weekly_digest
            # already excluded it; these two did not, and 544 of the 552
            # Quotation-stage opportunities carry a date (Ahmed, 2026-10-26).
            "status": ["not in", ["Lost", "Closed", "Converted", "Quotation"]],
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

    from opportunity_management.opportunity_management import email_design as D

    rows = [[
        D.link(o.name, f"{site_url}/app/opportunity/{o.name}", D.URGENT, mono=True),
        D.name_cell(o.party_name or "-"),
        D.esc(o.status or "Open"),
    ] for o in closings]

    body = D.data_table(
        ["Opportunity", "Customer", "Stage"], rows, ["left", "left", "left"],
        empty="Nothing closes today.")

    message = D.envelope(
        accent=D.URGENT,
        # A band, like the closing-today reminder: this IS a deadline, and the two
        # should read as the same kind of event from the same system.
        band=True,
        eyebrow="Closing today",
        headline="%d opportunit%s" % (len(closings), "y" if len(closings) == 1 else "ies"),
        subline=format_date(today, "EEEE d MMMM yyyy"),
        extra_html=body,
        actions=[D.button("Open the opportunity list",
                          f"{site_url}/app/opportunity", D.URGENT)],
        footnote="You hold the Management role.",
    )

    subject = "Closing today · {0} opportunit{1} — {2}".format(
        len(closings), "y" if len(closings) == 1 else "ies",
        format_date(today, "dd/MM/yyyy"))
    try:
        frappe.sendmail(recipients=recipients, subject=subject, message=message,
                        reply_to=", ".join(recipients),
                        expose_recipients="header", now=True)
    except Exception as e:
        frappe.log_error(
            title="Management Daily Closing Summary Error",
            message=f"Daily closing summary failed: {str(e)}",
        )
