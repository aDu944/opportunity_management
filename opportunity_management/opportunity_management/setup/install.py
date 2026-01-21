"""
Installation hooks for Opportunity Management app.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Called after the app is installed."""
    create_opportunity_custom_fields()
    frappe.db.commit()
    print("Opportunity Management app installed successfully!")


def create_opportunity_custom_fields():
    """Create custom fields on Opportunity for tracking reminders."""
    
    custom_fields = {
        "Opportunity": [
            {
                "fieldname": "custom_reminder_7_sent",
                "fieldtype": "Check",
                "label": "7-Day Reminder Sent",
                "insert_after": "expected_closing",
                "hidden": 1,
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "fieldname": "custom_reminder_3_sent",
                "fieldtype": "Check",
                "label": "3-Day Reminder Sent",
                "insert_after": "custom_reminder_7_sent",
                "hidden": 1,
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "fieldname": "custom_reminder_1_sent",
                "fieldtype": "Check",
                "label": "1-Day Reminder Sent",
                "insert_after": "custom_reminder_3_sent",
                "hidden": 1,
                "read_only": 1,
                "no_copy": 1,
            },
            {
                "fieldname": "custom_reminder_0_sent",
                "fieldtype": "Check",
                "label": "Due Date Reminder Sent",
                "insert_after": "custom_reminder_1_sent",
                "hidden": 1,
                "read_only": 1,
                "no_copy": 1,
            },
        ]
    }
    
    create_custom_fields(custom_fields, update=True)
    print("Custom fields created on Opportunity doctype")
