"""
Script to fix the Opportunity Management workspace in the database.

Run this to make the workspace show up properly with links:
    bench --site [your-site] console
    >>> from opportunity_management.fix_workspace import fix_workspace
    >>> fix_workspace()
"""

import frappe
import json


def fix_workspace():
    """Fix the Opportunity Management workspace to show links properly."""

    print("\n" + "="*70)
    print("FIXING OPPORTUNITY MANAGEMENT WORKSPACE")
    print("="*70 + "\n")

    workspace_name = "Opportunity Management"

    # Check if workspace exists
    if frappe.db.exists("Workspace", workspace_name):
        print(f"✓ Found existing workspace: {workspace_name}")
        workspace = frappe.get_doc("Workspace", workspace_name)
        print(f"  Current icon: {workspace.icon}")
        print(f"  Current module: {workspace.module}")
    else:
        print(f"Creating new workspace: {workspace_name}")
        workspace = frappe.new_doc("Workspace")
        workspace.name = workspace_name
        workspace.title = workspace_name

    # Update workspace fields
    workspace.label = "Opportunity Management"
    workspace.title = "Opportunity Management"
    workspace.icon = "briefcase"  # This should show the icon
    workspace.module = "Opportunity Management"
    workspace.is_hidden = 0
    workspace.public = 1
    workspace.sequence_id = 10

    # Clear existing content
    workspace.shortcuts = []
    workspace.links = []
    workspace.charts = []

    # Add shortcuts
    workspace.append("shortcuts", {
        "type": "DocType",
        "label": "Opportunity",
        "link_to": "Opportunity",
        "doc_view": "List"
    })

    # Add links - Views & Dashboards section
    workspace.append("links", {
        "label": "My Opportunities",
        "type": "Page",
        "link_to": "my-opportunities",
        "link_type": "Page",
        "icon": "user",
        "description": "View your assigned opportunities"
    })

    workspace.append("links", {
        "label": "Team Opportunities",
        "type": "Page",
        "link_to": "team-opportunities",
        "link_type": "Page",
        "icon": "users",
        "description": "View team opportunities"
    })

    workspace.append("links", {
        "label": "Opportunity Calendar",
        "type": "Page",
        "link_to": "opportunity-calendar",
        "link_type": "Page",
        "icon": "calendar",
        "description": "Calendar view of opportunities"
    })

    workspace.append("links", {
        "label": "KPI Dashboard",
        "type": "Page",
        "link_to": "opportunity-kpi",
        "link_type": "Page",
        "icon": "bar-chart",
        "description": "View KPI metrics"
    })

    # Add links - Reports & Logs section
    workspace.append("links", {
        "label": "Assignment Log",
        "type": "DocType",
        "link_to": "Opportunity Assignment Log",
        "link_type": "DocType",
        "icon": "list",
        "description": "View assignment logs"
    })

    # Add links - Configuration section
    workspace.append("links", {
        "label": "Employee Team Assignment",
        "type": "Page",
        "link_to": "employee-team-assignment",
        "link_type": "Page",
        "icon": "users",
        "description": "Assign employees to teams"
    })

    workspace.append("links", {
        "label": "Email Templates",
        "type": "DocType",
        "link_to": "Email Template",
        "link_type": "DocType",
        "icon": "mail",
        "description": "Manage email templates"
    })

    # Save
    try:
        workspace.save(ignore_permissions=True)
        frappe.db.commit()
        print("\n✅ Workspace updated successfully!")
        print(f"\nWorkspace details:")
        print(f"  Name: {workspace.name}")
        print(f"  Icon: {workspace.icon}")
        print(f"  Shortcuts: {len(workspace.shortcuts)}")
        print(f"  Links: {len(workspace.links)}")
    except Exception as e:
        print(f"\n❌ Error saving workspace: {str(e)}")
        frappe.log_error(f"Workspace fix error: {str(e)}")
        return False

    print("\n" + "="*70)
    print("WORKSPACE FIX COMPLETE")
    print("="*70)
    print("\nNext steps:")
    print("1. Refresh your browser (Ctrl+Shift+R)")
    print("2. Clear browser cache if needed")
    print("3. Look for 'Opportunity Management' in the sidebar")
    print("4. The icon should now appear")
    print("5. Links should be clickable")
    print("\n")

    return True


def delete_and_recreate_workspace():
    """Delete the workspace completely and recreate it."""

    workspace_name = "Opportunity Management"

    print("\n" + "="*70)
    print("DELETING AND RECREATING WORKSPACE")
    print("="*70 + "\n")

    # Delete if exists
    if frappe.db.exists("Workspace", workspace_name):
        print(f"Deleting existing workspace: {workspace_name}")
        frappe.delete_doc("Workspace", workspace_name, force=True)
        frappe.db.commit()
        print("✓ Deleted")

    # Recreate
    print(f"\nCreating fresh workspace...")
    return fix_workspace()


if __name__ == "__main__":
    fix_workspace()
