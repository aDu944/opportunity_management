"""
Pure helpers for the employee-expenses endpoints (`expenses_api.py`).

No `frappe` import: validation, Journal Entry construction, history
filtering, balance maths and receipt checks live here so they can be tested
without a bench (`tests/test_expenses_pure.py`). Every validation failure is
a `ValueError` whose message is user-facing; the API layer re-raises it as a
417 with `frappe.throw`.
"""

import datetime
import json
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_REMARK = 500
MAX_ROWS = 50
MAX_RECEIPT_BYTES = 10 * 1024 * 1024
DEFAULT_COST_CENTER = "1001 - Main - AK"
DEFAULT_CURRENCY = "IQD"
RECEIPT_EXTENSIONS = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".heic": "image/heic",
    ".heif": "image/heif", ".pdf": "application/pdf",
}


# ── scalars ──────────────────────────────────────────────────────────────────

def to_date(value):
    """`YYYY-MM-DD` (or a date/datetime) → date; ValueError otherwise."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError("Posting date is invalid") from None


def validate_posting_date(value, today):
    d = to_date(value)
    if d > to_date(today):
        raise ValueError("Posting date cannot be in the future")
    return d


def money(value):
    """Amount rounded to 2 dp as float; must be > 0."""
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        raise ValueError("Amount is invalid") from None
    if not amount.is_finite():
        raise ValueError("Amount is invalid")
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    return float(amount)


def clean_text(value, label="Remark"):
    text = str(value or "").strip()
    if len(text) > MAX_REMARK:
        raise ValueError(f"{label} is longer than {MAX_REMARK} characters")
    return text


def clean_name(value):
    """Link values (project, opportunity, cost centre): trimmed string."""
    return str(value or "").strip()


def like_pattern(q):
    """`%q%` with LIKE wildcards in `q` escaped (pass as a bound value)."""
    text = str(q or "").strip()[:100]
    text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{text}%"


def clamp_limit(value, default=200, maximum=500):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, maximum))


# ── create ───────────────────────────────────────────────────────────────────

def parse_rows(raw):
    """`rows` arrives as JSON text (form post) or as a list already."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raise ValueError("Expense rows are invalid") from None
    if not isinstance(raw, list) or not raw:
        raise ValueError("Add at least one expense row")
    if len(raw) > MAX_ROWS:
        raise ValueError(f"At most {MAX_ROWS} expense rows per claim")
    if not all(isinstance(r, dict) for r in raw):
        raise ValueError("Expense rows are invalid")
    return raw


def normalise_rows(raw_rows, allowed_accounts, default_cost_center):
    """Validate each row → [{account, amount, cost_center, project,
    opportunity, remark}]. `allowed_accounts` is the set of accounts of the
    active expense categories; anything else is refused. Exactly one of
    project / opportunity per row, as the app enforces."""
    allowed = {a for a in (allowed_accounts or ()) if a}
    out = []
    for i, r in enumerate(parse_rows(raw_rows), start=1):
        account = clean_name(r.get("account"))
        if not account or account not in allowed:
            raise ValueError(f"Row {i}: choose one of the expense categories")
        project = clean_name(r.get("project"))
        opportunity = clean_name(r.get("opportunity"))
        if bool(project) == bool(opportunity):
            raise ValueError(f"Row {i}: choose a project or an opportunity")
        out.append({
            "account": account,
            "amount": money(r.get("amount")),
            "cost_center": clean_name(r.get("cost_center")) or default_cost_center,
            "project": project,
            "opportunity": opportunity,
            "remark": clean_text(r.get("remark"), f"Row {i} remark"),
        })
    return out


def total_amount(rows):
    total = sum(Decimal(str(r["amount"])) for r in rows)
    return float(total.quantize(Decimal("0.01")))


def combined_remark(rows, remark=None):
    """The JE `user_remark`: an explicit `remark` if given, else the row
    remarks joined with " | " (what the app posts today)."""
    explicit = clean_text(remark)
    if explicit:
        return explicit
    return " | ".join(r["remark"] for r in rows if r["remark"])


def build_journal_entry(company, posting_date, payable_account, employee,
                        cost_center, rows, remark=None):
    """The Journal Entry dict, line for line what the app POSTs today: one
    debit line per row, one credit line on the payable account with the
    employee as party. Draft only (no docstatus key)."""
    accounts = []
    for r in rows:
        line = {
            "account": r["account"],
            "debit_in_account_currency": r["amount"],
            "credit_in_account_currency": 0,
            "cost_center": r["cost_center"] or cost_center,
        }
        if r["project"]:
            line["project"] = r["project"]
        if r["opportunity"]:
            line["custom_opportunity"] = r["opportunity"]
        if r["remark"]:
            line["user_remark"] = r["remark"]
        accounts.append(line)
    accounts.append({
        "account": payable_account,
        "debit_in_account_currency": 0,
        "credit_in_account_currency": total_amount(rows),
        "party_type": "Employee",
        "party": employee,
        "cost_center": cost_center,
    })
    return {
        "doctype": "Journal Entry",
        "voucher_type": "Journal Entry",
        "posting_date": to_date(posting_date).isoformat(),
        "company": company,
        "user_remark": combined_remark(rows, remark),
        "accounts": accounts,
    }


# ── read side ────────────────────────────────────────────────────────────────

def history_rows(rows, payable_account, employee):
    """Only the caller's lines on the payable account, in the app's shape."""
    keys = ("name", "posting_date", "user_remark", "docstatus", "account", "party",
            "debit_in_account_currency", "credit_in_account_currency", "account_currency")
    out = []
    for r in rows or ():
        if r.get("account") != payable_account or r.get("party") != employee:
            continue
        row = {k: r.get(k) for k in keys}
        d = row["posting_date"]
        if isinstance(d, (datetime.date, datetime.datetime)):
            row["posting_date"] = to_date(d).isoformat()
        row["user_remark"] = row["user_remark"] or ""
        row["docstatus"] = int(row["docstatus"] or 0)
        for k in ("debit_in_account_currency", "credit_in_account_currency"):
            row[k] = float(row[k] or 0)
        out.append(row)
    return out


def balance(credit, debit):
    """Positive → the company owes the employee."""
    value = Decimal(str(credit or 0)) - Decimal(str(debit or 0))
    return float(value.quantize(Decimal("0.01")))


# ── receipts ─────────────────────────────────────────────────────────────────

def _sniff(head):
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG"):
        return "image"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image"
    if head[4:8] == b"ftyp":
        return "image"  # HEIC / HEIF
    return None


def check_receipt(filename, content, max_bytes=MAX_RECEIPT_BYTES):
    """Image or PDF, by extension AND magic bytes, ≤ `max_bytes`.
    Returns a safe file name."""
    if not content:
        raise ValueError("The receipt file is empty")
    if len(content) > max_bytes:
        raise ValueError(f"Receipt exceeds {max_bytes // (1024 * 1024)} MB")
    base = os.path.basename(str(filename or "").replace("\\", "/")).strip()
    ext = os.path.splitext(base)[1].lower()
    if ext not in RECEIPT_EXTENSIONS:
        raise ValueError("Receipts must be an image or a PDF")
    kind = _sniff(bytes(content[:16]))
    if kind is None or (kind == "pdf") != (ext == ".pdf"):
        raise ValueError("Receipts must be an image or a PDF")
    stem = "".join(c for c in os.path.splitext(base)[0] if c.isalnum() or c in "-_")
    return f"{(stem or 'receipt')[:80]}{ext}"


def receipt_limit_bytes(setting_mb):
    """The ESS setting narrows the 10 MB cap; it never widens it."""
    try:
        mb = float(setting_mb or 0)
    except (TypeError, ValueError):
        mb = 0
    if mb <= 0:
        return MAX_RECEIPT_BYTES
    return min(MAX_RECEIPT_BYTES, int(mb * 1024 * 1024))
