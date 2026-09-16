"""Whitelisted endpoint that builds an xlsx for the Project P&L Detail report,
with a header block at the top and the data table below. Called from the
report's custom Excel button."""
import frappe
from frappe import _
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


def _responsible_party_names(project):
    """Readable names for a project's Responsible Party rows.

    Project.custom_responsible_party is a Table MultiSelect of
    'Opportunity Responsible Party'. Its single Link field stores the autonamed
    id (RP-00038); the human name is the target doctype's title_field,
    Responsible Party.display_name.

    The same child doctype is also attached to Opportunity, hence the
    parenttype guard. Rows keep their child-table order.
    """
    rows = frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(TRIM(r.display_name), ''), r.name) AS nm
        FROM `tabOpportunity Responsible Party` orp
        JOIN `tabResponsible Party` r ON r.name = orp.responsible_party
        WHERE orp.parent = %(project)s AND orp.parenttype = 'Project'
        ORDER BY orp.idx
        """,
        {"project": project},
        as_dict=True,
    )
    return ", ".join(x["nm"] for x in rows if x.get("nm")) or "\u2014"


@frappe.whitelist()
def project_pl_excel(project, to_currency="IQD", exchange_rate=1,
                     include_exchange_gain_loss=0):
    if not project:
        frappe.throw(_("Project is required"))
    frappe.has_permission("Project", doc=project, throw=True)

    # ── Header data ────────────────────────────────────────────────────────
    p = frappe.get_doc("Project", project)
    party_names = _responsible_party_names(project)

    # ── Data rows via the same SQL as the report ──────────────────────────
    report = frappe.get_doc("Report", "Project PL Detail")
    rows = frappe.db.sql(report.query, {
        "project": project,
        "to_currency": to_currency,
        "exchange_rate": float(exchange_rate or 1),
        "include_exchange_gain_loss": frappe.utils.cint(include_exchange_gain_loss),
    }, as_dict=True)

    # ── Build workbook ─────────────────────────────────────────────────────
    wb = Workbook()
    ws = wb.active
    ws.title = "Project P&L"

    thin = Side(border_style="thin", color="E2E8F0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    bold = Font(bold=True)
    hdr_fill = PatternFill("solid", fgColor="F1F5F9")
    lbl_font = Font(color="64748B")

    # Header block: 6 rows of Label / Value pairs
    header_rows = [
        ("Project #",         project),
        ("Project Name",      p.project_name or "—"),
        ("Cost Center",       p.cost_center or "—"),
        ("Status",            p.status or "—"),
        ("Responsible Party", party_names),
    ]
    # Compute Net P&L from rows
    total_row = next((r for r in rows if (r.get("Category:Data:150") or r.get("category")) == "TOTAL"), None)
    if total_row:
        header_rows.append(("Net P&L", total_row.get("Amount:Currency/currency_col:180") or 0))

    for label, value in header_rows:
        ws.append([label, value])
    # Style header
    for row_idx in range(1, len(header_rows) + 1):
        ws.cell(row=row_idx, column=1).font = lbl_font
        ws.cell(row=row_idx, column=2).font = bold
    # Set columns wider
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60

    # Empty row separator
    ws.append([])

    # Data column headers
    col_start = ws.max_row + 1
    ws.append(["Category", "Account", f"Amount ({to_currency})", "Entries"])
    for col in range(1, 5):
        c = ws.cell(row=col_start, column=col)
        c.font = bold
        c.fill = hdr_fill
        c.border = border

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 10

    # Data rows
    for r in rows:
        cat = r.get("Category:Data:150") or r.get("category") or ""
        acc = r.get("Account:Link/Account:340") or r.get("account") or ""
        amt = r.get("Amount:Currency/currency_col:180") or r.get("amount") or 0
        ent = r.get("Entries:Int:80") or r.get("entries") or 0
        ws.append([cat, acc, amt, ent])
        last = ws.max_row
        for col in range(1, 5):
            ws.cell(row=last, column=col).border = border
        ws.cell(row=last, column=3).number_format = f'#,##0.00 "{to_currency}"'
        if cat == "TOTAL":
            for col in range(1, 5):
                c = ws.cell(row=last, column=col)
                c.font = bold
                c.fill = PatternFill("solid", fgColor=("DCFCE7" if amt >= 0 else "FEE2E2"))

    # ── Return as attachment ──────────────────────────────────────────────
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    filename = f"Project_PL_{project}.xlsx"
    frappe.local.response.filename = filename
    frappe.local.response.filecontent = bio.read()
    frappe.local.response.type = "download"


@frappe.whitelist()
def project_pl_summary(project, to_currency="IQD", exchange_rate=1,
                       include_exchange_gain_loss=0):
    """Summary figures for the Project PL Detail report's card strip.

    Income / Expense / Withhold come from the GL, matching the scope of the
    report query itself. PO value and outstanding balances come from the source
    documents (Purchase Order / Purchase Invoice / Sales Invoice), which a
    GL-only query cannot reach.

    Project linkage is checked BOTH at the parent level and per line item, so
    contracts booked on the header and per-item allocations both count.

    Source documents store their totals in the DOCUMENT's transaction currency,
    so PO uses base_grand_total and the invoice outstandings are multiplied by
    conversion_rate (no base_outstanding_amount field exists) to land in the
    company base currency first. GL columns (ge.debit/ge.credit) are already
    base-currency.

    All amounts are then divided by `exchange_rate` to match the report's own
    conversion. Expense and Withhold are returned NEGATIVE so the cards render
    red with the same sign convention the report table uses.
    """
    if not project:
        frappe.throw(_("Project is required"))
    frappe.has_permission("Project", doc=project, throw=True)

    try:
        rate = float(exchange_rate or 1) or 1.0
    except (TypeError, ValueError):
        rate = 1.0

    def conv(v):
        return round(float(v or 0) / rate, 2)

    args = {
        "project": project,
        "include_exchange_gain_loss": frappe.utils.cint(include_exchange_gain_loss),
    }

    # ── Income / Expense from the GL (same scope as the report query) ───────
    gl = frappe.db.sql(
        """
        SELECT
            SUM(CASE WHEN a.root_type = 'Income'  THEN ge.credit - ge.debit ELSE 0 END) AS income,
            SUM(CASE WHEN a.root_type = 'Expense' THEN ge.debit  - ge.credit ELSE 0 END) AS expense
        FROM `tabGL Entry` ge
        JOIN `tabAccount` a ON a.name = ge.account
        WHERE ge.is_cancelled = 0 AND ge.project = %(project)s
          AND (%(include_exchange_gain_loss)s = 1
               OR ge.account NOT IN (SELECT c.exchange_gain_loss_account FROM `tabCompany` c
                                     WHERE c.exchange_gain_loss_account IS NOT NULL))
        """,
        args,
        as_dict=True,
    )
    gl = gl[0] if gl else {}

    # ── Withholding tax: Tax-type accounts, or names that look like withholding
    #    (LIKE is case-insensitive under the default utf8mb4 *_ci collation) ──
    wh = frappe.db.sql(
        """
        SELECT SUM(ge.debit - ge.credit) AS amt
        FROM `tabGL Entry` ge
        JOIN `tabAccount` a ON a.name = ge.account
        WHERE ge.is_cancelled = 0 AND ge.project = %(project)s
          AND (a.account_type = 'Tax'
               OR a.account_name LIKE %(wht_en)s
               OR a.account_name LIKE %(wht_ab)s
               OR a.account_name LIKE %(wht_ar)s)
        """,
        dict(args, wht_en="%withhold%", wht_ab="%WHT%", wht_ar="%استقطاع%"),
        as_dict=True,
    )
    wh = wh[0] if wh else {}

    # ── Contract value: what the CUSTOMER ordered ─────────────────────────
    # Sales Orders, not Purchase Orders. A PO is procurement cost and already
    # reaches this report via the GL expense lines once received/invoiced;
    # counting it as "contract value" would double-count it on the wrong side.
    so = frappe.db.sql(
        """
        SELECT SUM(so.base_grand_total) AS amt
        FROM `tabSales Order` so
        WHERE so.docstatus = 1
          AND (so.project = %(project)s
               OR EXISTS (SELECT 1 FROM `tabSales Order Item` soi
                          WHERE soi.parent = so.name AND soi.project = %(project)s))
        """,
        args,
        as_dict=True,
    )
    so = so[0] if so else {}

    # ── Outstanding payable (supplier invoices not fully paid) ─────────────
    pay = frappe.db.sql(
        """
        SELECT SUM(pi.outstanding_amount * COALESCE(NULLIF(pi.conversion_rate, 0), 1)) AS amt
        FROM `tabPurchase Invoice` pi
        WHERE pi.docstatus = 1 AND pi.outstanding_amount > 0
          AND (pi.project = %(project)s
               OR EXISTS (SELECT 1 FROM `tabPurchase Invoice Item` pii
                          WHERE pii.parent = pi.name AND pii.project = %(project)s))
        """,
        args,
        as_dict=True,
    )
    pay = pay[0] if pay else {}

    # ── Outstanding receivable (customer invoices not fully collected) ─────
    rec = frappe.db.sql(
        """
        SELECT SUM(si.outstanding_amount * COALESCE(NULLIF(si.conversion_rate, 0), 1)) AS amt
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1 AND si.outstanding_amount > 0
          AND (si.project = %(project)s
               OR EXISTS (SELECT 1 FROM `tabSales Invoice Item` sii
                          WHERE sii.parent = si.name AND sii.project = %(project)s))
        """,
        args,
        as_dict=True,
    )
    rec = rec[0] if rec else {}

    # ── GL posting-date span ───────────────────────────────────────────────
    # Drill-down links into the General Ledger need an explicit date range: GL
    # defaults to the current fiscal year, so older postings stay hidden until
    # the user widens the filter by hand.
    span = frappe.db.sql(
        """
        SELECT MIN(ge.posting_date) AS gl_from, MAX(ge.posting_date) AS gl_to
        FROM `tabGL Entry` ge
        WHERE ge.is_cancelled = 0 AND ge.project = %(project)s
        """,
        args,
        as_dict=True,
    )
    span = span[0] if span else {}

    return {
        "currency": to_currency,
        "responsible_parties": _responsible_party_names(project),
        "gl_from": str(span.get("gl_from") or ""),
        "gl_to": str(span.get("gl_to") or ""),
        "total_income": conv(gl.get("income")),
        "total_expense": -conv(gl.get("expense")),
        "total_withhold": -conv(wh.get("amt")),
        "total_contract_value": conv(so.get("amt")),
        "outstanding_payable": conv(pay.get("amt")),
        "outstanding_receivable": conv(rec.get("amt")),
    }
