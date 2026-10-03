"""
Attendance reminder scheduled tasks.

All entrypoints are wired into the existing `*/5 * * * *` cron in hooks.py.
Each one self-gates on the current local (site-timezone) time-of-day and
uses a per-slot per-day global flag so it fires at most once per slot per
day even if the poll bracket overlaps two ticks.

Timing (Baghdad time / Asia/Baghdad):

  09:45   check-in closes in 15 minutes  — non-checked-in employees
  09:55   check-in closes in 5 minutes   — non-checked-in employees
  10:00   regular check-in is closed     — non-checked-in employees (late
          check-in still possible until the late cutoff, using leave)
  16:00   don't forget to check out      — checked-in-but-not-out employees
  17:00   don't forget to check out      — checked-in-but-not-out employees
  18:00   don't forget to check out      — checked-in-but-not-out employees
  19:00   don't forget to check out      — checked-in-but-not-out employees
  19:55   auto-checkout in 5 minutes     — checked-in-but-not-out employees
  20:00   auto-checkout runs             — existing api.auto_checkout_pending_employees

The three check-in pushes are anchored to ESS Mobile Settings
`checkin_reminder_deadline_hour` (default 10) — the hour REGULAR check-in
closes. They deliberately do NOT use `checkin_window_end_hour`: that one is
the hard window ess_hooks enforces on every Employee Checkin and stays at
the late cutoff (12 on the live site) so late check-ins with a half-day
leave deduction can still be recorded. Anchoring the reminders to it made
them fire at 11:45 / 11:55 instead of 09:45 / 09:55.

The 5-minute auto-checkout warning follows `auto_checkout_hour`. The
4/5/6/7 PM checkout reminders are hardcoded to the anchor times the user
asked for. All clock times shown to employees are 12-hour (AM/PM, ص/م).
"""

import frappe

# Poll window — each function is called every 5 minutes by the cron. The
# poll window defines how many seconds AFTER the target instant a fire is
# still valid (so a slightly slow scheduler tick doesn't skip a slot).
POLL_WINDOW_SECONDS = 5 * 60

# Afternoon checkout reminder anchor hours (Baghdad local, 24h).
CHECKOUT_REMINDER_HOURS = (16, 17, 18, 19)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _settings():
    try:
        return frappe.get_single("ESS Mobile Settings")
    except Exception:
        return None


def _is_working_day(s) -> bool:
    working_days = {
        d.strip()
        for d in (s.get("working_days") or "Sun,Mon,Tue,Wed,Thu").split(",")
        if d.strip()
    }
    day_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    now = frappe.utils.now_datetime()
    return day_map[now.weekday()] in working_days


def _in_poll_window(target_h: int, target_m: int) -> bool:
    """True iff we're within [target, target + POLL_WINDOW) right now."""
    now = frappe.utils.now_datetime()
    target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    delta = (now - target).total_seconds()
    return 0 <= delta <= POLL_WINDOW_SECONDS


def _fire_once_per_day(slot_key: str) -> bool:
    """Atomic once-per-slot-per-day guard. Returns True the first time it's
    called on a given date for the given slot; False on subsequent calls."""
    today_str = frappe.utils.now_datetime().strftime("%Y-%m-%d")
    global_key = f"ess_reminder_{slot_key}_date"
    if frappe.db.get_global(global_key) == today_str:
        return False
    # Mark BEFORE the work so a slow send loop can't double-dispatch.
    frappe.db.set_global(global_key, today_str)
    frappe.db.commit()
    return True


def _deadline_hour(s) -> int:
    """Hour regular check-in closes (reminder anchor). Empty/0/garbage → 10."""
    try:
        h = int(s.get("checkin_reminder_deadline_hour") or 0)
    except (TypeError, ValueError):
        h = 0
    return h if 1 <= h <= 23 else 10


def _late_cutoff_hour(s) -> int:
    """Hour after which no check-in of any kind is accepted (default noon)."""
    try:
        h = int(s.get("late_checkin_cutoff_hour") or 0)
    except (TypeError, ValueError):
        h = 0
    return h if 1 <= h <= 23 else 12


def _clock_12h(hour: int, minute: int = 0) -> tuple:
    """(EN, AR) 12-hour labels, e.g. ("12:00 PM", "12:00 م")."""
    h12 = hour % 12 or 12
    am = hour % 24 < 12
    return (
        f"{h12}:{minute:02d} {'AM' if am else 'PM'}",
        f"{h12}:{minute:02d} {'ص' if am else 'م'}",
    )


def _employees_missing_checkin():
    """Active employees with a token who have no IN checkin today."""
    today = frappe.utils.today()
    return frappe.db.sql(
        """
        SELECT e.name AS employee, e.employee_name, e.custom_fcm_token AS token
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
          AND e.custom_fcm_token IS NOT NULL
          AND e.custom_fcm_token != ''
          AND NOT EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'IN'
          )
        """,
        (today,),
        as_dict=True,
    )


def _employees_missing_checkout():
    """Active employees with a token who have an IN today but no OUT after
    their last IN (i.e. they're still on the clock)."""
    today = frappe.utils.today()
    return frappe.db.sql(
        """
        SELECT DISTINCT e.name AS employee, e.employee_name, e.custom_fcm_token AS token
        FROM `tabEmployee` e
        WHERE e.status = 'Active'
          AND e.custom_fcm_token IS NOT NULL
          AND e.custom_fcm_token != ''
          AND EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'IN'
          )
          AND NOT EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` c
              WHERE c.employee = e.name
                AND DATE(c.time) = %s
                AND c.log_type = 'OUT'
                AND c.time > (
                    SELECT MAX(c2.time) FROM `tabEmployee Checkin` c2
                    WHERE c2.employee = e.name
                      AND DATE(c2.time) = %s
                      AND c2.log_type = 'IN'
                )
          )
        """,
        (today, today, today),
        as_dict=True,
    )


def _send_bulk(rows, title: str, body: str, kind: str) -> int:
    from opportunity_management.opportunity_management.fcm_utils import send_fcm
    sent = 0
    for r in rows:
        try:
            if send_fcm(r["token"], title=title, body=body, data={"type": kind}):
                sent += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"attendance_reminder:{kind}")
    return sent


# ── Public scheduler entrypoints ───────────────────────────────────────────────

def send_checkin_closing_15min_warning():
    """15 minutes before regular check-in closes → warn non-checked-in employees.

    Target time = (checkin_reminder_deadline_hour - 0h15m) in Baghdad local time.
    """
    s = _settings()
    if not s or not _is_working_day(s):
        return
    end_h = _deadline_hour(s)
    # 15 min before end_h → end_h-1 at :45
    target_h = end_h - 1
    target_m = 45
    if not _in_poll_window(target_h, target_m):
        return
    if not _fire_once_per_day("checkin_closing_15"):
        return
    rows = _employees_missing_checkin()
    _send_bulk(
        rows,
        title="⏰ Check-in closes in 15 minutes",
        body="سيغلق تسجيل الحضور بعد ١٥ دقيقة — سجّل حضورك الآن.\n"
             "Check-in closes in 15 minutes — please check in now.",
        kind="checkin_closing_15",
    )


def send_checkin_closing_5min_warning():
    """5 minutes before regular check-in closes → last warning."""
    s = _settings()
    if not s or not _is_working_day(s):
        return
    end_h = _deadline_hour(s)
    target_h = end_h - 1
    target_m = 55
    if not _in_poll_window(target_h, target_m):
        return
    if not _fire_once_per_day("checkin_closing_5"):
        return
    rows = _employees_missing_checkin()
    _send_bulk(
        rows,
        title="⏰ Check-in closes in 5 minutes!",
        body="سيغلق تسجيل الحضور بعد ٥ دقائق فقط!\n"
             "Check-in closes in 5 minutes!",
        kind="checkin_closing_5",
    )


def send_checkin_closed_notice():
    """At the deadline hour → tell non-checked-in employees that regular
    check-in is closed but a late check-in (which uses leave) is still
    possible until the late cutoff."""
    s = _settings()
    if not s or not _is_working_day(s):
        return
    end_h = _deadline_hour(s)
    if not _in_poll_window(end_h, 0):
        return
    cutoff_h = _late_cutoff_hour(s)
    if cutoff_h <= end_h:
        return  # no late window → the 5-minute warning was the last word
    if not _fire_once_per_day("checkin_closed"):
        return
    cutoff_en, cutoff_ar = _clock_12h(cutoff_h)
    rows = _employees_missing_checkin()
    _send_bulk(
        rows,
        title="⏰ Regular check-in is closed",
        body=f"انتهى وقت تسجيل الحضور العادي. يمكنك تسجيل حضور متأخر حتى {cutoff_ar} "
             f"وسيُخصم من رصيد إجازتك.\n"
             f"Regular check-in is closed. You can still check in late until "
             f"{cutoff_en} — it will use leave.",
        kind="checkin_closed",
    )


def send_checkout_reminder_hourly():
    """Fires hourly at 16:00, 17:00, 18:00, 19:00 Baghdad time — nudges any
    employee who's still on the clock to check out."""
    s = _settings()
    if not s or not _is_working_day(s):
        return
    now = frappe.utils.now_datetime()
    if now.hour not in CHECKOUT_REMINDER_HOURS:
        return
    if not _in_poll_window(now.hour, 0):
        return
    slot = f"checkout_reminder_{now.hour}"
    if not _fire_once_per_day(slot):
        return
    rows = _employees_missing_checkout()
    _send_bulk(
        rows,
        title="🕒 Don't forget to check out",
        body="لم تسجّل انصرافك بعد — لا تنسَ تسجيل الانصراف.\n"
             "You haven't checked out yet — please remember to check out.",
        kind="checkout_reminder",
    )


def send_pre_auto_checkout_warning():
    """5 minutes before auto-checkout runs → final warning that the system
    is about to clock the employee out automatically.

    Target = (auto_checkout_hour - 0h5m) in Baghdad local time.
    """
    s = _settings()
    if not s or not _is_working_day(s):
        return
    auto_h = int(s.get("auto_checkout_hour") or 0)
    if auto_h <= 0:
        return  # auto-checkout disabled → nothing to warn about
    target_h = auto_h - 1
    target_m = 55
    if not _in_poll_window(target_h, target_m):
        return
    if not _fire_once_per_day("pre_auto_checkout"):
        return
    rows = _employees_missing_checkout()
    _send_bulk(
        rows,
        title="⚠ Auto-checkout in 5 minutes",
        body="سيتم تسجيل انصرافك تلقائياً بعد ٥ دقائق. سجّل انصرافك الآن إن رغبت.\n"
             "You will be auto-checked out in 5 minutes. Check out now to override.",
        kind="pre_auto_checkout",
    )
