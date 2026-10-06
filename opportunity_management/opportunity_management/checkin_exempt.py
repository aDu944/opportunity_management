"""
Check-in exemption.

Employees with `custom_checkin_exempt` = 1 (Employee custom field, seeded by
the `seed_checkin_exempt` patch for the four System Managers) are not
required to check in or out. They may still check in voluntarily, but they
get no check-in / check-out reminders, no late-check-in leave and no
auto-checkout.

`frappe` is imported lazily so the pure parts (SQL clause, email matching)
load bench-free in `tests/test_checkin_exempt_pure.py`.

Every helper tolerates the column not existing yet (code pulled, migrate not
run) by treating everyone as non-exempt, and never raises — they are called
from scheduler jobs.
"""

FIELDNAME = "custom_checkin_exempt"

# Fragment for raw reminder queries that alias `tabEmployee` as `e`.
EXEMPT_SQL = "COALESCE(e.custom_checkin_exempt, 0) = 0"

# Users exempted by the seed patch (System Managers who don't punch in/out).
SEED_EXEMPT_USERS = (
    "as@alkhora.com",
    "ali.s@alkhora.com",
    "a.kh@alkhora.com",
    "aziz@alkhora.com",
)


def exempt_sql_clause(has_column: bool) -> str:
    """`" AND <EXEMPT_SQL>"` to append to a WHERE, or "" before migrate."""
    return f" AND {EXEMPT_SQL}" if has_column else ""


def split_found(emails, user_ids):
    """(found, missing) — which of `emails` appear in `user_ids`, matched
    case-insensitively and ignoring surrounding whitespace, order kept."""
    have = {(u or "").strip().lower() for u in user_ids or ()}
    found, missing = [], []
    for e in emails or ():
        key = (e or "").strip().lower()
        if not key:
            continue
        (found if key in have else missing).append(key)
    return found, missing


def has_exempt_column() -> bool:
    import frappe
    try:
        return bool(frappe.db.has_column("Employee", FIELDNAME))
    except Exception:
        return False


def exempt_filter_sql() -> str:
    """WHERE-suffix excluding exempt employees (alias `e`); safe pre-migrate."""
    return exempt_sql_clause(has_exempt_column())


def is_exempt_employee(employee_name) -> bool:
    if not employee_name or not has_exempt_column():
        return False
    import frappe
    try:
        return bool(frappe.db.get_value("Employee", employee_name, FIELDNAME))
    except Exception:
        return False


def is_exempt_user(user) -> bool:
    if not user or not has_exempt_column():
        return False
    import frappe
    try:
        return bool(frappe.db.get_value("Employee", {"user_id": user}, FIELDNAME))
    except Exception:
        return False
