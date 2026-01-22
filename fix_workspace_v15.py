"""
Fix workspace for Frappe v15 - proper card-based layout
"""

import frappe
import json


def fix_workspace_v15():
    """Create workspace with proper card structure for Frappe v15."""

    workspace_name = "Opportunity Management"

    print("\n" + "="*70)
    print("FIXING WORKSPACE FOR FRAPPE V15")
    print("="*70 + "\n")

    # Delete existing
    if frappe.db.exists("Workspace", workspace_name):
        print(f"Deleting existing workspace...")
        frappe.delete_doc("Workspace", workspace_name, force=True, ignore_permissions=True)
        frappe.db.commit()
        print("✓ Deleted\n")

    # Create with card-based structure
    print("Creating new workspace with cards...")

    workspace = frappe.get_doc({
        "doctype": "Workspace",
        "name": workspace_name,
        "title": "Opportunity Management",
        "module": "Opportunity Management",
        "icon": "briefcase",
        "is_hidden": 0,
        "public": 1,
        "extends": "",
        "extends_another_page": 0,
        "for_user": "",
        "parent_page": "",

        # Shortcuts
        "shortcuts": [
            {
                "type": "DocType",
                "label": "Opportunity",
                "link_to": "Opportunity",
                "doc_view": "List",
                "color": "Blue",
                "format": "{} Open"
            }
        ],

        # Cards with proper grouping
        "cards": [
            # Card 1: Views & Dashboards
            {
                "label": "Views & Dashboards",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "my-opportunities",
                        "label": "My Opportunities",
                        "icon": "user",
                        "description": "View your assigned opportunities"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "team-opportunities",
                        "label": "Team Opportunities",
                        "icon": "users",
                        "description": "View team opportunities"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "opportunity-calendar",
                        "label": "Opportunity Calendar",
                        "icon": "calendar",
                        "description": "Calendar view"
                    },
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "opportunity-kpi",
                        "label": "KPI Dashboard",
                        "icon": "bar-chart",
                        "description": "View KPI metrics"
                    }
                ]
            },
            # Card 2: Reports & Logs
            {
                "label": "Reports & Logs",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "DocType",
                        "link_to": "Opportunity Assignment Log",
                        "label": "Assignment Log",
                        "icon": "list",
                        "description": "View assignment logs"
                    }
                ]
            },
            # Card 3: Configuration
            {
                "label": "Configuration",
                "links": [
                    {
                        "type": "Link",
                        "link_type": "Page",
                        "link_to": "employee-team-assignment",
                        "label": "Employee Team Assignment",
                        "icon": "users",
                        "description": "Assign employees to teams"
                    },
                    {
                        "type": "Link",
                        "link_type": "DocType",
                        "link_to": "Email Template",
                        "label": "Email Templates",
                        "icon": "mail",
                        "description": "Manage email templates"
                    }
                ]
            }
        ]
    })

    try:
        workspace.insert(ignore_permissions=True, ignore_if_duplicate=True)
        frappe.db.commit()

        print("✓ Workspace created!\n")
        print(f"Name: {workspace.name}")
        print(f"Icon: {workspace.icon}")
        print(f"Cards: {len(workspace.cards)}")
        print(f"Shortcuts: {len(workspace.shortcuts)}")

        # Count total links
        total_links = sum(len(card.get("links", [])) for card in workspace.cards)
        print(f"Total Links: {total_links}")

        return True

    except Exception as e:
        print(f"✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        print("\n" + "="*70)
        print("DONE - Now clear cache and restart!")
        print("="*70 + "\n")


if __name__ == "__main__":
    fix_workspace_v15()
