"""
Installation hooks for Opportunity Management app.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
    """Called after the app is installed."""
    create_opportunity_custom_fields()
    create_workspace()
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


def create_workspace():
    """Create the Opportunity Management workspace."""

    workspace_name = "Opportunity Management"

    # Delete if exists
    if frappe.db.exists("Workspace", workspace_name):
        try:
            frappe.delete_doc("Workspace", workspace_name, force=True, ignore_permissions=True)
        except Exception as e:
            frappe.log_error(f"Could not delete existing workspace: {str(e)}")

    # Create workspace with shortcuts (cards/links don't work reliably on Frappe Cloud)
    workspace = frappe.get_doc({
        "doctype": "Workspace",
        "name": workspace_name,
        "title": "Opportunity Management",
        "module": "Opportunity Management",
        "icon": "folder-normal",
        "is_hidden": 0,
        "public": 1,

        # All features as shortcuts - these work reliably
        "shortcuts": [
            {
                "type": "DocType",
                "label": "Opportunity",
                "link_to": "Opportunity",
                "doc_view": "List",
                "color": "Blue"
            },
            {
                "type": "Page",
                "label": "My Opportunities",
                "link_to": "my-opportunities",
                "color": "Green"
            },
            {
                "type": "Page",
                "label": "Team Opportunities",
                "link_to": "team-opportunities",
                "color": "Green"
            },
            {
                "type": "Page",
                "label": "Opportunity Calendar",
                "link_to": "opportunity-calendar",
                "color": "Orange"
            },
            {
                "type": "Page",
                "label": "KPI Dashboard",
                "link_to": "opportunity-kpi",
                "color": "Purple"
            },
            {
                "type": "DocType",
                "label": "Assignment Log",
                "link_to": "Opportunity Assignment Log",
                "doc_view": "List",
                "color": "Grey"
            },
            {
                "type": "Page",
                "label": "Employee Team Assignment",
                "link_to": "employee-team-assignment",
                "color": "Red"
            },
            {
                "type": "DocType",
                "label": "Email Templates",
                "link_to": "Email Template",
                "doc_view": "List",
                "color": "Grey"
            }
        ]
    })

    try:
        workspace.insert(ignore_permissions=True, ignore_if_duplicate=True)
        print(f"✓ Created workspace: {workspace_name} with {len(workspace.shortcuts)} shortcuts")
    except Exception as e:
        frappe.log_error(f"Workspace creation error: {str(e)}")
        print(f"Warning: Could not create workspace: {str(e)}")
