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
        "on_trash":  "opportunity_management.opportunity_management.notification_utils.delete_related_notification_logs",
        "on_cancel": "opportunity_management.opportunity_management.notification_utils.delete_related_notification_logs",
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
        "after_insert": "opportunity_management.po_status.on_po_after_insert",
        "on_submit": [
            "opportunity_management.opportunity_management.business_hooks.on_purchase_order_submit",
            "opportunity_management.po_status.on_po_submit",
        ],
        "on_update_after_submit": "opportunity_management.po_status.on_po_update_after_submit",
        "on_cancel": "opportunity_management.po_status.on_po_cancel",
    },
    "Purchase Receipt": {
        "after_insert": "opportunity_management.po_status.on_purchase_receipt_change",
        "on_submit": [
            "opportunity_management.opportunity_management.business_hooks.on_purchase_receipt_submit",
            "opportunity_management.po_status.on_purchase_receipt_change",
        ],
        "on_cancel": "opportunity_management.po_status.on_purchase_receipt_change",
        "on_trash": "opportunity_management.po_status.on_purchase_receipt_change",
    },
    "Comment": {
        "after_insert": "opportunity_management.opportunity_management.business_hooks.on_comment_after_insert",
    },
    "Project": {
        "after_insert": "opportunity_management.opportunity_management.business_hooks.on_project_after_insert",
        "validate": "opportunity_management.rp_enforce.enforce_project_responsible_party",
    },
    "Sales Order": {
        "after_insert": "opportunity_management.quotation_handler.on_sales_order_save",
        "on_submit": [
            "opportunity_management.quotation_handler.on_sales_order_save",
            "opportunity_management.opportunity_management.business_hooks.on_sales_order_submit",
        ],
    },
    "Sales Invoice": {
        "on_submit": "opportunity_management.opportunity_management.business_hooks.on_sales_invoice_submit",
    },
    "Shipping": {
        "on_submit": "opportunity_management.po_status.on_shipping_change",
        "on_cancel": "opportunity_management.po_status.on_shipping_change",
        "on_update_after_submit": "opportunity_management.po_status.on_shipping_change",
    },
    "Purchase Invoice": {
        "on_submit": "opportunity_management.po_status.on_purchase_invoice_change",
        "on_cancel": "opportunity_management.po_status.on_purchase_invoice_change",
        "on_update_after_submit": "opportunity_management.po_status.on_purchase_invoice_change",
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
            "opportunity_management.po_status.on_payment_entry_change",
        ],
        "on_cancel": "opportunity_management.po_status.on_payment_entry_change",
    },
    # WhatsApp team inbox. `after_insert` threads the message onto a
    # WhatsApp Conversation; `on_update` republishes Meta's status ticks
    # (frappe_whatsapp's status callback does doc.save(), so on_update fires).
    # Both handlers swallow every exception internally — they run inside
    # Meta's webhook request and must never roll back the message insert.
    "WhatsApp Message": {
        "after_insert": "opportunity_management.opportunity_management.whatsapp_hooks.on_message_after_insert",
        "on_update": "opportunity_management.opportunity_management.whatsapp_hooks.on_message_on_update",
    },
}


# ============================================================================
# Overridden Whitelisted Methods
# ============================================================================
# Meta already points at frappe_whatsapp's webhook URL. Overriding the method
# lets us verify X-Hub-Signature-256, dedupe on message_id and coerce the
# inbound types frappe_whatsapp KeyErrors on, without forking that app.
override_whitelisted_methods = {
    "frappe_whatsapp.utils.webhook.webhook": "opportunity_management.opportunity_management.whatsapp_webhook.webhook",
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
            # WhatsApp inbox housekeeping — both self-gate on WhatsApp Inbox
            # Settings (privatize_outbound_after_sent / auto_resolve_after_days)
            # and no-op when those are off.
            "opportunity_management.opportunity_management.whatsapp_jobs.privatize_sent_outbound_media",
            "opportunity_management.opportunity_management.whatsapp_jobs.auto_resolve_stale_conversations",
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
    },
    # ── WhatsApp team inbox ──────────────────────────────────────────────
    # NOTE: fixtures are synced AFTER post-model-sync patches, so the same
    # objects are also created idempotently in
    # whatsapp_setup.create_whatsapp_message_custom_fields() /
    # ensure_whatsapp_roles_and_perms(), which the backfill patch and
    # after_install call. These blocks exist so a site export carries them.
    {
        "doctype": "Custom Field",
        "filters": [
            ["dt", "in", ["WhatsApp Message"]],
            ["fieldname", "in", [
                "custom_conversation",
                "custom_read",
                "custom_sent_by",
                "custom_is_auto",
                "custom_media_private",
                "custom_body_text"
            ]]
        ]
    },
    {
        "doctype": "Role",
        "filters": [["name", "in", ["WhatsApp Agent"]]]
    },
    {
        "doctype": "Custom DocPerm",
        "filters": [
            ["parent", "in", ["WhatsApp Message", "WhatsApp Templates", "WhatsApp Account"]],
            ["role", "in", ["WhatsApp Agent", "WhatsApp Manager"]]
        ]
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

# ── WhatsApp Desk inbox assets (M3) ──────────────────────────────────────────
# The files these point at landed with the M3 workstream, so the block is live.
doctype_js = {
    "Contact": "public/js/whatsapp_crm_form.js",
    "Lead": "public/js/whatsapp_crm_form.js",
    "Customer": "public/js/whatsapp_crm_form.js",
}
app_include_css = ["/assets/opportunity_management/css/whatsapp_inbox.css"]

# ============================================================================
# Installation/Setup Hooks
# ============================================================================
after_install = "opportunity_management.opportunity_management.setup.install.after_install"


# --- Bundled Client Scripts (migrated from DB for perf) ---
app_include_js = [
    'je_project_and_opportunity.bundle.js',
    'opportunity_list_year_first_sort.bundle.js',
    'opportunity_status.bundle.js',
    'opportunity_customer_abr.bundle.js',
    'quotation_general_customer_name.bundle.js',
    'quotation_subtotals_by_section.bundle.js',
    'quotation_title_row.bundle.js',
    'purchase_order_list_extend.bundle.js',
]
