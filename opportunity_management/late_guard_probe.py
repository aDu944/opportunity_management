import frappe


def check():
    # Test the actual guard with the exact checkin_time the app sent
    s = frappe.get_single("ESS Mobile Settings")
    print(f"expected_checkin_hour: {s.get('expected_checkin_hour')!r}")
    print(f"late_checkin_threshold_minutes: {s.get('late_checkin_threshold_minutes')!r}")

    expected_h = int(s.get("expected_checkin_hour") or 9)
    threshold_m = int(s.get("late_checkin_threshold_minutes") or 15)
    on_time_minutes = expected_h * 60 + threshold_m
    print(f"cutoff (minutes since midnight): {on_time_minutes}")

    for time_str in ["08:57:18", "8:57:18", "2026-07-28 08:57:18"]:
        from frappe.utils import get_datetime
        try:
            t = get_datetime(time_str)
            actual_minutes = t.hour * 60 + t.minute + (1 if t.second > 0 else 0)
            verdict = "on_time" if actual_minutes <= on_time_minutes else "LATE"
            print(f"  {time_str!r:32s} → hour={t.hour} min={t.minute} sec={t.second} → actual={actual_minutes} → {verdict}")
        except Exception as e:
            print(f"  {time_str!r:32s} → ERROR: {e}")

    # And now: what did submit_late_checkin_leave get called with?
    # Look at the newest ess-related error/log for hints
    return {"cutoff": on_time_minutes}
