"""Compatibility wrapper for legacy task path.

Task logic lives in opportunity_management.opportunity_management.tasks.
"""

from opportunity_management.opportunity_management import tasks as tasks_v2


def send_opportunity_reminders():
    return tasks_v2.send_opportunity_reminders()


def send_management_daily_closing_summary():
    return tasks_v2.send_management_daily_closing_summary()


def send_manager_weekly_digest():
    return tasks_v2.send_manager_weekly_digest()
