"""
Pure decisions behind WhatsApp agent groups (`agent_groups.py`).

No frappe import: the frappe side gathers members, mutes, settings and times
and hands them in as plain values, so every rule here is testable without a
bench (tests/test_agent_groups_pure.py).

    pick_round_robin(members, pointer, away)      next member + new pointer
    members_to_alert(members, muted, away)        who gets a group push
    is_overdue(assigned_at, first_response_at,
               timeout_minutes, business_minutes_fn)
    business_minutes_between(start, end, business_days, window, short_day)
    hold_out_of_hours(strategy, out_of_hours, in_hours)
"""

import datetime

RING = "Ring"
ROUND_ROBIN = "Round Robin"
HOLD = "Hold"
ROUND_ROBIN_ANYWAY = "Round Robin anyway"

DAY_TOKENS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_SECONDS = 24 * 60 * 60


def _clean(users):
    """Ordered, de-duplicated, stripped user ids (empty ones dropped)."""
    seen, out = set(), []
    for user in users or ():
        user = str(user or "").strip()
        if user and user not in seen:
            seen.add(user)
            out.append(user)
    return out


def pick_round_robin(members, pointer, away=frozenset()):
    """`(user, new_pointer)` for a Round Robin group.

    `members` is the ordered active-member list, `pointer` the index of the
    next candidate (stored on the group). Members in `away` are skipped; the
    new pointer is the slot after the one picked. `(None, pointer)` when
    nobody is available (no members, or all away).
    """
    members = _clean(members)
    if not members:
        return None, 0
    away = set(away or ())
    try:
        start = int(pointer or 0) % len(members)
    except (TypeError, ValueError):
        start = 0
    for step in range(len(members)):
        index = (start + step) % len(members)
        if members[index] not in away:
            return members[index], (index + 1) % len(members)
    return None, start


def members_to_alert(members, muted=frozenset(), away=frozenset()):
    """Active members who should get a group push: not muted on the thread,
    not away. Order kept, duplicates dropped."""
    skip = set(muted or ()) | set(away or ())
    return [u for u in _clean(members) if u not in skip]


def is_overdue(group_assigned_at, first_response_at, timeout_minutes, business_minutes_fn):
    """True when a ringing chat has waited `timeout_minutes` business minutes
    without a first response. A timeout <= 0 disables the alert.
    `business_minutes_fn(group_assigned_at)` returns the business minutes
    elapsed since then (the caller binds "now" and the schedule)."""
    if not group_assigned_at or first_response_at:
        return False
    try:
        timeout = int(timeout_minutes or 0)
    except (TypeError, ValueError):
        return False
    if timeout <= 0:
        return False
    return business_minutes_fn(group_assigned_at) >= timeout


def hold_out_of_hours(strategy, out_of_hours, in_hours):
    """Round Robin outside business hours with `out_of_hours == Hold` rings
    the group instead of picking someone who is off shift. Ring always
    rings, so this only changes Round Robin."""
    return strategy == ROUND_ROBIN and not in_hours and (out_of_hours or HOLD) == HOLD


def _day_intervals(day_start, token, business_days, window, short_day):
    """Business intervals (datetime pairs) of one calendar day.

    Mirrors `whatsapp_utils.is_business_hours`: a day outside `business_days`
    has none; the short day swaps in its own window; no window (None) means
    the whole day; an overnight window (start > end) counts the early part
    and the late part of the same calendar day."""
    if business_days and token not in business_days:
        return []
    if short_day and short_day[0] == token:
        window = (short_day[1], short_day[2])
    if not window:
        return [(day_start, day_start + datetime.timedelta(seconds=DAY_SECONDS))]
    start_s, end_s = int(window[0]), int(window[1])
    at = lambda s: day_start + datetime.timedelta(seconds=s)  # noqa: E731
    if start_s < end_s:
        return [(at(start_s), at(end_s))]
    return [(at(0), at(end_s)), (at(start_s), at(DAY_SECONDS))]


def business_minutes_between(start, end, business_days=None, window=None, short_day=None):
    """Whole business minutes between two naive datetimes.

    business_days  set of 3-letter day tokens ("sat", ...); empty/None = every day
    window         (start_seconds, end_seconds) since midnight; None = all day
    short_day      (day_token, start_seconds, end_seconds) or None
    """
    if not start or not end or end <= start:
        return 0
    days = {str(d).strip().lower()[:3] for d in (business_days or ())}
    days = {d for d in days if d in DAY_TOKENS}
    total = 0.0
    day = datetime.datetime.combine(start.date(), datetime.time())
    while day < end:
        token = day.strftime("%a").lower()[:3]
        for lo, hi in _day_intervals(day, token, days, window, short_day):
            lo, hi = max(lo, start), min(hi, end)
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += datetime.timedelta(days=1)
    return int(total // 60)
