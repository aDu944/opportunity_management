"""
API Endpoints for Opportunity Management

Provides data for:
1. My Opportunities page - employee's open tasks
2. KPI Dashboard - completion rate metrics
"""

import frappe
from frappe import _
from frappe.utils import nowdate, getdate, date_diff, flt
from datetime import datetime


@frappe.whitelist()
def get_my_opportunities(user=None):
    """
    Get all open opportunity tasks for the current user.
    
    Returns a list of opportunities with their ToDos and closing dates.
    """
    if not user:
        user = frappe.session.user
    
    # Get all open ToDos for this user linked to Opportunities
    todos = frappe.get_all(
        "ToDo",
        filters={
            "allocated_to": user,
            "reference_type": "Opportunity",
            "status": "Open"
        },
        fields=["name", "reference_name", "date", "description", "priority", "assigned_by", "creation"]
    )
    
    opportunities = []
    today = getdate(nowdate())
    
    for todo in todos:
        # Get opportunity details
        opp = frappe.get_doc("Opportunity", todo.reference_name)
        
        closing_date = getdate(opp.expected_closing) if opp.expected_closing else None
        days_remaining = date_diff(closing_date, today) if closing_date else None
        
        # Determine status color
        if days_remaining is None:
            status_color = "gray"
            status_label = "No closing date"
        elif days_remaining < 0:
            status_color = "red"
            status_label = f"Overdue by {abs(days_remaining)} days"
        elif days_remaining == 0:
            status_color = "red"
            status_label = "Due today"
        elif days_remaining <= 3:
            status_color = "orange"
            status_label = f"{days_remaining} days remaining"
        elif days_remaining <= 7:
            status_color = "yellow"
            status_label = f"{days_remaining} days remaining"
        else:
            status_color = "green"
            status_label = f"{days_remaining} days remaining"
        
        opportunities.append({
            "todo_name": todo.name,
            "opportunity_name": opp.name,
            "party_name": opp.party_name,
            "expected_closing": opp.expected_closing,
            "days_remaining": days_remaining,
            "status_color": status_color,
            "status_label": status_label,
            "opportunity_status": opp.status,
            "priority": todo.priority,
            "assigned_by": todo.assigned_by,
            "assigned_date": todo.creation,
            "source": opp.source,
            "opportunity_type": opp.opportunity_type,
        })
    
    # Sort by days remaining (most urgent first)
    opportunities.sort(key=lambda x: (x["days_remaining"] is None, x["days_remaining"] or 9999))
    
    return opportunities


@frappe.whitelist()
def get_opportunity_kpi(user=None, date_range="all"):
    """
    Get KPI metrics for opportunity completion.
    
    Args:
        user: Optional - filter by specific user, otherwise shows all
        date_range: 'all', 'month', 'quarter', 'year'
    
    Returns:
        Dictionary with KPI metrics including on-time completion rate
    """
    filters = {
        "status": ["in", ["Converted", "Closed", "Lost"]]
    }
    
    # Apply date range filter
    today = getdate(nowdate())
    if date_range == "month":
        filters["modified"] = [">=", frappe.utils.add_months(today, -1)]
    elif date_range == "quarter":
        filters["modified"] = [">=", frappe.utils.add_months(today, -3)]
    elif date_range == "year":
        filters["modified"] = [">=", frappe.utils.add_months(today, -12)]
    
    # Get closed opportunities
    opportunities = frappe.get_all(
        "Opportunity",
        filters=filters,
        fields=["name", "expected_closing", "modified", "status", "party_name"]
    )
    
    # Calculate metrics
    total_closed = len(opportunities)
    completed_on_time = 0
    completed_late = 0
    
    for opp in opportunities:
        if opp.expected_closing and opp.modified:
            closing_date = getdate(opp.expected_closing)
            completed_date = getdate(opp.modified)
            
            if completed_date <= closing_date:
                completed_on_time += 1
            else:
                completed_late += 1
    
    # Calculate per-user metrics if needed
    user_metrics = {}
    if not user:
        user_metrics = calculate_user_metrics(date_range)
    
    on_time_rate = (completed_on_time / total_closed * 100) if total_closed > 0 else 0
    
    return {
        "total_closed": total_closed,
        "completed_on_time": completed_on_time,
        "completed_late": completed_late,
        "on_time_rate": round(on_time_rate, 1),
        "user_metrics": user_metrics,
        "date_range": date_range,
    }


def calculate_user_metrics(date_range="all"):
    """Calculate KPI metrics per user."""
    # Get all users who have been assigned opportunities
    todos = frappe.get_all(
        "ToDo",
        filters={
            "reference_type": "Opportunity",
            "status": "Closed"
        },
        fields=["allocated_to", "reference_name", "modified"],
        group_by="allocated_to, reference_name"
    )
    
    # Group by user
    user_data = {}
    
    for todo in todos:
        user = todo.allocated_to
        if not user:
            continue
        
        if user not in user_data:
            user_data[user] = {
                "user": user,
                "user_name": frappe.db.get_value("User", user, "full_name") or user,
                "total": 0,
                "on_time": 0,
                "late": 0
            }
        
        # Get opportunity details
        opp = frappe.db.get_value(
            "Opportunity",
            todo.reference_name,
            ["expected_closing", "status"],
            as_dict=True
        )
        
        if opp and opp.status in ["Converted", "Closed", "Lost"]:
            user_data[user]["total"] += 1
            
            if opp.expected_closing:
                closing_date = getdate(opp.expected_closing)
                completed_date = getdate(todo.modified)
                
                if completed_date <= closing_date:
                    user_data[user]["on_time"] += 1
                else:
                    user_data[user]["late"] += 1
    
    # Calculate percentages
    for user, data in user_data.items():
        if data["total"] > 0:
            data["on_time_rate"] = round(data["on_time"] / data["total"] * 100, 1)
        else:
            data["on_time_rate"] = 0
    
    # Sort by on-time rate descending
    sorted_users = sorted(user_data.values(), key=lambda x: x["on_time_rate"], reverse=True)
    
    return sorted_users


@frappe.whitelist()
def close_opportunity_todo(todo_name):
    """Mark a ToDo as closed."""
    todo = frappe.get_doc("ToDo", todo_name)
    
    # Check permission
    if todo.allocated_to != frappe.session.user and not frappe.has_permission("ToDo", "write", todo):
        frappe.throw(_("You don't have permission to close this task"))
    
    todo.status = "Closed"
    todo.save(ignore_permissions=True)
    
    return {"status": "success", "message": "Task closed successfully"}


@frappe.whitelist()
def get_opportunity_details(opportunity_name):
    """Get detailed information about an opportunity for the dashboard."""
    opp = frappe.get_doc("Opportunity", opportunity_name)
    
    # Get items
    items = []
    if opp.get("items"):
        for item in opp.items:
            items.append({
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": item.qty,
                "uom": item.uom,
                "description": item.description
            })
    
    # Get assigned engineers
    engineers = []
    if opp.get("custom_resp_eng"):
        for row in opp.custom_resp_eng:
            engineers.append({
                "engineer": row.responsible_engineer,
                "name": frappe.db.get_value("Responsible Engineer", row.responsible_engineer, "eng_name") or row.responsible_engineer
            })
    
    return {
        "name": opp.name,
        "party_name": opp.party_name,
        "status": opp.status,
        "expected_closing": opp.expected_closing,
        "source": opp.source,
        "opportunity_type": opp.opportunity_type,
        "items": items,
        "engineers": engineers,
        "contact_person": opp.contact_person,
        "contact_email": opp.contact_email,
    }
