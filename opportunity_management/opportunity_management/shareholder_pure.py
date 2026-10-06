"""
Pure helpers behind the shareholder app endpoints (shareholder_contract.md).

No `frappe` import: everything here works on plain values so the bench-free
tests (`tests/test_shareholder_pure.py`) can load this file straight off disk.
`shareholder_finance` / `shareholder_api` do the querying and call in here
for the date maths, bucketing, labels and JSON-safe conversion.
"""

import datetime
import re
from decimal import Decimal

AGING_BUCKETS = ("0-30", "31-60", "61-90", "90+")

# Statuses the mobile client renders as tags. Anything else (the
# "… and Discounted" variants, Internal Transfer) folds into one of these.
INVOICE_STATUSES = ("Paid", "Unpaid", "Overdue", "Partly Paid", "Return", "Credit Note Issued")


# ── value conversion ─────────────────────────────────────────────────────────

def num(value, digits=2) -> float:
    """Decimal / str / None → float, rounded. Never raises."""
    if value is None or value == "":
        return 0.0
    try:
        if isinstance(value, Decimal):
            value = float(value)
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def to_date(value):
    """date / datetime / 'YYYY-MM-DD…' → date, or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def date_str(value):
    d = to_date(value)
    return d.isoformat() if d else None


# ── dates ────────────────────────────────────────────────────────────────────

def month_label(d) -> str:
    d = to_date(d)
    return f"{d.year:04d}-{d.month:02d}"


def month_start(d):
    d = to_date(d)
    return d.replace(day=1)


def add_months(d, months):
    """`d` shifted by whole months, day clamped to the target month's end."""
    d = to_date(d)
    idx = d.year * 12 + (d.month - 1) + months
    year, month = divmod(idx, 12)
    month += 1
    day = min(d.day, _days_in_month(year, month))
    return datetime.date(year, month, day)


def _days_in_month(year, month):
    nxt = datetime.date(year + (month // 12), (month % 12) + 1, 1)
    return (nxt - datetime.timedelta(days=1)).day


def previous_month_end(d):
    """Last day of the month before `d`'s month."""
    return month_start(d) - datetime.timedelta(days=1)


def same_day_last_month(d):
    """`d` one month back, clamped (31 Mar → 28/29 Feb)."""
    return add_months(d, -1)


def six_month_labels(today, count=6):
    """['2026-05', …, '2026-10'] — oldest → current, `count` items."""
    start = month_start(today)
    return [month_label(add_months(start, -i)) for i in range(count - 1, -1, -1)]


def series_start(today, count=6):
    """First day of the oldest month in `six_month_labels`."""
    return add_months(month_start(today), -(count - 1))


# ── maths ────────────────────────────────────────────────────────────────────

def delta_pct(current, previous):
    """Percent change from `previous` to `current`, one decimal.

    None when there is no meaningful base (previous == 0): the client shows
    a dash rather than an infinite percentage. Measured against |previous| so
    a negative base still reads in the right direction.
    """
    cur, prev = num(current), num(previous)
    if prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100.0, 1)


def aging_bucket(due_date, today) -> str:
    """Bucket of an outstanding amount by days past due.

    Not yet due (or no due date) counts as "0-30" — the screen shows four
    buckets only and a current balance is the least worrying one.
    """
    due, ref = to_date(due_date), to_date(today)
    if due is None or ref is None:
        return AGING_BUCKETS[0]
    days = (ref - due).days
    if days <= 30:
        return "0-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def aging_summary(rows, today):
    """rows: [{due_date, amount}] → [{bucket, amount}] in AGING_BUCKETS order."""
    totals = dict.fromkeys(AGING_BUCKETS, 0.0)
    for r in rows or []:
        totals[aging_bucket(r.get("due_date"), today)] += num(r.get("amount"))
    return [{"bucket": b, "amount": num(totals[b])} for b in AGING_BUCKETS]


def top_parties(rows, limit=5):
    """rows: [{party, party_name, due_date, amount}] (several per party) →
    the `limit` largest parties: [{party, party_name, outstanding, oldest_due_date}]."""
    by_party = {}
    for r in rows or []:
        party = r.get("party")
        if not party:
            continue
        cur = by_party.setdefault(
            party,
            {"party": party, "party_name": r.get("party_name") or party,
             "outstanding": 0.0, "oldest_due_date": None},
        )
        cur["outstanding"] += num(r.get("amount"))
        due = to_date(r.get("due_date"))
        old = to_date(cur["oldest_due_date"])
        if due and (old is None or due < old):
            cur["oldest_due_date"] = due
    out = sorted(by_party.values(), key=lambda p: (-p["outstanding"], str(p["party"])))
    for p in out:
        p["outstanding"] = num(p["outstanding"])
        p["oldest_due_date"] = date_str(p["oldest_due_date"])
    return out[: max(0, int(limit))]


def build_series(rows, labels):
    """rows: [{month:'YYYY-MM', revenue, expenses}] (any order, gaps allowed)
    → one entry per label, zero-filled, oldest → current."""
    by_month = {}
    for r in rows or []:
        m = str(r.get("month") or "")
        cur = by_month.setdefault(m, {"revenue": 0.0, "expenses": 0.0})
        cur["revenue"] += num(r.get("revenue"))
        cur["expenses"] += num(r.get("expenses"))
    return [
        {"month": m,
         "revenue": num(by_month.get(m, {}).get("revenue")),
         "expenses": num(by_month.get(m, {}).get("expenses"))}
        for m in labels
    ]


def indicative_split(profit, owners):
    """owners: [{shareholder, title, share_pct, user}] → same rows plus
    `indicative` = profit × share_pct / 100. Indicative only: no reserves,
    tax or prior distributions are taken into account."""
    base = num(profit)
    out = []
    for o in owners or []:
        pct = num(o.get("share_pct"), 4)
        row = dict(o)
        row["share_pct"] = pct
        row["indicative"] = num(base * pct / 100.0)
        out.append(row)
    return out


# ── labels ───────────────────────────────────────────────────────────────────

def invoice_status_label(status, outstanding=0, due_date=None, today=None, is_return=0):
    """Map a submitted Sales Invoice's status onto INVOICE_STATUSES."""
    s = str(status or "").strip()
    if s in INVOICE_STATUSES:
        return s
    if is_return:
        return "Return"
    for base in ("Partly Paid", "Overdue", "Unpaid"):
        if s.startswith(base):
            return base
    out = num(outstanding)
    if out <= 0:
        return "Paid"
    due, ref = to_date(due_date), to_date(today)
    if due and ref and due < ref:
        return "Overdue"
    return "Unpaid"


_NUMBER_PREFIX = re.compile(r"^\s*[\d.\-/]+\s*-\s*")


def account_label(account, account_name=None, abbr=None):
    """'1110 - Cash Box - AK' → 'Cash Box'. Prefers `account_name` (which
    ERPNext already stores without the number) and still strips a number
    prefix / company suffix in case someone typed them into the name."""
    text = str(account_name or account or "").strip()
    if abbr:
        suffix = f" - {abbr}"
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip()
    text = _NUMBER_PREFIX.sub("", text, count=1).strip()
    return text or str(account or "")


def totals_by_currency(accounts):
    """accounts: [{currency, balance}] → [{currency, total}] sorted by currency,
    never converted between currencies."""
    totals = {}
    for a in accounts or []:
        cur = a.get("currency") or ""
        totals[cur] = totals.get(cur, 0.0) + num(a.get("balance"))
    return [{"currency": c, "total": num(t)} for c, t in sorted(totals.items())]

