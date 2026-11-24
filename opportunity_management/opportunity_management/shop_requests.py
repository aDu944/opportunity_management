"""
Shop requests in My Opportunities and Team Opportunities (Ahmed, 2026-11-23).

The ALKHORA shop (shop.alkhora.com) keeps its own requests for quotation in its own ERPNext, shop-erp. HQ
assigns a request to people as this ERP assigns an Opportunity to its responsible parties: the people
assigned are emailed it, with its files, and reminded before its closing date. So that "each employee
monitors his opportunities and we monitor team opportunities", the two pages list the shop's requests
assigned to them beside the Opportunities here, marked as from the shop.

Nothing is copied. shop-erp is read live, over the private network, through its read-only feed
(shop_assigned_requests, as the user company-erp@alkhora.com), and kept for a minute. The shop names the
people assigned as it got them from this ERP: a Responsible Party's email, or its number for one with none.

Off until site_config.json has shop_erp_api_key and shop_erp_api_secret (and, if not the defaults,
shop_erp_url = "http://10.0.0.2:8000", shop_erp_host = "shop-erp.local"). While off, or if shop-erp
cannot be reached, the pages list the Opportunities here as before.

The callers ask for shop rows (include_shop=1): the desk pages do; the ESS app will from the release that
can open them, since an older app would try to open a shop row as an Opportunity here.
"""

import hashlib
import json

import frappe
import requests
from frappe.utils import date_diff, getdate, nowdate

FEED_METHOD = "/api/method/shop_assigned_requests"
CACHE_SECONDS = 60
SOURCE = "ALKHORA Shop"


def _config():
    conf = frappe.conf
    key = conf.get("shop_erp_api_key")
    secret = conf.get("shop_erp_api_secret")
    if not key or not secret:
        return None
    return {
        "url": (conf.get("shop_erp_url") or "http://10.0.0.2:8000").rstrip("/"),
        "host": conf.get("shop_erp_host") or "shop-erp.local",
        "auth": f"token {key}:{secret}",
    }


def enabled():
    return _config() is not None


def _fetch(keys, everyone, completed):
    """The shop's requests for these people (or everyone's), from shop-erp; [] when off or unreachable."""
    config = _config()
    if not config or (not keys and not everyone):
        return []
    payload = {
        "keys": json.dumps(sorted(set(keys))),
        "everyone": "1" if everyone else "0",
        "completed": "1" if completed else "0",
    }
    cache_key = "shop_requests:" + hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    cached = frappe.cache().get_value(cache_key)
    if cached is not None:
        return cached
    try:
        response = requests.post(
            config["url"] + FEED_METHOD,
            data=payload,
            headers={"Authorization": config["auth"], "Host": config["host"]},
            timeout=6,
        )
        response.raise_for_status()
        rows = response.json().get("message") or []
    except Exception as error:
        # Kept for the minute too, so a shop-erp that is down does not slow every page by the timeout.
        frappe.logger("shop_requests").warning(f"Shop requests not read: {error}")
        rows = []
    frappe.cache().set_value(cache_key, rows, expires_in_sec=CACHE_SECONDS)
    return rows


def _fields(doctype, wanted):
    meta = frappe.get_meta(doctype)
    return [f for f in wanted if f == "name" or meta.has_field(f)]


def people():
    """Everyone the shop may name, by what it names them with (an email in lower case, or an RP number):
    {key: {"user", "name", "department"}}."""
    employees = {
        e.name: e
        for e in frappe.get_all(
            "Employee",
            filters={"status": "Active"},
            fields=_fields("Employee", ["name", "employee_name", "user_id", "department", "prefered_email", "company_email"]),
        )
    }
    by_user = {e.user_id: e for e in employees.values() if e.get("user_id")}
    index = {}
    if frappe.db.exists("DocType", "Responsible Party"):
        for rp in frappe.get_all(
            "Responsible Party", fields=_fields("Responsible Party", ["name", "display_name", "user_id", "employee", "email"])
        ):
            employee = employees.get(rp.get("employee")) if rp.get("employee") else None
            user = rp.get("user_id") or (employee.user_id if employee else None)
            employee = employee or by_user.get(user)
            info = {
                "user": user,
                "name": rp.get("display_name") or (employee.employee_name if employee else rp.name),
                "department": employee.department if employee else None,
            }
            index[rp.name] = info
            if rp.get("email"):
                index.setdefault(rp.email.strip().lower(), info)
            if user:
                index.setdefault(user.lower(), info)
    for employee in employees.values():
        info = {"user": employee.get("user_id"), "name": employee.employee_name, "department": employee.department}
        for email in (employee.get("user_id"), employee.get("prefered_email"), employee.get("company_email")):
            if email:
                index.setdefault(email.strip().lower(), info)
    return index


def _keys_for(index, users):
    users = {u.lower() for u in users if u}
    keys = set(users)
    for key, info in index.items():
        if info.get("user") and info["user"].lower() in users:
            keys.add(key)
    return keys


def _matches(row, search):
    words = str(search or "").strip().lower().split()
    if not words:
        return True
    text = " ".join(
        [row.get("rfq") or "", row.get("name") or "", row.get("customer") or "", row.get("customer_reference") or ""]
        + [f"{i.get('item_code') or ''} {i.get('item_name') or ''}" for i in row.get("items") or []]
    ).lower()
    return all(word in text for word in words)


def _row(shop, index, completed, today):
    closing = shop.get("closing_on")
    days = date_diff(getdate(closing), today) if closing else None
    if completed:
        urgency = "completed"
    elif days is None:
        urgency = "no_closing_date"
    elif days < 0:
        urgency = "overdue"
    elif days == 0:
        urgency = "due_today"
    elif days == 1:
        urgency = "critical"
    elif days <= 3:
        urgency = "high"
    elif days <= 7:
        urgency = "medium"
    else:
        urgency = "low"
    if days is None:
        color, label = "gray", "No closing date"
    elif days < 0:
        color, label = "red", f"Overdue by {abs(days)} days"
    elif days == 0:
        color, label = "red", "Due today"
    else:
        color = "orange" if days <= 3 else ("yellow" if days <= 7 else "green")
        label = f"{days} days remaining"

    assignees = []
    for key in shop.get("assignees") or []:
        info = index.get(key.lower() if "@" in key else key) or {}
        assignees.append({"user": info.get("user") or key, "employee": info.get("name") or key, "department": info.get("department")})

    rfq = shop.get("rfq") or shop.get("name")
    return {
        "todo_name": None,
        "opportunity": rfq,
        "opportunity_name": rfq,
        "name": rfq,
        "customer": shop.get("customer"),
        "party_name": shop.get("customer"),
        "tender_no": None,
        "tender_title": None,
        "customer_reference": shop.get("customer_reference") or None,
        "closing_date": closing,
        "expected_closing": closing,
        "days_remaining": days,
        "urgency": urgency,
        "items": shop.get("items") or [],
        "status": shop.get("stage"),
        "opportunity_status": shop.get("stage"),
        "has_quotation": shop.get("stage") != "Open",
        "has_draft_quotation": False,
        "quotation_name": None,
        "status_color": color,
        "status_label": label,
        "priority": None,
        "assigned_by": shop.get("entered_by") or None,
        "assigned_date": shop.get("created"),
        "creation": shop.get("created"),
        "source": SOURCE,
        "opportunity_type": "Shop Request",
        "assignees": assignees,
        "assigned_users": [a["user"] for a in assignees if a.get("user")],
        "is_shop": 1,
        "shop_rfq": rfq,
        "shop_record": shop.get("name"),
        "shop_declined": shop.get("declined") or 0,
    }


def personal_rows(user, include_completed=False, search=None):
    """The shop's requests assigned to this user, as My Opportunities rows."""
    if not enabled():
        return []
    index = people()
    today = getdate(nowdate())
    shop_rows = _fetch(_keys_for(index, [user]), False, include_completed)
    return [_row(r, index, include_completed, today) for r in shop_rows if _matches(r, search)]


def team_rows(team=None, include_completed=False, search=None):
    """The shop's requests assigned to anyone in the team (a department), or to anyone at all for no team or
    "All Teams", as Team Opportunities rows."""
    if not enabled():
        return []
    index = people()
    today = getdate(nowdate())
    whole = not team or team == "All Teams"
    if whole:
        shop_rows = _fetch([], True, include_completed)
    else:
        keys = [key for key, info in index.items() if info.get("department") == team]
        shop_rows = _fetch(keys, False, include_completed)
    rows = []
    for shop in shop_rows:
        if not _matches(shop, search):
            continue
        row = _row(shop, index, include_completed, today)
        if not whole and not any(a.get("department") == team for a in row["assignees"]):
            continue
        rows.append(row)
    return rows


_URGENCY_RANK = {
    "no_closing_date": 0,
    "due_today": 1, "critical": 2, "high": 3, "medium": 4, "low": 5,
    "overdue": 6, "completed": 7, "unknown": 8,
}


def merge(rows, shop_rows, include_completed=False):
    """The Opportunities here and the shop's requests in one list, in the pages' order: open — undated first,
    then nearest closing, overdue last; completed — latest closing first."""
    merged = list(rows) + list(shop_rows)
    if include_completed:
        from datetime import date

        def completed_key(row):
            day = row.get("closing_date") or row.get("expected_closing")
            try:
                return getdate(day) if day else date(1, 1, 1)
            except Exception:
                return date(1, 1, 1)

        merged.sort(key=completed_key, reverse=True)
    else:

        def open_key(row):
            days = row.get("days_remaining")
            if row.get("urgency") == "overdue" and days is not None:
                second = -days
            else:
                second = days if days is not None else 9999
            return (_URGENCY_RANK.get(row.get("urgency"), 99), second)

        merged.sort(key=open_key)
    return merged


def add_to_employee_stats(stats, team=None):
    """The team member cards with the shop's requests counted in, by the cards' own rule: open, with a closing
    date that has not passed, once for each person assigned. Each card also says how many are the shop's
    (shop_open). Someone with only shop requests gets a card too, if they are in the team."""
    if not enabled():
        return stats
    counts = {}
    for row in team_rows(team, False):
        days = row.get("days_remaining")
        if days is None or days < 0:
            continue
        for person in row["assignees"]:
            user = person.get("user")
            if not user or "@" not in user:
                continue
            if team and team != "All Teams" and person.get("department") != team:
                continue
            if user not in counts:
                counts[user] = {"count": 0, "department": person.get("department"), "name": person.get("employee")}
            counts[user]["count"] += 1
    if not counts:
        return stats
    cards = [dict(card) for card in stats]
    by_user = {card["user"]: card for card in cards}
    for user, found in counts.items():
        card = by_user.get(user)
        if card is None:
            card = {
                "user": user,
                "employee_name": frappe.db.get_value("User", user, "full_name") or found["name"] or user,
                "department": found["department"],
                "open_opportunities": 0,
            }
            cards.append(card)
        card["open_opportunities"] = (card.get("open_opportunities") or 0) + found["count"]
        card["shop_open"] = found["count"]
    cards.sort(key=lambda card: card["open_opportunities"], reverse=True)
    return cards

