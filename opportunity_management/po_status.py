"""
Custom Purchase Order status tracking based on:
  - Delivery: ERPNext's per_received (quantity-based, all items)
  - Payment: all linked Purchase Invoices fully paid (outstanding_amount == 0)

State machine (custom_delivery_payment_status):
    per_received | invoices fully paid | status
    -----------  | ------------------- | -------------------------
    0            | no invoices         | Open
    0            | yes (all paid)      | Paid — Awaiting Delivery
    100          | no or not all paid  | Received — Payment Due
    100          | yes (all paid)      | Completed
    other        | any                 | In Progress

Cancelled POs (docstatus=2) get no status (kept blank).
Draft POs (docstatus=0) also blank — status only meaningful post-submit.
"""
from __future__ import annotations

import frappe

STATUS_FIELD = "custom_delivery_payment_status"

STATUS_DRAFT = "Draft"
STATUS_OPEN = "Open"
STATUS_ON_HOLD = "On Hold"
STATUS_IN_PROGRESS = "In Progress"
STATUS_RECEIVED_PAYMENT_DUE = "Received — Payment Due"
STATUS_PAID_AWAITING_DELIVERY = "Paid — Awaiting Delivery"
STATUS_SHIPPED = "Shipped"
STATUS_COMPLETED = "Completed"
STATUS_CLOSED = "Closed"
STATUS_CANCELLED = "Cancelled"

ALL_STATUSES = [
    "",
    STATUS_DRAFT,
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
    STATUS_RECEIVED_PAYMENT_DUE,
    STATUS_PAID_AWAITING_DELIVERY,
    STATUS_SHIPPED,
    STATUS_COMPLETED,
    STATUS_CANCELLED,
]

PAID_TOLERANCE = 0.01  # ignore tiny rounding cents


def compute_status(po_name: str) -> str:
    """Compute the custom_delivery_payment_status value for a Purchase Order.
    Read-only — never writes. Callers must persist via set_status().
    """
    po = frappe.db.get_value(
        "Purchase Order", po_name,
        ["docstatus", "per_received", "status"],
        as_dict=True,
    )
    if not po:
        return ""
    if po.docstatus == 0:
        return STATUS_DRAFT
    if po.docstatus == 2:
        return STATUS_CANCELLED
    # Native ERPNext Close/Hold take precedence over auto-computed states
    if po.status == "Closed":
        return STATUS_CLOSED
    if po.status == "On Hold":
        return STATUS_ON_HOLD

    per_received = float(po.per_received or 0)

    invoice_rows = frappe.db.sql(
        """
        SELECT DISTINCT pi.name, pi.outstanding_amount
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pii.purchase_order = %s AND pi.docstatus = 1
        """,
        (po_name,),
        as_dict=True,
    )

    if invoice_rows:
        billed_and_paid = all(
            (r.outstanding_amount or 0) <= PAID_TOLERANCE for r in invoice_rows
        )
    else:
        billed_and_paid = False

    # Full delivery + full payment
    if per_received >= 100 and billed_and_paid:
        return STATUS_COMPLETED

    # Fully received but not fully paid
    if per_received >= 100 and not billed_and_paid:
        return STATUS_RECEIVED_PAYMENT_DUE

    # Goods still en route — active Shipping (In Transit) exists AND no
    # Purchase Receipt of any docstatus (draft counts as "someone's already
    # processing the receipt" → not really Shipped anymore).
    if per_received == 0 and _has_shipping_in_transit(po_name) and not _has_any_pr(po_name):
        return STATUS_SHIPPED

    # Fully paid but nothing received yet
    if per_received == 0 and billed_and_paid:
        return STATUS_PAID_AWAITING_DELIVERY

    # Nothing done at all
    if per_received == 0 and not invoice_rows:
        return STATUS_OPEN

    # Anything else is partial
    return STATUS_IN_PROGRESS


def _has_any_pr(po_name: str) -> bool:
    """Any Purchase Receipt (draft OR submitted, ignoring cancelled) linked
    to this PO. Draft counts because "receipt is being processed" == "goods
    have arrived at the warehouse" — no longer 'Shipped'."""
    rows = frappe.db.sql(
        """SELECT 1 FROM `tabPurchase Receipt Item` pri
           JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
           WHERE pri.purchase_order = %s AND pr.docstatus != 2
           LIMIT 1""",
        (po_name,),
    )
    return bool(rows)


def _has_shipping_in_transit(po_name: str) -> bool:
    """Any submitted Shipping (docstatus=1, status='In Transit') linked to this
    PO — via direct field or the Shipping PO Reference child table."""
    if frappe.db.exists("Shipping", {
        "purchase_order": po_name, "docstatus": 1, "status": "In Transit",
    }):
        return True
    rows = frappe.db.sql(
        """SELECT 1 FROM `tabShipping PO Reference` r
           JOIN `tabShipping` s ON s.name = r.parent
           WHERE r.purchase_order = %s AND s.docstatus = 1 AND s.status = 'In Transit'
           LIMIT 1""",
        (po_name,),
    )
    return bool(rows)


def set_status(po_name: str) -> str | None:
    """Compute and persist the custom status. Returns new value (or None if
    unchanged / skipped / cannot compute). Uses db.set_value to avoid
    save-hook loops.

    Skipped when the PO has `custom_status_manual` = 1 — a System Manager
    has taken ownership of the value and hooks must not overwrite it.
    """
    manual = frappe.db.get_value("Purchase Order", po_name, "custom_status_manual")
    if manual:
        return None
    new = compute_status(po_name)
    current = frappe.db.get_value("Purchase Order", po_name, STATUS_FIELD)
    if new == current:
        return None
    frappe.db.set_value(
        "Purchase Order", po_name, STATUS_FIELD, new, update_modified=False,
    )
    return new


def _pos_from_purchase_receipt(doc) -> set[str]:
    return {i.purchase_order for i in (doc.get("items") or []) if i.get("purchase_order")}


def _pos_from_purchase_invoice(doc) -> set[str]:
    return {i.purchase_order for i in (doc.get("items") or []) if i.get("purchase_order")}


def _pos_from_payment_entry(doc) -> set[str]:
    """Payment Entry → references → Purchase Invoice → items → PO names."""
    pi_names = {
        r.reference_name for r in (doc.get("references") or [])
        if r.get("reference_doctype") == "Purchase Invoice" and r.get("reference_name")
    }
    if not pi_names:
        return set()
    rows = frappe.db.sql(
        """
        SELECT DISTINCT purchase_order FROM `tabPurchase Invoice Item`
        WHERE parent IN %(pis)s AND purchase_order != '' AND purchase_order IS NOT NULL
        """,
        {"pis": tuple(pi_names)},
        as_dict=True,
    )
    return {r.purchase_order for r in rows}


def _bulk_update(po_names):
    for name in po_names:
        try:
            set_status(name)
        except Exception:
            frappe.log_error(
                title="PO custom status update failed",
                message=frappe.get_traceback(),
            )
    if po_names:
        frappe.db.commit()


# ─── Hook entry points ────────────────────────────────────────────────────────

def on_po_submit(doc, method):
    """Purchase Order submitted → set initial status."""
    set_status(doc.name)


def on_po_after_insert(doc, method):
    """New Draft PO → set 'Draft' status."""
    set_status(doc.name)


def on_po_cancel(doc, method):
    """PO cancelled → mark 'Cancelled'."""
    set_status(doc.name)


def on_po_update_after_submit(doc, method):
    """Recompute when Close/Hold action changes built-in status on a
    submitted PO (or any post-submit edit)."""
    set_status(doc.name)


def on_purchase_receipt_change(doc, method):
    _bulk_update(_pos_from_purchase_receipt(doc))


def on_purchase_invoice_change(doc, method):
    _bulk_update(_pos_from_purchase_invoice(doc))


def on_payment_entry_change(doc, method):
    _bulk_update(_pos_from_payment_entry(doc))


def _pos_from_shipping(doc) -> set[str]:
    """Shipping links to POs via direct field + Shipping PO Reference child."""
    names = set()
    if doc.get("purchase_order"):
        names.add(doc.purchase_order)
    for r in (doc.get("po_references") or doc.get("references") or []):
        if r.get("purchase_order"):
            names.add(r.purchase_order)
    return names


def on_shipping_change(doc, method):
    _bulk_update(_pos_from_shipping(doc))


# ─── Setup + backfill (call once from bench execute) ──────────────────────────

def ensure_field():
    """Create the Custom Field on Purchase Order if not present."""
    if frappe.db.exists("Custom Field", {"dt": "Purchase Order", "fieldname": STATUS_FIELD}):
        print(f"  field already exists: {STATUS_FIELD}")
        return
    cf = frappe.get_doc({
        "doctype": "Custom Field",
        "dt": "Purchase Order",
        "fieldname": STATUS_FIELD,
        "label": "Delivery / Payment Status",
        "fieldtype": "Select",
        "options": "\n".join(ALL_STATUSES),
        "insert_after": "status",
        "in_list_view": 1,
        "in_standard_filter": 1,
        "bold": 1,
        "read_only": 1,
        "description": "Auto-set by ALKHORA hooks based on Purchase Receipt + Payment state.",
    })
    cf.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"  created Custom Field {STATUS_FIELD}")


def backfill(dry_run=False):
    """Recompute custom status for every submitted Purchase Order."""
    names = frappe.db.sql_list("SELECT name FROM `tabPurchase Order` WHERE docstatus = 1")
    print(f"Backfilling {len(names)} Purchase Orders (dry_run={dry_run})")
    changed = 0
    tally = {}
    for name in names:
        new = compute_status(name)
        tally[new] = tally.get(new, 0) + 1
        if dry_run:
            continue
        current = frappe.db.get_value("Purchase Order", name, STATUS_FIELD)
        if new != current:
            frappe.db.set_value(
                "Purchase Order", name, STATUS_FIELD, new, update_modified=False,
            )
            changed += 1
    if not dry_run:
        frappe.db.commit()
    print("Distribution:")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {k or '(blank)'}: {v}")
    print(f"Rows updated: {changed}")


def run(dry_run=False):
    ensure_field()
    backfill(dry_run=dry_run)
