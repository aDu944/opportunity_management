"""Migrate PO status indicator from Client Script → Document States."""
import frappe

STATUS_FIELD = "custom_delivery_payment_status"
CLIENT_SCRIPT = "Purchase Order List — Custom Status Indicator"

# Each state maps a value of STATUS_FIELD to a Frappe indicator color.
STATES = [
    ("Open",                        "Gray"),
    ("In Progress",                 "Purple"),
    ("Received — Payment Due",      "Orange"),
    ("Paid — Awaiting Delivery",    "Blue"),
    ("Completed",                   "Green"),
]


def _remove_client_script():
    if frappe.db.exists("Client Script", CLIENT_SCRIPT):
        frappe.delete_doc("Client Script", CLIENT_SCRIPT, force=True,
                          ignore_permissions=True)
        print(f"deleted Client Script: {CLIENT_SCRIPT}")
    else:
        print(f"no Client Script to delete (already gone)")


def _clear_existing_states():
    """Remove any prior DocType State rows on Purchase Order so we can seed fresh."""
    frappe.db.delete("DocType State", {
        "parent": "Purchase Order",
        "parenttype": "DocType",
        "parentfield": "states",
    })
    print("cleared any existing DocType State rows for Purchase Order")


def _add_states():
    dt = frappe.get_doc("DocType", "Purchase Order")
    for idx, (title, color) in enumerate(STATES, start=1):
        dt.append("states", {
            "title": title,
            "color": color,
            "custom": 1,
        })
    dt.save(ignore_permissions=True)
    print(f"added {len(STATES)} DocType State rows")


def _set_state_field():
    """Point the doctype's state field at our custom status field via
    Customize Form (persists as a Property Setter so ERPNext upgrades
    don't wipe it).
    """
    from frappe.custom.doctype.customize_form.customize_form import CustomizeForm

    cf = frappe.get_doc("Customize Form")
    cf.doc_type = "Purchase Order"
    cf.fetch_to_customize()
    # Newer Frappe uses `state_field` (or `states_field`) — try both.
    for attr in ("state_field", "states_field"):
        if hasattr(cf, attr):
            setattr(cf, attr, STATUS_FIELD)
    cf.save_customization()
    print(f"set state_field on Purchase Order → {STATUS_FIELD}")


def run():
    _remove_client_script()
    _clear_existing_states()
    _add_states()
    _set_state_field()
    frappe.db.commit()
    print("DONE — refresh the PO list view to see native Document State colors")
