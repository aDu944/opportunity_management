"""
Install the Opportunity Management workspace properly.

This creates the workspace with the correct structure for Frappe v15.
"""

import frappe
import json


def install_workspace():
    """Install or update the Opportunity Management workspace."""

    workspace_name = "Opportunity Management"

    print("\n" + "="*70)
    print("INSTALLING OPPORTUNITY MANAGEMENT WORKSPACE")
    print("="*70 + "\n")

    # Delete existing workspace if it exists
    if frappe.db.exists("Workspace", workspace_name):
        print(f"Deleting existing workspace: {workspace_name}")
        try:
            frappe.delete_doc("Workspace", workspace_name, force=True, ignore_permissions=True)
            frappe.db.commit()
            print("✓ Deleted old workspace\n")
        except Exception as e:
            print(f"Warning: Could not delete old workspace: {e}\n")

    # Create new workspace
    print("Creating new workspace...")

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
        "category": "Modules",
        "for_user": "",

        # Add shortcuts
        "shortcuts": [
            {
                "type": "DocType",
                "label": "Opportunity",
                "link_to": "Opportunity",
                "doc_view": "List",
                "color": "Blue"
            }
        ],

        # Add links
        "links": [
            # Views & Dashboards
            {
                "label": "My Opportunities",
                "type": "Link",
                "link_type": "Page",
                "link_to": "my-opportunities",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            {
                "label": "Team Opportunities",
                "type": "Link",
                "link_type": "Page",
                "link_to": "team-opportunities",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            {
                "label": "Opportunity Calendar",
                "type": "Link",
                "link_type": "Page",
                "link_to": "opportunity-calendar",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            {
                "label": "KPI Dashboard",
                "type": "Link",
                "link_type": "Page",
                "link_to": "opportunity-kpi",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            # Reports & Logs
            {
                "label": "Assignment Log",
                "type": "Link",
                "link_type": "DocType",
                "link_to": "Opportunity Assignment Log",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            # Configuration
            {
                "label": "Employee Team Assignment",
                "type": "Link",
                "link_type": "Page",
                "link_to": "employee-team-assignment",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            },
            {
                "label": "Email Templates",
                "type": "Link",
                "link_type": "DocType",
                "link_to": "Email Template",
                "only_for": "",
                "dependencies": "",
                "is_query_report": 0,
                "onboard": 0
            }
        ]
    })

    try:
        workspace.insert(ignore_permissions=True, ignore_if_duplicate=True)
        frappe.db.commit()

        print("✓ Workspace created successfully!\n")
        print(f"Workspace Name: {workspace.name}")
        print(f"Icon: {workspace.icon}")
        print(f"Module: {workspace.module}")
        print(f"Public: {workspace.public}")
        print(f"Shortcuts: {len(workspace.shortcuts)}")
        print(f"Links: {len(workspace.links)}")

        return True

    except Exception as e:
        print(f"✗ Error creating workspace: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        print("\n" + "="*70)
        print("INSTALLATION COMPLETE")
        print("="*70)
        print("\nNext steps:")
        print("1. Run: bench --site [your-site] clear-cache")
        print("2. Run: bench restart")
        print("3. Refresh browser (Ctrl+Shift+R)")
        print("4. Check sidebar for 'Opportunity Management' with briefcase icon")
        print("\n")


if __name__ == "__main__":
    install_workspace()
