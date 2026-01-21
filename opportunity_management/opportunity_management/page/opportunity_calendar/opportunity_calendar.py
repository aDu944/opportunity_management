import frappe
from frappe import _


@frappe.whitelist()
def get_calendar_events(start, end, filters=None):
    """
    Fetch opportunities for calendar view based on date range and filters
    """
    if isinstance(filters, str):
        import json
        filters = json.loads(filters) if filters else {}

    filters = filters or {}

    # Check which custom fields exist
    meta = frappe.get_meta("Opportunity")
    has_resp_eng = meta.has_field("custom_resp_eng")
    has_urgency = meta.has_field("custom_urgency_level")
    has_closing_date = meta.has_field("custom_closing_date")

    # Base filters
    conditions = ["o.transaction_date >= %(start)s", "o.transaction_date <= %(end)s"]
    values = {"start": start, "end": end}

    # Additional filters
    if filters.get("status"):
        conditions.append("o.status = %(status)s")
        values["status"] = filters["status"]

    if filters.get("opportunity_owner"):
        conditions.append("o.opportunity_owner = %(opportunity_owner)s")
        values["opportunity_owner"] = filters["opportunity_owner"]

    if filters.get("custom_resp_eng") and has_resp_eng:
        conditions.append("o.custom_resp_eng = %(custom_resp_eng)s")
        values["custom_resp_eng"] = filters["custom_resp_eng"]

    if filters.get("urgency_level") and has_urgency:
        conditions.append("o.custom_urgency_level = %(urgency_level)s")
        values["urgency_level"] = filters["urgency_level"]

    where_clause = " AND ".join(conditions)

    # Build dynamic field list
    fields = [
        "o.name as id",
        "o.name as title",
        "o.transaction_date as start",
        "o.transaction_date as end",
        "o.status",
        "o.opportunity_owner",
        "o.opportunity_amount",
        "o.party_name"
    ]

    if has_resp_eng:
        fields.append("o.custom_resp_eng")
    if has_urgency:
        fields.append("o.custom_urgency_level as urgency_level")
    if has_closing_date:
        fields.append("o.custom_closing_date as closing_date")
    else:
        # Use expected_closing as fallback
        fields.append("o.expected_closing as closing_date")

    # Query opportunities
    query = f"""
        SELECT
            {', '.join(fields)}
        FROM
            `tabOpportunity` o
        WHERE
            {where_clause}
        ORDER BY
            o.transaction_date
    """

    opportunities = frappe.db.sql(query, values, as_dict=True)

    # Format events for FullCalendar
    events = []
    for opp in opportunities:
        # Determine color based on urgency level
        color = get_urgency_color(opp.get("urgency_level"))

        # Use closing date if available, otherwise use transaction date
        event_date = opp.get("closing_date") or opp.get("start")

        events.append({
            "id": opp.get("id"),
            "title": f"{opp.get('party_name') or opp.get('id')} - {frappe.format_value(opp.get('opportunity_amount'), {'fieldtype': 'Currency'})}",
            "start": str(event_date),
            "end": str(event_date),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {
                "opportunity_name": opp.get("id"),
                "status": opp.get("status"),
                "owner": opp.get("opportunity_owner"),
                "resp_eng": opp.get("custom_resp_eng"),
                "urgency": opp.get("urgency_level"),
                "amount": opp.get("opportunity_amount"),
                "party": opp.get("party_name"),
                "closing_date": str(opp.get("closing_date")) if opp.get("closing_date") else None
            }
        })

    return events


def get_urgency_color(urgency_level):
    """Return color based on urgency level"""
    color_map = {
        "Urgent": "#dc3545",      # Red
        "High": "#fd7e14",        # Orange
        "Medium": "#ffc107",      # Yellow
        "Low": "#28a745",         # Green
    }
    return color_map.get(urgency_level, "#6c757d")  # Default gray


@frappe.whitelist()
def get_filter_options():
    """Get available filter options for the calendar"""

    # Get unique opportunity owners
    owners = frappe.db.sql("""
        SELECT DISTINCT opportunity_owner
        FROM `tabOpportunity`
        WHERE opportunity_owner IS NOT NULL
        ORDER BY opportunity_owner
    """, as_dict=True)

    # Get unique responsible engineers (check if field exists)
    resp_engs = []
    meta = frappe.get_meta("Opportunity")
    has_resp_eng_field = meta.has_field("custom_resp_eng")

    if has_resp_eng_field:
        try:
            resp_engs = frappe.db.sql("""
                SELECT DISTINCT custom_resp_eng
                FROM `tabOpportunity`
                WHERE custom_resp_eng IS NOT NULL
                ORDER BY custom_resp_eng
            """, as_dict=True)
        except Exception as e:
            frappe.log_error(f"Error fetching responsible engineers: {str(e)}")
            resp_engs = []

    # Get statuses
    statuses = frappe.get_meta("Opportunity").get_field("status").options.split("\n")

    return {
        "owners": [o.opportunity_owner for o in owners],
        "resp_engs": [r.custom_resp_eng for r in resp_engs] if resp_engs else [],
        "statuses": statuses,
        "urgency_levels": ["Urgent", "High", "Medium", "Low"]
    }
