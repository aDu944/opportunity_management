"""
Bench-free logic for `team_today.get_team_today` — the late cutoff and the
per-employee roll-up — so it is testable without frappe
(`tests/test_team_today_pure.py`).
"""

import datetime as _dt

NAME_LIMIT = 5


def _int(value, default):
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


def late_cutoff(expected_hour, threshold_minutes):
    """Wall-clock time after which a first IN counts as late.

    Same rule as `api.py` (late-check-in leave): cutoff = expected_hour:00 +
    threshold minutes; a check-in AT the cutoff is on time, only after is late.
    Empty / garbage settings fall back to 09:15."""
    h = _int(expected_hour, 9) or 9
    m = _int(threshold_minutes, 15)
    if not 0 <= h <= 23:
        h = 9
    if m < 0:
        m = 15
    total = min(h * 60 + m, 23 * 60 + 59)
    return _dt.time(total // 60, total % 60)


def is_late(first_in, cutoff):
    """True when the datetime `first_in` is strictly after `cutoff` (a time)."""
    if not first_in or cutoff is None:
        return False
    t = first_in.time() if isinstance(first_in, _dt.datetime) else first_in
    return t.replace(microsecond=0) > cutoff


def summarize(rows, cutoff, limit=NAME_LIMIT):
    """Roll per-employee rows up into the card's counts.

    Each row: {employee_name, first_in, last_in, last_out, on_leave}. An
    employee with an IN today is never counted as on leave (they came in)."""
    total = checked_in = late = on_leave = checked_out = 0
    late_rows, missing = [], []
    for r in rows or ():
        total += 1
        name = (r.get("employee_name") or r.get("name") or "").strip()
        first_in = r.get("first_in")
        if first_in:
            checked_in += 1
            if is_late(first_in, cutoff):
                late += 1
                late_rows.append((first_in, name))
            last_in, last_out = r.get("last_in"), r.get("last_out")
            if last_in and last_out and last_out > last_in:
                checked_out += 1
        elif r.get("on_leave"):
            on_leave += 1
        else:
            missing.append(name)
    late_rows.sort(key=lambda x: x[0])
    missing.sort(key=lambda s: s.lower())
    return {
        "total": total,
        "checked_in": checked_in,
        "late": late,
        "on_leave": on_leave,
        "not_in": max(0, total - checked_in - on_leave),
        "checked_out": checked_out,
        "late_names": [n for _, n in late_rows if n][:limit],
        "not_in_names": [n for n in missing if n][:limit],
    }


def empty_summary():
    return summarize([], None)
