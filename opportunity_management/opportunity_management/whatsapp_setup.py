"""
One-time / idempotent schema bootstrap for the WhatsApp team inbox.

Split out of `whatsapp_utils` so that module stays small and importable with
a stubbed `frappe` (its pure helpers are unit-tested without a bench); this
one is all writes and only ever runs from two callers:

    setup/install.py::setup_whatsapp_inbox          (fresh install)
    patches/backfill_whatsapp_conversations.py      (migrate)

Both call the same four functions in the same order, so the install and
migrate paths can never drift. Everything here is safe to re-run.
"""

import frappe

from opportunity_management.opportunity_management.whatsapp_utils import clear_settings_cache


# `custom_` prefix per Frappe convention. `create_custom_fields(update=True)`
# is idempotent, so both the install path and the migrate patch can call this
# on every run. Exported as a fixture filter block in hooks.py as well, but
# the fixture sync happens AFTER post-model-sync patches — hence the inline
# creation here.
WHATSAPP_MESSAGE_CUSTOM_FIELDS = {
    "WhatsApp Message": [
        {
            "fieldname": "custom_conversation",
            "label": "Conversation",
            "fieldtype": "Link",
            "options": "WhatsApp Conversation",
            "insert_after": "whatsapp_account",
            "search_index": 1,
            "read_only": 1,
            "no_copy": 1,
        },
        {
            "fieldname": "custom_read",
            "label": "Read",
            "fieldtype": "Check",
            "insert_after": "custom_conversation",
            "no_copy": 1,
            "description": "0 for unread inbound. Outbound rows are inserted read.",
        },
        {
            "fieldname": "custom_sent_by",
            "label": "Sent By",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "custom_read",
            "read_only": 1,
            "no_copy": 1,
            "description": "The agent who pressed send. Empty for auto-replies and notifications.",
        },
        {
            "fieldname": "custom_is_auto",
            "label": "Is Auto Reply",
            "fieldtype": "Check",
            "insert_after": "custom_sent_by",
            "no_copy": 1,
        },
        {
            "fieldname": "custom_media_private",
            "label": "Media Privatized",
            "fieldtype": "Check",
            "insert_after": "custom_is_auto",
            "no_copy": 1,
        },
        {
            "fieldname": "custom_body_text",
            "label": "Body Text",
            "fieldtype": "Small Text",
            "insert_after": "custom_media_private",
            "read_only": 1,
            "no_copy": 1,
            "description": "Normalized display text computed once at insert (whatsapp_utils.normalize_body).",
        },
    ]
}

# (role, doctype, extra perms) — read everywhere, because Frappe's private
# File access check delegates to the attached document's permissions.
_DOCPERMS = (
    ("WhatsApp Agent", "WhatsApp Message", {"read": 1}),
    ("WhatsApp Manager", "WhatsApp Message", {"read": 1}),
    ("WhatsApp Agent", "WhatsApp Templates", {"read": 1}),
    ("WhatsApp Manager", "WhatsApp Templates", {"read": 1}),
    ("WhatsApp Manager", "WhatsApp Account", {"read": 1}),
)


def create_whatsapp_message_custom_fields():
    """Idempotently add the `custom_*` fields to `WhatsApp Message`."""
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    if not frappe.db.exists("DocType", "WhatsApp Message"):
        return False
    create_custom_fields(WHATSAPP_MESSAGE_CUSTOM_FIELDS, update=True)
    return True


def ensure_message_index():
    """Composite index behind `get_messages` — every thread read is
    `WHERE custom_conversation = … ORDER BY creation`."""
    try:
        frappe.db.add_index("WhatsApp Message", ["custom_conversation", "creation"])
        return True
    except Exception:
        frappe.log_error(
            frappe.get_traceback(), "WhatsApp inbox: could not add message index"
        )
        return False


def ensure_whatsapp_roles_and_perms():
    """Create the `WhatsApp Agent` role and the Custom DocPerms both inbox
    roles need on frappe_whatsapp's doctypes.

    Done in code rather than only as fixtures because fixtures sync *after*
    post-model-sync patches, and the backfill needs the role to exist.
    No create/write grants: every insert goes through whatsapp_api with
    `ignore_permissions=True`.
    """
    if not frappe.db.exists("Role", "WhatsApp Agent"):
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": "WhatsApp Agent",
                "desk_access": 1,
                "search_bar": 1,
                "notifications": 1,
            }
        ).insert(ignore_permissions=True)

    for role, doctype, perms in _DOCPERMS:
        if not frappe.db.exists("DocType", doctype):
            continue
        if not frappe.db.exists("Role", role):
            continue
        if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0}):
            continue
        row = {
            "doctype": "Custom DocPerm",
            "parent": doctype,
            "parenttype": "DocType",
            "parentfield": "permissions",
            "permlevel": 0,
            "role": role,
        }
        row.update(perms)
        frappe.get_doc(row).insert(ignore_permissions=True)


_DEFAULT_TAGS = (
    ("Sales", "#25D366"),
    ("Support", "#1565C0"),
    ("Spam", "#9E9E9E"),
)

_DEFAULT_QUICK_REPLIES = (
    {
        "title": "Business hours",
        "shortcut": "/hours",
        "text_en": "Hello {{customer}}, our team is available Sunday to Thursday, 9:00 to 17:00 Baghdad time.",
        "text_ar": "مرحباً {{customer}}، فريقنا متاح من الأحد إلى الخميس، من 9:00 إلى 17:00 بتوقيت بغداد.",
    },
    {
        "title": "One moment",
        "shortcut": "/wait",
        "text_en": "Thank you {{customer}} — {{agent}} is checking this for you now.",
        "text_ar": "شكراً {{customer}}، يقوم {{agent}} بالتحقق من ذلك الآن.",
    },
)


def seed_inbox_defaults(working_days: str = None):
    """Fill the Inbox Settings singleton and seed starter tags / quick replies.

    Only writes fields that are still empty, so re-running a migrate never
    stomps what the manager configured.
    """
    settings = frappe.get_single("WhatsApp Inbox Settings")
    defaults = {
        "default_country_code": "964",
        "default_language": "en",
        "agent_roles": "WhatsApp Agent,WhatsApp Manager",
        "business_days": working_days or _ess_working_days() or "Sun,Mon,Tue,Wed,Thu",
        "business_hours_start": "09:00:00",
        "business_hours_end": "17:00:00",
        "timezone": "Asia/Baghdad",
        "enable_welcome": 1,
        "welcome_text_en": (
            "Hello! Thanks for messaging AL KHORA. One of our team will reply shortly."
        ),
        "welcome_text_ar": (
            "مرحباً! شكراً لتواصلك مع الخورة. "
            "سيرد عليك أحد أعضاء فريقنا قريباً."
        ),
        "enable_out_of_hours": 1,
        "out_of_hours_text_en": (
            "Thanks for your message. Our office is closed right now — we will reply "
            "during business hours (Sun-Thu, 9:00-17:00)."
        ),
        "out_of_hours_text_ar": (
            "شكراً لرسالتك. مكتبنا مغلق حالياً — "
            "سنرد عليك خلال ساعات العمل (الأحد-الخميس، 9:00-17:00)."
        ),
        "out_of_hours_throttle_hours": 12,
        "notify_team_on_unassigned": 1,
        "team_alert_throttle_minutes": 10,
        "privatize_inbound_media": 1,
        "privatize_outbound_after_sent": 0,
        "auto_resolve_after_days": 0,
        "auto_read_receipt": 0,
    }
    dirty = False
    for field, value in defaults.items():
        if settings.get(field) in (None, ""):
            settings.set(field, value)
            dirty = True
    if dirty:
        settings.flags.ignore_permissions = True
        settings.save(ignore_permissions=True)

    for tag_name, color in _DEFAULT_TAGS:
        if not frappe.db.exists("WhatsApp Tag", tag_name):
            frappe.get_doc(
                {
                    "doctype": "WhatsApp Tag",
                    "tag_name": tag_name,
                    "color": color,
                    "is_active": 1,
                }
            ).insert(ignore_permissions=True)

    for row in _DEFAULT_QUICK_REPLIES:
        if frappe.db.exists("WhatsApp Quick Reply", {"shortcut": row["shortcut"]}):
            continue
        doc = {"doctype": "WhatsApp Quick Reply", "scope": "Team", "is_active": 1}
        doc.update(row)
        frappe.get_doc(doc).insert(ignore_permissions=True)

    clear_settings_cache()


def _ess_working_days() -> str:
    try:
        return frappe.db.get_single_value("ESS Mobile Settings", "working_days") or ""
    except Exception:
        return ""
