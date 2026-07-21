"""
Compatibility wrappers for legacy API paths.

All logic lives in opportunity_management.opportunity_management.api.
"""

import frappe
from opportunity_management.opportunity_management import api as api_v2


@frappe.whitelist()
def get_my_opportunities(user=None, include_completed=False):
    return api_v2.get_my_opportunities(user=user, include_completed=include_completed)


@frappe.whitelist()
def get_opportunity_kpi(user=None, date_range="all", from_date=None, to_date=None):
    return api_v2.get_opportunity_kpi(user=user, date_range=date_range, from_date=from_date, to_date=to_date)


@frappe.whitelist()
def get_kpi_by_employee(from_date=None, to_date=None):
    return api_v2.get_kpi_by_employee(from_date=from_date, to_date=to_date)


@frappe.whitelist()
def get_kpi_by_team(from_date=None, to_date=None):
    return api_v2.get_kpi_by_team(from_date=from_date, to_date=to_date)


@frappe.whitelist()
def close_opportunity_todo(todo_name):
    return api_v2.close_opportunity_todo(todo_name)


@frappe.whitelist()
def get_opportunity_details(opportunity_name):
    return api_v2.get_opportunity_details(opportunity_name)


@frappe.whitelist()
def get_team_opportunities(team=None, include_completed=False):
    return api_v2.get_team_opportunities(team=team, include_completed=include_completed)


@frappe.whitelist()
def get_employee_opportunity_stats(team=None):
    return api_v2.get_employee_opportunity_stats(team=team)


@frappe.whitelist()
def get_available_teams():
    return api_v2.get_available_teams()


@frappe.whitelist()
def geofence_checkin_reminder(location_name):
    """Called by the iOS app when the device enters a registered geofence region.
    Sends an FCM push notification to the employee reminding them to check in.
    """
    user = frappe.session.user

    # Get the employee's FCM token stored by the mobile app on login
    emp = frappe.db.get_value(
        "Employee",
        {"user_id": user},
        ["name", "fcm_token"],
        as_dict=True,
    )
    if not emp or not emp.get("fcm_token"):
        return {"status": "no_token"}

    _send_fcm(
        token=emp["fcm_token"],
        title=f"أنت في {location_name}",
        body="لا تنسَ تسجيل الحضور!\nDon't forget to check in!",
    )
    return {"status": "sent"}


def _send_fcm(token: str, title: str, body: str):
    """Send a single FCM notification.

    Thin wrapper that delegates to `fcm_utils.send_fcm` so the whole app
    goes through ONE credential path (site config) and ONE working init
    pattern (ephemeral naked FirebaseApp per send). The prior body of
    this function inspected `firebase_admin._apps` to decide whether to
    init from a file — that check was tripped by fcm_utils's named apps
    living in the same registry, causing this path to skip init and then
    hit `messaging.send(message)` without an `app=` argument, which fell
    into a broken default-app lookup that surfaced as a 401. The file it
    tried to load didn't exist on the server anyway."""
    from opportunity_management.opportunity_management.fcm_utils import send_fcm
    send_fcm(token=token, title=title, body=body)
