"""
WhatsApp auto menu: seed the agent groups, tags and menus decided on
2026-10-28 (opportunity_management/auto_menu_seed_data.py) and point Inbox
Settings › Root Menu at `root` when it is empty.

Idempotent: creates only what is missing and never overwrites an existing
group, tag or menu. `enable_menu` is left as it is (off until the user turns
it on). Group members / notify user that do not exist as Users are skipped.
"""

import frappe

from opportunity_management.opportunity_management import auto_menu_seed_data as D

SETTINGS = "WhatsApp Inbox Settings"
TAG_COLORS = {"Vendor": "#6B7280", "Careers": "#8B5CF6", "Follow-up": "#F59E0B"}


def _ensure_doctypes():
    for name in ("whatsapp_menu_option", "whatsapp_menu"):
        title = name.replace("_", " ").title().replace("Whatsapp", "WhatsApp")
        if not frappe.db.table_exists(title):
            frappe.reload_doc("opportunity_management", "doctype", name, force=True)
    if not frappe.db.has_column("WhatsApp Conversation", "menu_state"):
        frappe.reload_doc("opportunity_management", "doctype", "whatsapp_conversation", force=True)
    frappe.reload_doc("opportunity_management", "doctype", "whatsapp_inbox_settings")


def _users(emails):
    return [e for e in emails if frappe.db.exists("User", e)]


def _seed_groups():
    if not frappe.db.table_exists("WhatsApp Agent Group"):
        return []
    created = []
    notify = D.NOTIFY_USER if frappe.db.exists("User", D.NOTIFY_USER) else None
    for name, members in D.GROUPS:
        if frappe.db.exists("WhatsApp Agent Group", name):
            continue
        doc = frappe.get_doc({
            "doctype": "WhatsApp Agent Group", "group_name": name, "is_active": 1, "strategy": "Ring",
            "first_response_timeout_minutes": 30, "notify_user": notify, "out_of_hours": "Hold",
            "members": [{"user": u, "is_active": 1} for u in _users(members)],
        })
        doc.insert(ignore_permissions=True)
        created.append(name)
    return created


def _seed_tags():
    created = []
    for tag in D.TAGS:
        if not frappe.db.exists("WhatsApp Tag", tag):
            frappe.get_doc({"doctype": "WhatsApp Tag", "tag_name": tag, "is_active": 1,
                            "color": TAG_COLORS.get(tag)}).insert(ignore_permissions=True)
            created.append(tag)
    return created


def _seed_menus():
    created = []
    for menu in D.MENUS:
        if frappe.db.exists("WhatsApp Menu", menu["menu_key"]):
            continue
        values = {k: v for k, v in menu.items() if k != "options"}
        doc = frappe.get_doc(dict(values, doctype="WhatsApp Menu",
                                  options=[dict(o) for o in menu["options"]]))
        doc.flags.ignore_links = True  # menus link each other; inserted in order
        doc.insert(ignore_permissions=True)
        created.append(menu["menu_key"])
    return created


def execute():
    _ensure_doctypes()
    groups = _seed_groups()
    tags = _seed_tags()
    menus = _seed_menus()
    if not frappe.db.get_single_value(SETTINGS, "root_menu") and frappe.db.exists("WhatsApp Menu", D.ROOT_MENU):
        frappe.db.set_single_value(SETTINGS, "root_menu", D.ROOT_MENU)
    frappe.db.commit()
    print("WhatsApp auto menu seeded — groups: {0}; tags: {1}; menus: {2}".format(
        ", ".join(groups) or "none new", ", ".join(tags) or "none new", ", ".join(menus) or "none new"))
