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

    # Create workspace with card structure (Frappe v15)
    workspace = frappe.get_doc({
        "doctype": "Workspace",
        "name": workspace_name,
        "title": "Opportunity Management",
        "module": "Opportunity Management",
        "icon": "briefcase",
        "is_hidden": 0,
        "public": 1,

        # Shortcuts
        "shortcuts": [
            {
                "type": "DocType",
                "label": "Opportunity",
                "link_to": "Opportunity",
                "doc_view": "List",
                "color": "Blue"
            }
        ],

        # Cards with links
        "cards": [
            {
                "label": "Views & Dashboards",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "my-opportunities",
                        "label": "My Opportunities",
                        "description": "View your assigned opportunities"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "team-opportunities",
                        "label": "Team Opportunities",
                        "description": "View team opportunities"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "opportunity-calendar",
                        "label": "Opportunity Calendar",
                        "description": "Calendar view"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "opportunity-kpi",
                        "label": "KPI Dashboard",
                        "description": "View KPI metrics"
                    }
                ]
            },
            {
                "label": "Reports & Logs",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "DocType",
                        "link_to": "Opportunity Assignment Log",
                        "label": "Assignment Log",
                        "description": "View assignment logs"
                    }
                ]
            },
            {
                "label": "Configuration",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "employee-team-assignment",
                        "label": "Employee Team Assignment",
                        "description": "Assign employees to teams"
                    },
                    {
                        "type": "Link",
                        "link_type": "DocType",
                        "link_to": "Email Template",
                        "label": "Email Templates",
                        "description": "Manage email templates"
                    }
                ]
            }
        ]
    })

    try:
        workspace.insert(ignore_permissions=True, ignore_if_duplicate=True)
        print(f"✓ Created workspace: {workspace_name} with {len(workspace.cards)} cards")
    except Exception as e:
        frappe.log_error(f"Workspace creation error: {str(e)}")
        print(f"Warning: Could not create workspace: {str(e)}")
