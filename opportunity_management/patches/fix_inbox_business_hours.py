"""
Move the WhatsApp inbox to the real business week: Saturday–Thursday,
9:00 AM – 4:00 PM (Baghdad), with the schedule rendered into the
out-of-hours reply from the settings instead of hardcoded into it.

What the live site had:

  * business_hours_start / end = the `nowtime()` artefact Frappe stamps into
    every Time field of a fresh Single (e.g. 17:26:35 → 17:26:35), which
    `is_business_hours()` reads as "no window" — so the out-of-hours reply
    only ever fired on non-business days, never on weekday evenings;
  * business_days = the old seed "Sun,Mon,Tue,Wed,Thu" (Saturday missing);
  * out-of-hours texts = the old seeded strings hardcoding "Sun-Thu,
    9:00-17:00" — wrong days, wrong end hour, 24-hour clock.

Every change is conditional on the value still being the artefact or the
exact old seed, so a manager's own window, days or wording is never
stomped. Idempotent: a second run finds nothing to change.
"""

import frappe

from opportunity_management.opportunity_management.whatsapp_setup import (
    DEFAULT_BUSINESS_DAYS,
    DEFAULT_HOURS_END,
    DEFAULT_HOURS_START,
    OUT_OF_HOURS_TEXT_AR,
    OUT_OF_HOURS_TEXT_EN,
)
from opportunity_management.opportunity_management.whatsapp_utils import (
    business_window_unset,
    clear_settings_cache,
)

DOCTYPE = "WhatsApp Inbox Settings"

OLD_BUSINESS_DAYS = "Sun,Mon,Tue,Wed,Thu"
OLD_OUT_OF_HOURS_TEXT_EN = (
    "Thanks for your message. Our office is closed right now — we will reply "
    "during business hours (Sun-Thu, 9:00-17:00)."
)
OLD_OUT_OF_HOURS_TEXT_AR = (
    "شكراً لرسالتك. مكتبنا مغلق حالياً — "
    "سنرد عليك خلال ساعات العمل (الأحد-الخميس، 9:00-17:00)."
)

# The seeded "/hours" quick reply carried the same stale schedule.
QUICK_REPLY_SHORTCUT = "/hours"
OLD_QUICK_REPLY = {
    "text_en": "Hello {{customer}}, our team is available Sunday to Thursday, 9:00 to 17:00 Baghdad time.",
    "text_ar": "مرحباً {{customer}}، فريقنا متاح من الأحد إلى الخميس، من 9:00 إلى 17:00 بتوقيت بغداد.",
}
NEW_QUICK_REPLY = {
    "text_en": "Hello {{customer}}, our team is available Saturday to Thursday, 9:00 AM to 4:00 PM Baghdad time.",
    "text_ar": "مرحباً {{customer}}، فريقنا متاح من السبت إلى الخميس، من 9:00 ص إلى 4:00 م بتوقيت بغداد.",
}


def _same(current, old) -> bool:
    return (current or "").strip() == old.strip()


def execute():
    if not frappe.db.exists("DocType", DOCTYPE):
        return

    get = lambda field: frappe.db.get_single_value(DOCTYPE, field)  # noqa: E731
    updates = {}

    start, end = get("business_hours_start"), get("business_hours_end")
    if business_window_unset(start, end):
        updates["business_hours_start"] = DEFAULT_HOURS_START
        updates["business_hours_end"] = DEFAULT_HOURS_END
        print(
            f"WhatsApp inbox: business hours {start!s} → {end!s} reset to "
            f"{DEFAULT_HOURS_START} → {DEFAULT_HOURS_END}"
        )

    days = get("business_days")
    if _same(days, OLD_BUSINESS_DAYS):
        updates["business_days"] = DEFAULT_BUSINESS_DAYS
        print(f"WhatsApp inbox: business days {days} → {DEFAULT_BUSINESS_DAYS}")

    for field, old, new in (
        ("out_of_hours_text_en", OLD_OUT_OF_HOURS_TEXT_EN, OUT_OF_HOURS_TEXT_EN),
        ("out_of_hours_text_ar", OLD_OUT_OF_HOURS_TEXT_AR, OUT_OF_HOURS_TEXT_AR),
    ):
        if _same(get(field), old):
            updates[field] = new
            print(f"WhatsApp inbox: {field} now uses {{{{business_hours}}}}")

    if updates:
        frappe.db.set_single_value(DOCTYPE, updates)
        frappe.clear_document_cache(DOCTYPE, DOCTYPE)
        clear_settings_cache()

    _fix_hours_quick_reply()
    frappe.db.commit()


def _fix_hours_quick_reply():
    if not frappe.db.exists("DocType", "WhatsApp Quick Reply"):
        return
    name = frappe.db.get_value("WhatsApp Quick Reply", {"shortcut": QUICK_REPLY_SHORTCUT}, "name")
    if not name:
        return
    current = frappe.db.get_value(
        "WhatsApp Quick Reply", name, list(OLD_QUICK_REPLY), as_dict=True
    ) or {}
    for field, old in OLD_QUICK_REPLY.items():
        if _same(current.get(field), old):
            frappe.db.set_value(
                "WhatsApp Quick Reply", name, field, NEW_QUICK_REPLY[field], update_modified=False
            )
            print(f"WhatsApp inbox: quick reply {QUICK_REPLY_SHORTCUT} {field} → Sat–Thu, 9:00 AM – 4:00 PM")
