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
        "after_insert": "opportunity_management.quotation_handler.on_quotation_save",
    }
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
        ]
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
            ["dt", "in", ["Opportunity"]],
            ["fieldname", "in", [
                "custom_resp_eng",
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
# Include FullCalendar library
app_include_css = [
    "https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/main.min.css"
]

app_include_js = [
    "https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/main.min.js",
    "https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/daygrid/main.min.js",
    "https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/timegrid/main.min.js",
    "https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/list/main.min.js"
]

# ============================================================================
# Installation/Setup Hooks
# ============================================================================
after_install = "opportunity_management.opportunity_management.setup.install.after_install"
