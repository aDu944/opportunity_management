"""
Channels of the team inbox (WhatsApp, Messenger): who may use which, what a
conversation of each channel can do (`caps`), and when it may be written to
(the window rule).

A Messenger chat is a `WhatsApp Conversation` with `channel = "Messenger"`
and its messages are `WhatsApp Message` rows with `custom_channel =
"Messenger"` (messenger_contract.md). Everything that lists, counts, pushes
or opens a conversation asks this module which channels the caller has.

Access:
    WhatsApp   ⇐ any role in Inbox Settings `agent_roles` (`inbox_roles()`)
    Messenger  ⇐ Messenger Agent / Messenger Manager
    System Manager ⇐ every channel — Messenger only once Messenger Settings
                     is enabled, so a System Manager's inbox is exactly the
                     WhatsApp one until the owner switches Messenger on
Manager-ness is per channel: WhatsApp Manager → WhatsApp, Messenger Manager →
Messenger, System Manager → all (same Messenger rule).

The top half is pure (no `frappe` import at module scope) so
`tests/test_inbox_channels_pure.py` loads it bench-free; the frappe-backed
helpers below import lazily. A row whose `channel` is empty (written before
the field existed) is WhatsApp.
"""

WHATSAPP = "WhatsApp"
MESSENGER = "Messenger"
CHANNELS = (WHATSAPP, MESSENGER)

MESSENGER_AGENT = "Messenger Agent"
MESSENGER_MANAGER = "Messenger Manager"
MESSENGER_ROLES = (MESSENGER_AGENT, MESSENGER_MANAGER)
SYSTEM_MANAGER = "System Manager"
MANAGER_ROLES = {WHATSAPP: "WhatsApp Manager", MESSENGER: MESSENGER_MANAGER}

# The window rule. Messenger's Human Agent tag allows a person (not a bot) to
# answer for 7 days after the customer's last message.
STANDARD_SECONDS = 24 * 60 * 60
HUMAN_AGENT_SECONDS = 7 * 24 * 60 * 60
STANDARD = "standard"
HUMAN_AGENT = "human_agent"
CLOSED = "closed"

CAP_KEYS = (
    "templates", "reactions", "voice", "video", "documents", "location",
    "contact", "options", "block", "typing", "forward",
)
# What Messenger cannot do. Reactions CAN be sent: the Send API has
# `sender_action: "react" | "unreact"` (verified 2026-10-05, see messenger_api).
_MESSENGER_OFF = ("templates", "location", "contact", "block")


# ── pure ─────────────────────────────────────────────────────────────────────

def channel_of(value) -> str:
    """Normalise a stored / requested channel; empty and unknown → WhatsApp."""
    text = str(value or "").strip()
    return text if text in CHANNELS else WHATSAPP


def conv_channel(conv) -> str:
    """The channel of a conversation (Document, dict or row)."""
    if conv is None:
        return WHATSAPP
    getter = getattr(conv, "get", None)
    value = getter("channel") if callable(getter) else getattr(conv, "channel", None)
    return channel_of(value)


def channels_for_roles(roles, whatsapp_roles, messenger_enabled=True) -> list:
    """Channels a set of roles may use, in CHANNELS order. A System Manager
    gets Messenger only when it is enabled; an explicit Messenger role
    always does (someone granted it on purpose)."""
    roles = set(roles or ())
    system = SYSTEM_MANAGER in roles
    out = []
    if system or roles & set(whatsapp_roles or ()):
        out.append(WHATSAPP)
    if roles & set(MESSENGER_ROLES) or (system and messenger_enabled):
        out.append(MESSENGER)
    return out


def manager_channels_for_roles(roles, messenger_enabled=True) -> list:
    roles = set(roles or ())
    system = SYSTEM_MANAGER in roles
    out = [WHATSAPP] if system or MANAGER_ROLES[WHATSAPP] in roles else []
    if MANAGER_ROLES[MESSENGER] in roles or (system and messenger_enabled):
        out.append(MESSENGER)
    return out


def caps_for(channel) -> dict:
    """What the composer / menus may offer for a conversation of `channel`."""
    caps = {key: True for key in CAP_KEYS}
    if channel_of(channel) == MESSENGER:
        for key in _MESSENGER_OFF:
            caps[key] = False
    return caps


def window_state(channel, last_inbound_at, now, human_agent=False):
    """`(window_mode, seconds_remaining)`.

    WhatsApp: exactly the old rule (`int(24h - elapsed)` while > 0, else
    closed) so `window_open` never moves for a WhatsApp thread. Messenger:
    the same 24 h `standard` window, then — only when the Human Agent
    permission is enabled — `human_agent` until 7 days, else closed.
    `last_inbound_at` / `now` are datetimes (the caller parses).
    """
    if not last_inbound_at or now is None:
        return CLOSED, 0
    elapsed = (now - last_inbound_at).total_seconds()
    remaining = STANDARD_SECONDS - elapsed
    if remaining > 0 and int(remaining) > 0:
        return STANDARD, int(remaining)
    if channel_of(channel) == MESSENGER and human_agent:
        remaining = HUMAN_AGENT_SECONDS - elapsed
        if remaining > 0 and int(remaining) > 0:
            return HUMAN_AGENT, int(remaining)
    return CLOSED, 0


def channel_sql(column, channels):
    """A WHERE fragment limiting `column` to `channels`, or "" when they are
    every channel (no filter — the query stays exactly what it was). Values
    are only ever CHANNELS constants, so inlining them is safe."""
    wanted = [ch for ch in CHANNELS if ch in (channels or ())]
    if len(wanted) == len(CHANNELS):
        return ""
    if not wanted:
        return "1 = 0"
    quoted = ", ".join("'{0}'".format(ch) for ch in wanted)
    return "COALESCE(NULLIF({0}, ''), '{1}') IN ({2})".format(column, WHATSAPP, quoted)


def agents_with_channels(users_by_channel, channels) -> list:
    """`[(user, [channels])]` for the roster of `channels` (CHANNELS order),
    first-seen user order kept."""
    order, seen = [], {}
    for ch in CHANNELS:
        if ch not in (channels or ()):
            continue
        for user in users_by_channel.get(ch) or ():
            if user not in seen:
                seen[user] = []
                order.append(user)
            seen[user].append(ch)
    return [(user, seen[user]) for user in order]


# ── frappe-backed ────────────────────────────────────────────────────────────

def _roles(user=None):
    import frappe

    return set(frappe.get_roles(user or frappe.session.user))


def user_channels(user=None) -> list:
    from opportunity_management.opportunity_management.whatsapp_utils import inbox_roles

    return channels_for_roles(_roles(user), inbox_roles(), messenger_enabled())


def manager_channels(user=None) -> list:
    return manager_channels_for_roles(_roles(user), messenger_enabled())


def messenger_enabled() -> bool:
    try:
        return bool(int(messenger_settings().get("enabled") or 0))
    except (TypeError, ValueError):
        return False


def has_channel_column() -> bool:
    """False until the migrate adds `channel` — the queries then skip it."""
    import frappe

    try:
        return bool(frappe.db.has_column("WhatsApp Conversation", "channel"))
    except Exception:
        return False


def list_channel_sql(alias, channels) -> str:
    """`channel_sql` for `alias.channel`, "" before the migrate."""
    if not has_channel_column():
        return ""
    return channel_sql("{0}.channel".format(alias) if alias else "channel", channels)


def list_select(alias) -> str:
    """`channel` / `avatar_url` columns for the list query (constants before
    the migrate), with the trailing comma."""
    if not has_channel_column():
        return "'{0}' AS channel, NULL AS avatar_url, ".format(WHATSAPP)
    return "{0}.channel, {0}.avatar_url, ".format(alias)


def expired_sql(alias, channels, params) -> str:
    """The `expired` scope: the window has closed. `params["window_cutoff"]`
    is now − 24 h; with Messenger + Human Agent its rows use now − 7 days."""
    base = "({0}.last_inbound_at IS NULL OR {0}.last_inbound_at <= %(window_cutoff)s)".format(alias)
    if MESSENGER not in (channels or ()) or not human_agent_enabled() or not has_channel_column():
        return base
    from frappe.utils import add_to_date, now_datetime

    params["ha_cutoff"] = add_to_date(now_datetime(), seconds=-HUMAN_AGENT_SECONDS)
    return (
        "(CASE WHEN {0}.channel = '{1}' THEN ({0}.last_inbound_at IS NULL"
        " OR {0}.last_inbound_at <= %(ha_cutoff)s) ELSE {2} END)".format(alias, MESSENGER, base)
    )


def mark_seen(conv):
    from opportunity_management.opportunity_management.messenger_send import sender_action

    return sender_action(conv, "mark_seen")


def messenger_settings():
    """The `Messenger Settings` single, cached for this request ({} when the
    doctype is not installed yet)."""
    import frappe

    cached = getattr(frappe.local, "_messenger_settings", None)
    if cached is not None:
        return cached
    try:
        settings = frappe.get_cached_doc("Messenger Settings")
    except Exception:
        settings = frappe._dict({})
    try:
        frappe.local._messenger_settings = settings
    except Exception:
        pass
    return settings


def human_agent_enabled() -> bool:
    try:
        return bool(int(messenger_settings().get("human_agent_enabled") or 0))
    except (TypeError, ValueError):
        return False


def conv_window(conv, now=None):
    """`window_state` for a conversation, with the live Human Agent setting."""
    from frappe.utils import get_datetime, now_datetime

    last = conv.get("last_inbound_at") if hasattr(conv, "get") else None
    try:
        last = get_datetime(last) if last else None
    except Exception:
        last = None
    current = get_datetime(now) if now else now_datetime()
    channel = conv_channel(conv)
    return window_state(channel, last, current, channel == MESSENGER and human_agent_enabled())


def channel_users(channel) -> list:
    """Enabled users who work `channel` — push and realtime recipients and
    the assignment roster. WhatsApp is `inbox_users()` unchanged; Messenger
    mirrors it with the Messenger roles (System Managers only while nobody
    holds one)."""
    from opportunity_management.opportunity_management.whatsapp_utils import inbox_users

    if channel_of(channel) == WHATSAPP:
        return inbox_users()
    from opportunity_management.opportunity_management.business_hooks import _users_with_role

    users, seen = [], {"Administrator", "Guest"}
    for roles in (MESSENGER_ROLES, (SYSTEM_MANAGER,)):
        for role in roles:
            for email in _users_with_role(role):
                if email and email not in seen:
                    seen.add(email)
                    users.append(email)
        if users:
            break
    return users


def roster(channels) -> list:
    """`[(user, [channels])]` over `channels`."""
    return agents_with_channels({ch: channel_users(ch) for ch in channels}, channels)
