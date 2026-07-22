app_name = "opportunity_management"
app_title = "Opportunity Management"
app_publisher = "Your Company"
app_description = "Custom Opportunity Assignment and Notification Management"
app_email = "your@email.com"
app_license = "MIT"

# ============================================================================
# Document Events
# ============================================================================
# Hook into Opportunity save/update events
# DISABLED: Using client script for assignment instead to avoid duplicates
doc_events = {
    "Opportunity": {
        # Keep assignment hooks disabled to avoid duplicates.
        "validate": "opportunity_management.opportunity_management.notification_utils.set_opportunity_notification_recipients",
        "on_update": "opportunity_management.opportunity_management.notification_utils.send_closing_date_extended_notification",
    },
    "Email Queue": {
        "after_insert": "opportunity_management.opportunity_management.notification_utils.log_opportunity_notification_from_email_queue",
        "on_update": "opportunity_management.opportunity_management.notification_utils.update_opportunity_notification_log_status",
    },
    "Quotation": {
        "after_insert": [
            "opportunity_management.quotation_handler.on_quotation_save",
            "opportunity_management.quotation_handler.recalc_opportunity_amount",
            "opportunity_management.opportunity_management.business_hooks.on_quotation_after_insert",
        ],
        "on_update_after_submit": [
            "opportunity_management.quotation_handler.recalc_opportunity_amount",
            "opportunity_management.opportunity_management.business_hooks.on_quotation_update_after_submit",
        ],
        "on_submit": [
            "opportunity_management.quotation_handler.recalc_opportunity_amount",
            "opportunity_management.opportunity_management.business_hooks.on_quotation_submit",
        ],
        "on_cancel": "opportunity_management.quotation_handler.recalc_opportunity_amount",
        "on_trash": "opportunity_management.quotation_handler.recalc_opportunity_amount",
    },
    "Purchase Order": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_purchase_order_submit",
    },
    "Project": {
        "after_insert": "opportunity_management.opportunity_management.business_hooks.on_project_after_insert",
    },
    "Sales Order": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_sales_order_submit",
    },
    "Sales Invoice": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_sales_invoice_submit",
    },
    "Delivery Note": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_delivery_note_submit",
    },
    "Material Request": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_material_request_submit",
    },
    "ToDo": {
        "after_insert": "opportunity_management.opportunity_management.business_hooks.on_todo_after_insert",
    },
    "Employee Checkin": {
        "before_insert": "opportunity_management.opportunity_management.ess_hooks.before_checkin_insert",
        "after_insert": "opportunity_management.opportunity_management.ess_hooks.on_checkin_insert",
    },
    "Leave Application": {
        "after_insert": [
            "opportunity_management.opportunity_management.ess_hooks.on_leave_application_insert",
            "opportunity_management.opportunity_management.business_hooks.on_leave_application_insert_notify_approver",
        ],
        "on_update": "opportunity_management.opportunity_management.ess_hooks.on_leave_application_update",
    },
    "Salary Slip": {
        "on_submit": "opportunity_management.opportunity_management.ess_hooks.on_salary_slip_submit",
    },
    "Expense Claim": {
        "after_insert": "opportunity_management.opportunity_management.business_hooks.on_expense_claim_after_insert",
        "on_update": "opportunity_management.opportunity_management.ess_hooks.on_expense_claim_update",
    },
    "Announcement": {
        "after_insert": "opportunity_management.opportunity_management.ess_hooks.on_announcement_insert",
    },
    "Notification Log": {
        "after_insert": "opportunity_management.opportunity_management.ess_hooks.on_notification_log_insert",
    },
    "Journal Entry": {
        "on_update": "opportunity_management.opportunity_management.business_hooks.on_journal_entry_workflow_change",
        "on_submit": "opportunity_management.opportunity_management.ess_hooks.on_journal_entry_submit",
    },
    "Payment Entry": {
        "on_submit": [
            "opportunity_management.opportunity_management.ess_hooks.on_payment_entry_submit",
            "opportunity_management.opportunity_management.business_hooks.on_payment_entry_submit_broadcast",
        ],
    },
}

# ============================================================================
# Scheduled Tasks (Option B: Fancy color-coded reminder emails)
# ============================================================================
# Daily scheduler for reminder emails at 7, 3, 1, 0 days before closing
scheduler_events = {
    # Run daily at 8:00 AM
    "cron": {
        "0 8 * * *": [
            "opportunity_management.opportunity_management.tasks.send_opportunity_reminders"
        ],
        # Daily closings summary for Management role (7:30 AM)
        "30 7 * * *": [
            "opportunity_management.opportunity_management.tasks.send_management_daily_closing_summary"
        ],
        # Weekly manager digest (Mondays at 9:00 AM)
        "0 9 * * 1": [
            "opportunity_management.opportunity_management.tasks.send_manager_weekly_digest"
        ],
        # Every 5 minutes — process scheduled FCM broadcasts, send the
        # configured daily check-in reminder, force auto-checkout any
        # employees still checked in past the configured hour, and fire the
        # attendance-window reminders (each of which self-gates on
        # time-of-day + a per-day global flag so this cron can safely list
        # them all — they no-op outside their window).
        "*/5 * * * *": [
            "opportunity_management.opportunity_management.api.process_scheduled_broadcasts",
            "opportunity_management.opportunity_management.api.send_daily_checkin_reminders",
            "opportunity_management.opportunity_management.api.auto_checkout_pending_employees",
            # 15 min / 5 min before check-in window closes.
            "opportunity_management.opportunity_management.attendance_reminders.send_checkin_closing_15min_warning",
            "opportunity_management.opportunity_management.attendance_reminders.send_checkin_closing_5min_warning",
            # Hourly 4/5/6/7 PM — remind checked-in-but-not-out employees.
            "opportunity_management.opportunity_management.attendance_reminders.send_checkout_reminder_hourly",
            # 5 min before auto-checkout — final warning before we clock people out.
            "opportunity_management.opportunity_management.attendance_reminders.send_pre_auto_checkout_warning",
        ],
    }
}

# ============================================================================
# Website/Portal Configuration
# ============================================================================
# Add pages to the website module
website_route_rules = [
    {"from_route": "/my-opportunities", "to_route": "My Opportunities"},
    {"from_route": "/opportunity-kpi", "to_route": "Opportunity KPI"},
]

# ============================================================================
# Fixtures (Optional - for exporting custom fields, etc.)
# ============================================================================
fixtures = [
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Employee Checkin"]],
            ["fieldname", "in", ["custom_outside_zone"]]
        ]
    },
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["Opportunity"]],
            ["fieldname", "in", [
                "custom_reminder_7_sent",
                "custom_reminder_3_sent",
                "custom_reminder_1_sent",
                "custom_reminder_0_sent",
                "custom_notification_recipients",
                "custom_last_notification_sent",
                "custom_last_notification_recipients",
                "custom_last_notification_subject",
                "custom_last_notification_status"
            ]]
        ]
    },
    {
        "doctype": "Email Template",
        "filters": [["name", "in", ["Opportunity Assignment", "Opportunity Reminder", "Opportunity Closing Date Extended"]]]
    },
    {
        "doctype": "Workspace",
        "filters": [["name", "in", ["Opportunity Management"]]]
    }
]

# ============================================================================
# Jinja Environment
# ============================================================================
# Add custom jinja methods if needed
# jinja = {
#     "methods": "opportunity_management.opportunity_management.utils.jinja_methods"
# }

# ============================================================================
# App Includes
# ============================================================================
# Override the default HRMS list-view indicator for Employee Checkin so HR
# sees Late / On Time / Outside Zone / Check Out instead of just Off-Shift.
doctype_list_js = {
    "Employee Checkin": "public/js/employee_checkin_list.js",
}

# ============================================================================
# Installation/Setup Hooks
# ============================================================================
after_install = "opportunity_management.opportunity_management.setup.install.after_install"
