"""
Multi-device push registration (`ESS Push Device`) — today the web Team Inbox;
the phone keeps using `api.register_fcm_token` (Employee.custom_fcm_token).

    register_push_device(token, platform, label=None)  POST → {"name"}
    unregister_push_device(token)                      POST → {"disabled": n}
    list_push_devices()                                     → [rows]

All three act on the session user's own rows only and write with
ignore_permissions (the doctype grants nothing beyond System Manager).
Register/unregister are POST-only: a GET would let a cross-site link bind an
attacker's browser token to the victim's account.
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

DT = "ESS Push Device"
PLATFORMS = ("web", "ios", "android")
MAX_TOKEN = 512
MAX_LABEL = 140


def normalize_platform(platform):
    """`web` / `ios` / `android` (case-insensitive), else None."""
    value = str(platform or "").strip().lower()
    return value if value in PLATFORMS else None


def clean_token(token):
    """Stripped token, or None when empty / too long / contains whitespace."""
    value = str(token or "").strip()
    if not value or len(value) > MAX_TOKEN or any(c.isspace() for c in value):
        return None
    return value


def clean_label(label):
    value = " ".join(str(label or "").split())
    return value[:MAX_LABEL] or None


def _session_user():
    user = frappe.session.user
    if not user or user == "Guest":
        frappe.throw(_("Please log in first."), frappe.PermissionError)
    return user


def _upsert(user, token, platform, label):
    employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
    values = {
        "user": user,
        "employee": employee,
        "platform": platform,
        "enabled": 1,
        "last_seen": now_datetime(),
        "last_error": None,
    }
    if label:
        values["label"] = label
    name = frappe.db.get_value(DT, {"token": token}, "name")
    if name:
        # Same browser, possibly a different user now (shared machine): the
        # token follows whoever registered it last.
        doc = frappe.get_doc(DT, name)
        doc.update(values)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({"doctype": DT, "token": token, **values})
        doc.insert(ignore_permissions=True)
    return doc.name


@frappe.whitelist(methods=["POST"])
def register_push_device(token, platform, label=None):
    """Upsert the caller's push token (enabled, last_seen = now)."""
    user = _session_user()
    token = clean_token(token)
    if not token:
        frappe.throw(_("Invalid push token."))
    platform = normalize_platform(platform)
    if not platform:
        frappe.throw(_("Platform must be one of: {0}").format(", ".join(PLATFORMS)))
    label = clean_label(label)
    try:
        name = _upsert(user, token, platform, label)
    except frappe.DuplicateEntryError:
        # Two tabs registering the same token at once: the other insert won.
        frappe.db.rollback()
        name = _upsert(user, token, platform, label)
    return {"name": name}


@frappe.whitelist(methods=["POST"])
def unregister_push_device(token):
    """Disable the caller's row for `token` (sign-out / "remove")."""
    user = _session_user()
    token = clean_token(token)
    if not token:
        return {"disabled": 0}
    names = frappe.get_all(DT, filters={"token": token, "user": user, "enabled": 1}, pluck="name")
    for name in names:
        frappe.db.set_value(DT, name, "enabled", 0)
    return {"disabled": len(names)}


@frappe.whitelist()
def list_push_devices():
    """The caller's devices, newest activity first. `token` is included so
    the UI can mark "this browser" and pass it to `unregister_push_device`."""
    user = _session_user()
    return frappe.get_all(
        DT,
        filters={"user": user},
        fields=["name", "token", "platform", "label", "enabled", "last_seen", "last_error", "creation"],
        order_by="last_seen desc, creation desc",
    )
