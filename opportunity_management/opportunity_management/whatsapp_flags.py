"""
The shared, team-wide flag on a WhatsApp Conversation (`is_flagged`,
`flagged_by`, `flagged_at`, `flag_note`).

Unlike pin / mute (whatsapp_chat_state, per user) a flag is one column set on
the conversation itself: everyone on the channel sees the same flag, the
`flagged` list scope (whatsapp_chat_state.FLAGGED_CLAUSES) is a team queue,
and resolving the thread clears it (`CLEARED`).

Pure helpers only — the endpoint is `whatsapp_api_flags.set_flag`. Bench-free
tests load this file off disk with a stub `frappe`.
"""

import frappe
from frappe.utils import cint

CONV = "WhatsApp Conversation"
NOTE_MAX = 140
FIELDS = ("is_flagged", "flagged_by", "flagged_at", "flag_note")
# Written by set_flag(flagged=False) and by every Resolve.
CLEARED = {"is_flagged": 0, "flagged_by": None, "flagged_at": None, "flag_note": None}
UNFLAGGED_ROW = {
    "is_flagged": False,
    "flagged_by": None,
    "flagged_by_name": "",
    "flagged_at": None,
    "flag_note": None,
}


def _get(obj, key):
    if isinstance(obj, dict) or hasattr(obj, "get"):
        return obj.get(key)
    return getattr(obj, key, None)


def has_columns() -> bool:
    """False until the migrate adds the fields — callers fall back."""
    try:
        return bool(frappe.db.has_column(CONV, "is_flagged"))
    except Exception:
        return False


def list_select(alias) -> str:
    """The flag columns for the list query, with the trailing comma
    (constants before the migrate). No literal % anywhere."""
    if not has_columns():
        return "0 AS is_flagged, NULL AS flagged_by, NULL AS flagged_at, NULL AS flag_note, "
    return "{0}.is_flagged, {0}.flagged_by, {0}.flagged_at, {0}.flag_note, ".format(alias)


def count_select() -> str:
    """`flagged_open` for get_unread_count's SUM row (its WHERE already
    drops Resolved threads)."""
    if not has_columns():
        return "0 AS flagged_open"
    return "SUM(CASE WHEN COALESCE(is_flagged, 0) = 1 THEN 1 ELSE 0 END) AS flagged_open"


def parse_flag(value) -> bool:
    """`flagged` as sent by Desk (1/0), mobile (true/false) or the console."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(cint(value)) if value is not None else False


def clean_note(note):
    """Trimmed, single-spaced, at most NOTE_MAX characters; None when empty."""
    text = " ".join(str(note or "").split())
    return text[:NOTE_MAX] or None


def note_text(flagged, who, note=None, translate=None):
    """The System internal note set_flag writes."""
    t = translate or (lambda s: s)
    if not flagged:
        return t("Flag removed by {0}").format(who)
    if note:
        return t("Flagged by {0}: {1}").format(who, note)
    return t("Flagged by {0}").format(who)


def flag_values(current, me, note, now):
    """Columns to write when `me` flags a thread. Re-flagging an already
    flagged thread keeps its `flagged_at`, so the queue position holds."""
    keep = cint(_get(current, "is_flagged")) and _get(current, "flagged_at")
    return {"is_flagged": 1, "flagged_by": me, "flagged_at": keep or now, "flag_note": note}


def flag_fields(conv, flagger_name=None, iso=None):
    """The ConvRow flag keys. `flagger_name` comes batched from conv_rows;
    None looks the user up once."""
    if not cint(_get(conv, "is_flagged")):
        return dict(UNFLAGGED_ROW)
    by = _get(conv, "flagged_by") or None
    if flagger_name is None and by:
        try:
            flagger_name = frappe.db.get_value("User", by, "full_name")
        except Exception:
            flagger_name = None
    at = _get(conv, "flagged_at")
    return {
        "is_flagged": True,
        "flagged_by": by,
        "flagged_by_name": flagger_name or by or "",
        "flagged_at": (iso(at) if iso else (str(at) if at else None)),
        "flag_note": _get(conv, "flag_note") or None,
    }
