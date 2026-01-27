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
