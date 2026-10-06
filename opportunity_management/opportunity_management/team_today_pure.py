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


# --- Team attendance page (`team_today.get_team_attendance`) ---------------

ZONE_SEP = "\x1e"  # GROUP_CONCAT separator between IN logs
ZONE_FIELD_SEP = "|"  # "<outside_zone flag>|<reason>" inside one IN log

# Section order on the page: late, not in yet, present, checked out, on leave.
STATUS_ORDER = {"late": 0, "not_in": 1, "present": 2, "checked_out": 3, "on_leave": 4}
SUMMARY_KEYS = ("total", "checked_in", "late", "on_leave", "not_in", "checked_out")
_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def fmt_time(value):
    """'HH:MM:SS' for a datetime / time / timedelta, else None."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        value = value.time()
    if isinstance(value, _dt.timedelta):
        secs = int(value.total_seconds()) % 86400
        return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    if isinstance(value, _dt.time):
        return value.strftime("%H:%M:%S")
    return str(value)


def minutes_late(first_in, cutoff):
    """Whole minutes past the cutoff, rounded up (9:15:01 → 1); 0 if on time.
    Matches the Desk report, which counts any started minute."""
    if not is_late(first_in, cutoff):
        return 0
    t = first_in.time() if isinstance(first_in, _dt.datetime) else first_in
    secs = (t.hour * 3600 + t.minute * 60 + t.second) - (cutoff.hour * 3600 + cutoff.minute * 60)
    return max(1, -(-secs // 60))


def parse_zone(blob):
    """(outside_zone, reason) of the FIRST IN, from the GROUP_CONCAT blob
    "<flag>|<reason>\\x1e<flag>|<reason>…" ordered by time — the same IN the
    Desk report reads the zone from."""
    if not blob:
        return False, None
    first = str(blob).split(ZONE_SEP, 1)[0]
    flag, _sep, reason = first.partition(ZONE_FIELD_SEP)
    outside = _int(flag, 0) != 0
    reason = (reason or "").strip() or None
    return outside, (reason if outside else None)


def attendance_status(row, cutoff):
    """One status per employee. An IN today wins over a leave (as the card);
    a late arrival stays "late" even after checking out so the late section
    is complete — `checked_out` on the row still says they left."""
    first_in = row.get("first_in")
    if first_in:
        if is_late(first_in, cutoff):
            return "late"
        if _has_left(row):
            return "checked_out"
        return "present"
    return "on_leave" if row.get("on_leave") else "not_in"


def _has_left(row):
    last_in, last_out = row.get("last_in"), row.get("last_out")
    return bool(last_in and last_out and last_out > last_in)


def attendance_row(row, cutoff, leave_type=None):
    """Raw SQL row → the page's row dict."""
    status = attendance_status(row, cutoff)
    has_in = bool(row.get("first_in"))
    outside, reason = parse_zone(row.get("zone")) if has_in else (False, None)
    return {
        "employee": row.get("employee") or row.get("name"),
        "employee_name": (row.get("employee_name") or row.get("employee")
                          or row.get("name") or "").strip(),
        "department": row.get("department") or None,
        "designation": row.get("designation") or None,
        "image": row.get("image") or None,
        "status": status,
        "first_in": fmt_time(row.get("first_in")),
        "last_out": fmt_time(row.get("last_out")) if has_in else None,
        "checked_out": has_in and _has_left(row),
        "minutes_late": minutes_late(row.get("first_in"), cutoff) if has_in else 0,
        "leave_type": leave_type if row.get("on_leave") else None,
        "outside_zone": outside,
        "outside_zone_reason": reason,
    }


def sort_key(r):
    """Late (latest first-in first) → not in (A-Z) → present → checked out
    → on leave; ties by name."""
    status = r.get("status")
    name = (r.get("employee_name") or "").lower()
    if status == "late":
        fi = r.get("first_in") or ""
        # Latest first: invert "HH:MM:SS" by sorting on negative seconds.
        try:
            h, m, s = (int(x) for x in fi.split(":"))
            secondary = -(h * 3600 + m * 60 + s)
        except ValueError:
            secondary = 0
        return (STATUS_ORDER["late"], secondary, name)
    return (STATUS_ORDER.get(status, 9), 0, name)


def sort_rows(rows):
    return sorted(rows or (), key=sort_key)


def build_attendance(raw_rows, leaves, cutoff):
    """(summary, rows) for the page. `leaves` maps employee → leave type;
    the summary is the card's roll-up of the same rows so both always agree."""
    leaves = leaves or {}
    prepared = []
    for r in raw_rows or ():
        emp = r.get("employee") or r.get("name")
        item = dict(r)
        item["on_leave"] = emp in leaves
        prepared.append(item)
    full = summarize(prepared, cutoff)
    summary = {k: full[k] for k in SUMMARY_KEYS}
    rows = [attendance_row(r, cutoff, leaves.get(r.get("employee") or r.get("name")))
            for r in prepared]
    return summary, sort_rows(rows)


def is_working_day(day, working_days, holidays=()):
    """`working_days` is ESS Mobile Settings' "Sun,Mon,…" (same default as
    the reminders); `holidays` is a set of dates that are off regardless."""
    days = {d.strip() for d in (working_days or "Sun,Mon,Tue,Wed,Thu").split(",") if d.strip()}
    if day in set(holidays or ()):
        return False
    return _DAY_ABBR[day.weekday()] in days


def clamp_day(requested, today_):
    """The requested date, or today when missing or in the future."""
    if requested is None or requested > today_:
        return today_
    return requested
