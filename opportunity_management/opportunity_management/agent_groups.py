"""
WhatsApp agent groups — the frappe side (decisions: agent_groups_pure).

    assign_to_group(conv, group, by)   Ring → the chat rings every active member
                                       (assigned_to cleared); Round Robin → the
                                       next member gets it directly. Both keep
                                       `assigned_group` and stamp `group_assigned_at`.
    claim_verdict(conv, user, mgr)     `claim` endpoint: members of the ringing
                                       group (or managers) only
    auto_claim(conv, sender, now)      first agent reply on a ringing chat claims
                                       it for that agent (whatsapp_hooks)
    inbound_recipients(conv)           who an inbound on a ringing chat pushes
    notify_overdue()                   */5 cron: email `notify_user` once when a
                                       ringing chat waited past the timeout
                                       (business minutes); never reassigns

Everything degrades to "no groups" until the migrate has created the doctype
and the conversation columns (`ready()`), like whatsapp_chat_state.
"""

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, now_datetime

from opportunity_management.opportunity_management import agent_groups_pure as P
from opportunity_management.opportunity_management.whatsapp_utils import (
    _to_seconds,
    business_window_unset,
    get_inbox_settings,
    is_business_hours,
)
from opportunity_management.opportunity_management import whatsapp_short_day as SD

GROUP = "WhatsApp Agent Group"
MEMBER = "WhatsApp Agent Group Member"
CONV = "WhatsApp Conversation"
# Where the overdue email's "Open chat" button points (the /inbox web app).
INBOX_SITE = "https://bms.alkhora.com"
SWEEP_LIMIT = 200


def ready() -> bool:
    """True once the migrate created the group tables and conversation columns."""
    try:
        return bool(
            frappe.db.table_exists(GROUP)
            and frappe.db.table_exists(MEMBER)
            and frappe.db.has_column(CONV, "assigned_group")
        )
    except Exception:
        return False


# ── reads ────────────────────────────────────────────────────────────────────

def active_members(group) -> list:
    """Enabled users on the group's active member rows, in table order. []
    for an unknown / inactive group or before the migrate."""
    if not group or not ready():
        return []
    rows = frappe.db.sql(
        """SELECT m.user
           FROM `tabWhatsApp Agent Group Member` m
           JOIN `tabWhatsApp Agent Group` g ON g.name = m.parent
           JOIN `tabUser` u ON u.name = m.user
           WHERE m.parent = %(group)s AND m.parenttype = 'WhatsApp Agent Group'
             AND m.parentfield = 'members' AND COALESCE(m.is_active, 0) = 1
             AND COALESCE(g.is_active, 0) = 1 AND u.enabled = 1
           ORDER BY m.idx ASC""",
        {"group": group},
    )
    return P.members_to_alert([r[0] for r in rows])


def groups_of(user) -> list:
    """Active groups where `user` is an active member."""
    if not user or not ready():
        return []
    rows = frappe.db.sql(
        """SELECT DISTINCT g.name
           FROM `tabWhatsApp Agent Group` g
           JOIN `tabWhatsApp Agent Group Member` m
             ON m.parent = g.name AND m.parenttype = 'WhatsApp Agent Group' AND m.parentfield = 'members'
           WHERE COALESCE(g.is_active, 0) = 1 AND COALESCE(m.is_active, 0) = 1 AND m.user = %(user)s
           ORDER BY g.name ASC""",
        {"user": user},
    )
    return [r[0] for r in rows]


def _muted(conv_name) -> set:
    from opportunity_management.opportunity_management.whatsapp_chat_state import muted_users

    return set(muted_users(conv_name))


def _full_name(user):
    return frappe.db.get_value("User", user, "full_name") or user


def _who(conv):
    from opportunity_management.opportunity_management.notification_templates import _wa_who

    return _wa_who(conv)


def _push_data(conv, kind="whatsapp_group"):
    from opportunity_management.opportunity_management.whatsapp_message_extras import add_wa_sound

    return add_wa_sound({
        "type": kind,
        "screen": "whatsapp",
        "doctype": CONV,
        "name": conv.get("name"),
        "kind": "whatsapp",
    })


def _push(users, title, body, data, seen):
    from opportunity_management.opportunity_management.business_hooks import _send_to_users

    _send_to_users(users, title, body, data, dedupe_seen=seen)


# ── assignment ───────────────────────────────────────────────────────────────

def assign_to_group(conv, group, by):
    """Hand `conv` (a locked WhatsApp Conversation doc) to `group`. The caller
    checked permission. Returns the verdict: P.RING or P.ROUND_ROBIN."""
    from opportunity_management.opportunity_management.whatsapp_api_common import _note
    from opportunity_management.opportunity_management import whatsapp_hooks

    if not ready():
        frappe.throw(_("Agent groups are not set up yet"))
    info = frappe.db.get_value(
        GROUP, group, ["name", "is_active", "strategy", "out_of_hours", "round_robin_pointer"], as_dict=True, for_update=True
    ) if group else None
    if not info or not cint(info.is_active):
        frappe.throw(_("{0} is not an active agent group").format(group or ""))
    members = active_members(info.name)
    if not members:
        frappe.throw(_("{0} has no active members").format(info.name))

    now = now_datetime()
    strategy = info.strategy or P.RING
    if P.hold_out_of_hours(strategy, info.out_of_hours, is_business_hours(now)):
        strategy = P.RING
    pick = None
    if strategy == P.ROUND_ROBIN:
        pick, pointer = P.pick_round_robin(members, cint(info.round_robin_pointer))  # `away`: no presence data yet
        if pick:
            frappe.db.set_value(GROUP, info.name, "round_robin_pointer", pointer, update_modified=False)
        else:
            strategy = P.RING

    values = {
        "assigned_group": info.name,
        "group_assigned_at": now,
        "group_notified_at": None,
        "assigned_to": pick,
        "assigned_at": now if pick else None,
        "assigned_by": by if pick else None,
    }
    for field, value in values.items():
        conv.set(field, value)
    frappe.db.set_value(CONV, conv.name, values, update_modified=False)

    if pick:
        _note(conv.name, _("Assigned to {0} via group {1} by {2}").format(
            _full_name(pick), info.name, _full_name(by)))
    else:
        _note(conv.name, _("Assigned to group {0} by {1}").format(info.name, _full_name(by)))

    try:
        _alert_assignment(conv, info.name, members, pick, by)
    except Exception:
        frappe.log_error(title="WhatsApp agent groups: assignment push failed", message=frappe.get_traceback())
    whatsapp_hooks.publish_inbox_event("conversation", conv)
    return strategy


def _alert_assignment(conv, group, members, pick, by):
    seen = _muted(conv.name)
    seen.add(by)  # the person who just did it needs no push
    if pick:
        from opportunity_management.opportunity_management import notification_templates as T

        title, body, data = T.whatsapp_assigned(conv, by)
        _push([pick], title, body, data, seen)
        return
    title = _("New chat for {0}: {1}").format(group, _who(conv))
    body = (conv.get("last_message_preview") or "").strip()
    _push(P.members_to_alert(members, seen), title, body, _push_data(conv), seen)


def claim_verdict(conv, user, is_manager):
    """`(allowed, reason)` for the `claim` endpoint (whatsapp_assign_rules)."""
    from opportunity_management.opportunity_management import whatsapp_assign_rules as AR

    group = conv.get("assigned_group") if ready() else None
    return AR.may_claim(is_manager, user, conv.get("assigned_to"), group, active_members(group) if group else None)


def auto_claim(conv, sender, now):
    """Values to merge into the conversation update when `sender` (an agent)
    replies to a ringing chat they are a member of; {} otherwise. Writes the
    "Claimed by" note."""
    group = conv.get("assigned_group")
    if not group or conv.get("assigned_to") or not sender or not ready():
        return {}
    try:  # runs inside the message hook: never break the counter update
        if sender not in active_members(group):
            return {}
        from opportunity_management.opportunity_management.whatsapp_api_common import _note

        _note(conv.name, _("Claimed by {0} (first reply)").format(_full_name(sender)), author=sender)
    except Exception:
        frappe.log_error(title="WhatsApp agent groups: auto-claim failed", message=frappe.get_traceback())
        return {}
    return {"assigned_to": sender, "assigned_at": now, "assigned_by": sender}


def inbound_recipients(conv) -> list:
    """Active members of the group a still-unclaimed chat rings; [] when the
    chat is not ringing (the caller then falls back to the whole team)."""
    group = conv.get("assigned_group")
    if not group or conv.get("assigned_to"):
        return []
    return active_members(group)


# ── overdue sweep ────────────────────────────────────────────────────────────

def _schedule(settings):
    """The inbox business schedule as the plain values agent_groups_pure takes."""
    days = {d.strip().lower()[:3] for d in str(settings.get("business_days") or "").split(",") if d.strip()}
    start, end = settings.get("business_hours_start"), settings.get("business_hours_end")
    window = None if business_window_unset(start, end) else (_to_seconds(start), _to_seconds(end))
    short = SD.short_day_window(settings)
    short_day = (short[0], _to_seconds(short[1]), _to_seconds(short[2])) if short else None
    return {"business_days": days, "window": window, "short_day": short_day}


def business_minutes_since(now, settings=None):
    """`fn(start) -> business minutes from start to now`, for P.is_overdue."""
    schedule = _schedule(settings if settings is not None else get_inbox_settings())
    return lambda start: P.business_minutes_between(get_datetime(start), now, **schedule)


def notify_overdue():
    """*/5 cron. Ringing chats (group set, nobody assigned, no agent reply
    since the group got them, not yet notified) past the group's timeout:
    email the group's `notify_user`, push the members once more, stamp
    `group_notified_at`. Never reassigns."""
    if not ready():
        return
    rows = frappe.db.sql(
        """SELECT c.name, c.display_name, c.phone, c.wa_username, c.assigned_group,
                  c.group_assigned_at, c.last_message_preview,
                  g.first_response_timeout_minutes AS timeout, g.notify_user,
                  (SELECT MIN(m.creation) FROM `tabWhatsApp Message` m
                    WHERE m.custom_conversation = c.name AND m.type = 'Outgoing'
                      AND COALESCE(m.custom_sent_by, '') != '' AND COALESCE(m.custom_is_auto, 0) = 0
                      AND m.creation >= c.group_assigned_at) AS first_response_at
           FROM `tabWhatsApp Conversation` c
           JOIN `tabWhatsApp Agent Group` g ON g.name = c.assigned_group
           WHERE COALESCE(c.assigned_to, '') = '' AND c.status != 'Resolved'
             AND c.group_assigned_at IS NOT NULL AND c.group_notified_at IS NULL
             AND COALESCE(g.is_active, 0) = 1 AND COALESCE(g.first_response_timeout_minutes, 0) > 0
           ORDER BY c.group_assigned_at ASC
           LIMIT %(limit)s""",
        {"limit": SWEEP_LIMIT},
        as_dict=True,
    )
    if not rows:
        return
    now = now_datetime()
    minutes_since = business_minutes_since(now)
    for row in rows:
        try:
            if not P.is_overdue(row.group_assigned_at, row.first_response_at, row.timeout, minutes_since):
                continue
            _notify_one(row, minutes_since(row.group_assigned_at), now)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            frappe.log_error(
                title="WhatsApp agent groups: overdue notify failed",
                message="{0}\n{1}".format(row.name, frappe.get_traceback()),
            )


def _notify_one(row, waited, now):
    # Stamp first: a failing mail server must not turn into a push every 5 minutes.
    frappe.db.set_value(CONV, row.name, "group_notified_at", now, update_modified=False)
    who = _who(row)
    if row.notify_user:
        try:
            _send_overdue_email(row, who, waited)
        except Exception:
            frappe.log_error(
                title="WhatsApp agent groups: overdue email failed",
                message="{0}\n{1}".format(row.name, frappe.get_traceback()),
            )
    seen = _muted(row.name)
    title = _("Chat waiting {0} min — {1}").format(waited, row.assigned_group)
    body = who + ("\n" + row.last_message_preview if row.last_message_preview else "")
    _push(P.members_to_alert(active_members(row.assigned_group), seen), title, body,
          _push_data(row, "whatsapp_group_overdue"), seen)


def _send_overdue_email(row, who, waited):
    from opportunity_management.opportunity_management import email_design as E
    from opportunity_management.opportunity_management.fcm_webpush import inbox_link

    url = inbox_link({"screen": "whatsapp", "doctype": CONV, "name": row.name}, INBOX_SITE)
    message = E.envelope(
        accent=E.URGENT,
        eyebrow=_("WhatsApp · no reply yet"),
        headline=who,
        subline=_("Waiting {0} business minutes for a first reply").format(waited),
        rows=[
            E.row(E.label("Group", "المجموعة"), E.name_cell(row.assigned_group)),
            E.row(E.label("Waiting", "الانتظار"), E.esc(_("{0} min").format(waited))),
            E.row(E.label("Conversation", "المحادثة"), E.name_cell(row.name, mono=True)),
        ],
        actions=[E.button(_("Open chat"), url, accent=E.URGENT, ar="فتح المحادثة")],
    )
    frappe.sendmail(
        recipients=[row.notify_user],
        subject=_("WhatsApp chat pending: {0} — {1}").format(who, row.assigned_group),
        message=message,
        reference_doctype=CONV,
        reference_name=row.name,
    )
