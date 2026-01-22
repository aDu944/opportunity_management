"""
Patch to create workspace.
This will run during bench migrate.
"""

import frappe


def execute():
    """Create the Opportunity Management workspace."""

    from opportunity_management.opportunity_management.setup.install import create_workspace

    try:
        create_workspace()
        frappe.db.commit()
        print("✓ Workspace created successfully")
    except Exception as e:
        frappe.log_error(f"Workspace creation patch error: {str(e)}")
        print(f"Error creating workspace: {str(e)}")
