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
doc_events = {
    "Opportunity": {
        "on_update": "opportunity_management.opportunity_management.utils.assignment.on_opportunity_update",
        "after_insert": "opportunity_management.opportunity_management.utils.assignment.on_opportunity_insert",
    },
    "Quotation": {
        "on_submit": "opportunity_management.quotation_handler.on_quotation_submit",
    }
}

# ============================================================================
# Scheduled Tasks
# ============================================================================
# Daily scheduler for reminder emails
# DISABLED: Using Notification doctype instead to avoid duplicate emails
# scheduler_events = {
#     # Run daily at 8:00 AM
#     "cron": {
#         "0 8 * * *": [
#             "opportunity_management.opportunity_management.tasks.send_opportunity_reminders"
#         ]
#     },
#     # Alternative: use daily hook
#     "daily": [
#         "opportunity_management.opportunity_management.tasks.send_opportunity_reminders"
#     ]
# }

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
            ["fieldname", "in", ["custom_resp_eng", "custom_reminder_7_sent", "custom_reminder_3_sent", "custom_reminder_1_sent", "custom_reminder_0_sent"]]
        ]
    },
    {
        "doctype": "Email Template",
        "filters": [["name", "in", ["Opportunity Assignment", "Opportunity Reminder"]]]
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
# Installation/Setup Hooks
# ============================================================================
after_install = "opportunity_management.opportunity_management.setup.install.after_install"
