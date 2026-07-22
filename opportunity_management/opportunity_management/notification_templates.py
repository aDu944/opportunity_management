"""
FCM notification templates.

Every builder returns a `(title, body, data)` tuple ready to hand straight
to `send_fcm`. All follow the same shape so the notification tray reads
consistently:

    title:  [emoji] [Arabic action] • [English action]        (≤ 40 chars)
    body:   Arabic sentence with key numbers/names.
            English sentence with same info.
            — بواسطة {name} • by {name}

The trailing "by X" line always names the doc's creator (Frappe .owner
→ User.full_name). Bodies are trimmed to iOS-friendly lengths. The
`data` payload always carries {doctype, name} so tapping the push can
deep-link straight to the doc.
"""

import frappe


# ── Common helpers ────────────────────────────────────────────────────────────

def _creator_display(doc) -> str:
    """Full name of the User who created `doc`, falling back to their
    user_id (email) if no full_name is set."""
    owner = getattr(doc, "owner", None) or (doc.get("owner") if hasattr(doc, "get") else None)
    if not owner:
        return ""
    full = frappe.db.get_value("User", owner, "full_name")
    return full or owner


def _by_line(doc) -> str:
    creator = _creator_display(doc)
    return f"\n— بواسطة {creator} • by {creator}" if creator else ""


def _action_by_line(doc, ar_verb: str, en_verb: str, use_modified: bool = True) -> str:
    """Return the trailer line naming who took the action (submitted/approved/rejected).

    Uses doc.modified_by by default — for transition events (approve/reject/submit)
    the last modifier IS the actor. Set use_modified=False to name the original owner."""
    user_id = None
    if use_modified:
        user_id = getattr(doc, "modified_by", None) or (doc.get("modified_by") if hasattr(doc, "get") else None)
    if not user_id:
        user_id = getattr(doc, "owner", None) or (doc.get("owner") if hasattr(doc, "get") else None)
    if not user_id:
        return ""
    full = frappe.db.get_value("User", user_id, "full_name") or user_id
    return f"\n— {ar_verb} {full} • {en_verb} by {full}"


def _money(amount, currency) -> str:
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return f"{amount} {currency or ''}".strip()
    ccy = (currency or "").strip()
    # Thousand-separated integer, no decimals — cleaner in a push.
    if ccy:
        return f"{amt:,.0f} {ccy}"
    return f"{amt:,.0f}"


def _customer_of(doc) -> str:
    return doc.get("customer_name") or doc.get("customer") or doc.get("party_name") or ""


def _supplier_of(doc) -> str:
    return doc.get("supplier_name") or doc.get("supplier") or doc.get("party_name") or ""


# ── SALES ─────────────────────────────────────────────────────────────────────

def quotation_created(doc):
    total = _money(doc.get("grand_total"), doc.get("currency"))
    customer = _customer_of(doc)
    return (
        "📄 عرض سعر جديد • New Quotation",
        (
            f"عرض السعر {doc.name} — {customer} — {total}\n"
            f"Quotation {doc.name} — {customer} — {total}"
        ) + _by_line(doc),
        {"doctype": "Quotation", "name": doc.name},
    )


def quotation_submitted(doc):
    total = _money(doc.get("grand_total"), doc.get("currency"))
    customer = _customer_of(doc)
    return (
        "✅ اعتماد عرض السعر • Quotation Submitted",
        (
            f"اعتُمد عرض السعر {doc.name} — {customer} — {total}\n"
            f"Quotation {doc.name} submitted — {customer} — {total}"
        ) + _by_line(doc),
        {"doctype": "Quotation", "name": doc.name},
    )


def quotation_lost(doc):
    customer = _customer_of(doc)
    return (
        "❌ خسارة عرض السعر • Quotation Lost",
        (
            f"عرض السعر {doc.name} فُقد — {customer}\n"
            f"Quotation {doc.name} lost — {customer}"
        ) + _by_line(doc),
        {"doctype": "Quotation", "name": doc.name},
    )


def sales_order_submitted(doc):
    total = _money(doc.get("grand_total"), doc.get("currency"))
    customer = _customer_of(doc)
    return (
        "🎯 طلب مبيعات جديد • New Sales Order",
        (
            f"طلب المبيعات {doc.name} — {customer} — {total}\n"
            f"Sales Order {doc.name} — {customer} — {total}"
        ) + _by_line(doc),
        {"doctype": "Sales Order", "name": doc.name},
    )


def sales_invoice_submitted(doc):
    total = _money(doc.get("grand_total"), doc.get("currency"))
    customer = _customer_of(doc)
    return (
        "🧾 فاتورة جديدة • New Invoice",
        (
            f"فاتورة {doc.name} — {customer} — {total}\n"
            f"Invoice {doc.name} — {customer} — {total}"
        ) + _by_line(doc),
        {"doctype": "Sales Invoice", "name": doc.name},
    )


# ── FINANCE ───────────────────────────────────────────────────────────────────

def journal_entry_submitted(doc):
    total = _money(doc.get("total_debit"), "")
    ref = (doc.get("cheque_no") or "").strip()
    ref_bit = f" — {ref}" if ref else ""
    return (
        "📒 قيد يومي مُقدّم • JE Submitted",
        (
            f"القيد {doc.name}{ref_bit} — {total}\n"
            f"Journal Entry {doc.name}{ref_bit} — {total} submitted"
        ) + _action_by_line(doc, "قدّمه", "Submitted"),
        {"doctype": "Journal Entry", "name": doc.name},
    )


def payment_received(doc):
    currency = doc.get("paid_to_account_currency") or doc.get("paid_from_account_currency")
    amt = _money(doc.get("paid_amount"), currency)
    party = _customer_of(doc)
    return (
        "💵 دفعة من عميل • Customer Payment",
        (
            f"استلمت {amt} من {party}\n"
            f"Received {amt} from {party}"
        ) + _by_line(doc),
        {"doctype": "Payment Entry", "name": doc.name},
    )


def payment_made(doc):
    currency = doc.get("paid_from_account_currency") or doc.get("paid_to_account_currency")
    amt = _money(doc.get("paid_amount"), currency)
    party = _supplier_of(doc)
    return (
        "💸 دفعة لمورد • Supplier Payment",
        (
            f"دُفع {amt} إلى {party}\n"
            f"Paid {amt} to {party}"
        ) + _by_line(doc),
        {"doctype": "Payment Entry", "name": doc.name},
    )


# ── HR ────────────────────────────────────────────────────────────────────────

def leave_request_created(doc):
    emp_name = frappe.db.get_value("Employee", doc.employee, "employee_name") or doc.employee
    return (
        "🗓 طلب إجازة جديد • New Leave Request",
        (
            f"{emp_name} طلب إجازة من {doc.from_date} إلى {doc.to_date} — {doc.leave_type}\n"
            f"{emp_name} requested leave {doc.from_date} → {doc.to_date} — {doc.leave_type}"
        ) + _by_line(doc),
        {"doctype": "Leave Application", "name": doc.name, "screen": "leave"},
    )


def leave_approved(doc):
    days = doc.get("total_leave_days") or ""
    days_bit = f" — {days} يوم / days" if days else ""
    return (
        "✅ تمت الموافقة على إجازتك",
        (
            f"من {doc.from_date} إلى {doc.to_date}{days_bit}\n"
            f"{doc.from_date} → {doc.to_date}{days_bit}"
        ) + _by_line(doc),
        {"doctype": "Leave Application", "name": doc.name, "screen": "leave"},
    )


def leave_rejected(doc):
    return (
        "❌ إجازتك مرفوضة • Leave Rejected",
        (
            f"طلب الإجازة من {doc.from_date} إلى {doc.to_date} لم يُعتمد.\n"
            f"Leave request {doc.from_date} → {doc.to_date} was rejected."
        ) + _by_line(doc),
        {"doctype": "Leave Application", "name": doc.name, "screen": "leave"},
    )


def expense_claim_created(doc):
    emp_name = frappe.db.get_value("Employee", doc.employee, "employee_name") or doc.employee
    amt = _money(doc.get("total_claimed_amount"), doc.get("currency"))
    return (
        "🧾 مطالبة مصروف جديدة • New Expense Claim",
        (
            f"{emp_name} — {amt}\n"
            f"{emp_name} submitted an expense of {amt}"
        ) + _by_line(doc),
        {"doctype": "Expense Claim", "name": doc.name, "screen": "expenses"},
    )


def expense_approved(doc):
    amt = _money(doc.get("total_claimed_amount"), doc.get("currency"))
    return (
        "✅ تمت الموافقة على مصروفك",
        f"{amt}" + _by_line(doc),
        {"doctype": "Expense Claim", "name": doc.name, "screen": "expenses"},
    )


def expense_rejected(doc):
    amt = _money(doc.get("total_claimed_amount"), doc.get("currency"))
    return (
        "❌ مصروفك مرفوض • Expense Rejected",
        f"{amt}" + _by_line(doc),
        {"doctype": "Expense Claim", "name": doc.name, "screen": "expenses"},
    )


def salary_slip_ready(doc):
    period = doc.get("month_name") or str(doc.get("start_date") or "")
    net = _money(doc.get("net_pay"), doc.get("currency"))
    return (
        "💰 قسيمة راتبك جاهزة • Payslip Ready",
        f"شهر {period} — {net}" + _by_line(doc),
        {"doctype": "Salary Slip", "name": doc.name, "screen": "payslips"},
    )


# ── OPERATIONS ────────────────────────────────────────────────────────────────

def task_assigned(doc):
    subject = (doc.get("description") or doc.get("subject") or "New task")
    # ToDo.description is often HTML — strip crudely to keep the push clean.
    import re
    subject = re.sub(r"<[^>]+>", "", subject).strip()[:140]
    return (
        "📌 مهمة جديدة • New Task",
        subject + _by_line(doc),
        {"doctype": "ToDo", "name": doc.name},
    )


def material_request_submitted(doc):
    n_items = len(doc.get("items") or [])
    purpose = doc.get("material_request_type") or ""
    purpose_bit = f" — {purpose}" if purpose else ""
    return (
        "📦 طلب مواد جديد • Material Request",
        (
            f"{doc.name}{purpose_bit} — {n_items} صنف/items\n"
            f"Material Request {doc.name}{purpose_bit} — {n_items} items"
        ) + _by_line(doc),
        {"doctype": "Material Request", "name": doc.name},
    )


def delivery_note_submitted(doc):
    customer = _customer_of(doc)
    return (
        "🚚 وصل تسليم • Delivery Issued",
        (
            f"وصل {doc.name} — {customer}\n"
            f"Delivery {doc.name} — {customer}"
        ) + _by_line(doc),
        {"doctype": "Delivery Note", "name": doc.name},
    )


def purchase_order_submitted(doc):
    total = _money(doc.get("grand_total"), doc.get("currency"))
    supplier = _supplier_of(doc)
    return (
        "📦 طلب شراء جديد • New Purchase Order",
        (
            f"طلب الشراء {doc.name} — {supplier} — {total}\n"
            f"Purchase Order {doc.name} — {supplier} — {total}"
        ) + _by_line(doc),
        {"doctype": "Purchase Order", "name": doc.name},
    )


def project_created(doc):
    proj_name = (doc.get("project_name") or doc.name).strip()
    customer = _customer_of(doc)
    ar = f"مشروع {doc.name} — {proj_name}" + (f" — {customer}" if customer else "")
    en = f"Project {doc.name} — {proj_name}" + (f" — {customer}" if customer else "")
    return (
        "🚀 مشروع جديد • New Project",
        f"{ar}\n{en}" + _by_line(doc),
        {"doctype": "Project", "name": doc.name},
    )


def journal_entry_approved(doc):
    total = _money(doc.get("total_debit"), "")
    ref = (doc.get("cheque_no") or "").strip()
    ref_bit = f" — {ref}" if ref else ""
    return (
        "✅ قيد يومي معتمد • JE Approved",
        (
            f"القيد {doc.name}{ref_bit} — {total} تمت الموافقة\n"
            f"Journal Entry {doc.name}{ref_bit} — {total} approved"
        ) + _action_by_line(doc, "اعتمده", "Approved"),
        {"doctype": "Journal Entry", "name": doc.name},
    )


def journal_entry_rejected(doc):
    total = _money(doc.get("total_debit"), "")
    ref = (doc.get("cheque_no") or "").strip()
    ref_bit = f" — {ref}" if ref else ""
    return (
        "❌ قيد يومي مرفوض • JE Rejected",
        (
            f"القيد {doc.name}{ref_bit} — {total} تم رفضه\n"
            f"Journal Entry {doc.name}{ref_bit} — {total} rejected"
        ) + _action_by_line(doc, "رفضه", "Rejected"),
        {"doctype": "Journal Entry", "name": doc.name},
    )
