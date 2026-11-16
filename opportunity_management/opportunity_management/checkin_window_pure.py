"""
Bench-free rules for the check-in window (`tests/test_checkin_window_pure.py`).

Who uses them:

* `api.submit_missed_checkin_leave` — the home card's "Submit late check-in".
  App builds before 1.0.7 (commit 255cb84) offered that button to anyone past
  the 09:15 late boundary, even while the window was still open, and it only
  filed the Time-Off leave: no IN was ever recorded, so the day read as Absent
  and no Check out was offered (Afraa 10 and 16 Nov, Haider Ghaith 16 Nov,
  Aya 9 Nov, Saleh 11 Nov, Taher 14 Nov 2026). The server now records the IN
  itself while the window is open, so a late check-in is a check-in for every
  app version.
"""


def window(settings_get):
    """(start_hour, end_hour) from ESS Mobile Settings, or None when the
    window is unset or misconfigured — the same reading `before_checkin_insert`
    uses, so the two agree on when a punch is allowed."""
    try:
        start = int(settings_get("checkin_window_start_hour") or 0)
        end = int(settings_get("checkin_window_end_hour") or 0)
    except (TypeError, ValueError):
        return None
    if start <= 0 or end <= 0 or end <= start:
        return None
    return start, end


def is_open(hour, win):
    """True while a punch at `hour` would pass the window guard."""
    if win is None:
        return False
    start, end = win
    return start <= hour < end


def record_punch(hour, win, has_in_today):
    """Should "Submit late check-in" record an IN punch at this moment?

    Yes while the window is open and no IN exists today: the employee is at
    the phone tapping to check in, only an older app labelled the button
    differently. Once the window has closed the action keeps its original
    meaning (leave without a punch)."""
    return is_open(hour, win) and not has_in_today
