"""
Bench-free logic behind the web Team Inbox sidebar, the customer drawer's
Opportunity card and the right-click actions. No `frappe` import, so
`tests/test_inbox_sidebar_pure.py` loads it straight off disk.

    opportunity_clause   list_conversations(opportunity=…) / sidebar counts
    opportunity_fields   the four `opportunity_*` ConvRow keys
    apply_user_state     the caller's pin / mute / marked-unread onto a ConvRow
    day_start, minutes_since   "today" maths of get_sidebar_counts
    stages_from_options, opportunity_card   the drawer's Opportunity card
    quick_reply_fields, clean_tag_name      save_quick_reply / rename_tag

SQL fragments use the list query's aliases: `c` = WhatsApp Conversation,
`o` = Opportunity (LEFT JOINed on `o.name = c.opportunity`). They carry no
literal `%`: values are pymysql placeholders only.
"""

import datetime as _dt
import re

# ── scope fragments (shared by list_conversations and get_sidebar_counts) ────

OPEN_SQL = "c.status != 'Resolved'"
MINE_CLAUSES = ("c.assigned_to = %(me)s", OPEN_SQL)
UNASSIGNED_CLAUSES = ("(c.assigned_to IS NULL OR c.assigned_to = '')", OPEN_SQL)
RESOLVED_CLAUSES = ("c.status = 'Resolved'",)

# ── opportunity filter ───────────────────────────────────────────────────────

OPPORTUNITY_FILTERS = ("any", "none", "Open", "Quotation", "Converted", "Closed")
# The sidebar's "Opportunities" buckets (`none` is counted as no_opportunity).
OPPORTUNITY_BUCKETS = ("any", "Open", "Quotation", "Converted", "Closed")
# "Closed" in the sidebar is ERPNext's Closed and Lost together.
STATUS_GROUPS = {
    "Open": ("Open",),
    "Quotation": ("Quotation",),
    "Converted": ("Converted",),
    "Closed": ("Closed", "Lost"),
}
OPPORTUNITY_LIST_JOIN = "LEFT JOIN `tabOpportunity` o ON o.name = c.opportunity"


def normalize_opportunity_filter(value):
    """"" / None → None; a known filter (any case) → its canonical
    spelling; anything else → ValueError."""
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    for known in OPPORTUNITY_FILTERS:
        if text.lower() == known.lower():
            return known
    raise ValueError(text)


def opportunity_clause(value, key="opp"):
    """(sql, params) for one opportunity filter; ("", {}) for no filter.

    any        a linked Opportunity that exists
    none       no (existing) Opportunity, and not Resolved
    Open | Quotation | Converted   linked Opportunity with that status
    Closed     linked Opportunity that is Closed or Lost

    `key` prefixes the parameter names, so several clauses can share one
    query (get_sidebar_counts). Raises ValueError for an unknown value.
    """
    wanted = normalize_opportunity_filter(value)
    if wanted is None:
        return "", {}
    if wanted == "any":
        return "(COALESCE(c.opportunity, '') != '' AND o.name IS NOT NULL)", {}
    if wanted == "none":
        # A dangling link (Opportunity deleted) counts as "no opportunity".
        return "(o.name IS NULL AND {0})".format(OPEN_SQL), {}
    params = {}
    names = []
    for i, status in enumerate(STATUS_GROUPS[wanted]):
        name = "{0}_{1}".format(key, i)
        params[name] = status
        names.append("%({0})s".format(name))
    return "o.status IN ({0})".format(", ".join(names)), params


def opportunity_select(has_stage=True, has_closing=True):
    """The four list columns (with the trailing comma) for alias `o`."""
    return (
        "o.status AS opportunity_status, "
        + ("o.custom_agent_status" if has_stage else "NULL") + " AS opportunity_stage, "
        + ("o.expected_closing" if has_closing else "NULL") + " AS opportunity_closing, "
        + "o.title AS opportunity_title, "
    )


# ── ConvRow fields ───────────────────────────────────────────────────────────

OPPORTUNITY_KEYS = ("opportunity_status", "opportunity_stage", "opportunity_closing", "opportunity_title")


def _text(value):
    text = str(value if value is not None else "").strip()
    return text or None


def date_str(value):
    """"YYYY-MM-DD" from a date / datetime / string, else None."""
    if value in (None, ""):
        return None
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None


def opportunity_fields(src):
    """The four ConvRow keys from a row carrying them (list query columns,
    or a lookup mapped onto the same names). Missing → all None."""
    src = src or {}
    return {
        "opportunity_status": _text(src.get("opportunity_status")),
        "opportunity_stage": _text(src.get("opportunity_stage")),
        "opportunity_closing": date_str(src.get("opportunity_closing")),
        "opportunity_title": _text(src.get("opportunity_title")),
    }


def apply_user_state(row, state):
    """A copy of ConvRow `row` with one user's own flags: pinned, muted and
    marked_unread. A chat the user marked unread shows `unread_count` >= 1
    for them (the conversation's own counter is untouched)."""
    state = state or {}
    out = dict(row or {})
    out["pinned"] = bool(state.get("pinned"))
    out["muted"] = bool(state.get("muted"))
    marked = bool(state.get("marked_unread"))
    out["marked_unread"] = marked
    try:
        count = int(out.get("unread_count") or 0)
    except (TypeError, ValueError):
        count = 0
    out["unread_count"] = max(count, 1) if marked else count
    return out


# ── today ────────────────────────────────────────────────────────────────────

def _as_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def day_start(now):
    """Midnight of `now`'s day (site time in, site time out)."""
    now = _as_datetime(now)
    return _dt.datetime.combine(now.date(), _dt.time.min) if now else None


def minutes_since(value, now):
    """Whole minutes from `value` to `now` (never negative), None when
    `value` is unset or unreadable. Both are naive site-time datetimes."""
    then = _as_datetime(value)
    current = _as_datetime(now)
    if then is None or current is None:
        return None
    seconds = (current - then).total_seconds()
    return int(seconds // 60) if seconds > 0 else 0


# ── Opportunity card ─────────────────────────────────────────────────────────

def stages_from_options(options):
    """Select options text → ordered stages, blanks and duplicates dropped."""
    out = []
    for line in str(options or "").split("\n"):
        line = line.strip()
        if line and line not in out:
            out.append(line)
    return out


def _float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def opportunity_card(row, stages=None, responsible=None, iso=None):
    """The drawer card from an Opportunity row (title, status,
    custom_agent_status, expected_closing, opportunity_amount, currency,
    modified). `iso` formats `modified`."""
    if not row or not row.get("name"):
        return None
    modified = row.get("modified")
    return {
        "name": row["name"],
        "title": _text(row.get("title")) or row["name"],
        "status": _text(row.get("status")) or "",
        "stage": _text(row.get("custom_agent_status")),
        "stages": list(stages or []),
        "expected_closing": date_str(row.get("expected_closing")),
        "responsible": [n for n in (responsible or []) if n],
        "amount": _float(row.get("opportunity_amount")),
        "currency": _text(row.get("currency")) or "",
        "modified": (iso(modified) if iso else (str(modified) if modified else None)),
    }


# ── quick replies / tags ─────────────────────────────────────────────────────

TITLE_LENGTH = 40
TAG_MAX = 140
_ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def quick_reply_fields(text, title=None):
    """{title, text_en | text_ar} for a Personal quick reply. Arabic-script
    text goes to text_ar (render_quick_reply falls back to either slot).
    The title defaults to the first 40 characters, whitespace collapsed.
    Raises ValueError on empty text."""
    body = str(text if text is not None else "").strip()
    if not body:
        raise ValueError("text")
    name = " ".join(str(title if title is not None else "").split())
    if not name:
        name = " ".join(body.split())[:TITLE_LENGTH].strip()
    slot = "text_ar" if _ARABIC.search(body) else "text_en"
    return {"title": name[:TAG_MAX], slot: body}


def clean_tag_name(value):
    """A usable tag name: trimmed, inner whitespace collapsed; ValueError
    when empty or longer than 140 characters."""
    name = " ".join(str(value if value is not None else "").split())
    if not name or len(name) > TAG_MAX:
        raise ValueError(name)
    return name
