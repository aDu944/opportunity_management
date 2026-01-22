"""
Setup workspace - can be called from Frappe UI or during migration.
"""

import frappe


def execute():
    """
    This can be run as a script from Frappe Cloud.
    Or called during bench migrate.
    """
    from opportunity_management.opportunity_management.setup.install import create_workspace

    print("Setting up Opportunity Management workspace...")
    create_workspace()
    frappe.db.commit()
    print("Done! Please refresh your browser.")


if __name__ == "__main__":
    execute()
