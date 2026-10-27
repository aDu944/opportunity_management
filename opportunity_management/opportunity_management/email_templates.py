"""The per-email templates, built from the primitives in email_design.

Split out when email_design passed 500 lines. Everything here answers "what does THIS
email say"; everything in email_design answers "what does an ALKHORA email look like".
"""

from .email_design import (
    AMBER, BRAND, FAINT, INK, LOG, MUTED, QTN, _AR, _MONO,
    button, envelope, esc, label, link, money, name_cell, progress, row,
)

# ---------------------------------------------------------------------------
# Notification-doc emails
#
# These six live in the DB as Notification records. Rather than keep six slabs of
# HTML in a `message` field nobody can diff or test, each record now holds one line:
#
#     {{ notification_email(doc, "new_quotation") }}
#
# and the design stays here, in code, next to everything else (Ahmed, 2026-10-25).
# Registered as a Jinja method in opportunity_management/hooks.py.
# ---------------------------------------------------------------------------


def _url(doctype, name):
    import frappe
    return "{0}/app/{1}/{2}".format(
        frappe.utils.get_url(), doctype.lower().replace(" ", "-"), name)


def _who(user_id):
    import frappe
    return frappe.db.get_value("User", user_id, "full_name") or user_id or ""


def _date(value, fmt="d MMMM yyyy"):
    import frappe
    if not value:
        return ""
    try:
        return frappe.utils.format_date(value, fmt)
    except Exception:  # noqa: BLE001 - a bad date must not stop the mail
        return str(value)


def _party(doc, *fields):
    for f in fields:
        v = doc.get(f)
        if v:
            return v
    return doc.get("name") or ""


def new_quotation(doc):
    customer = _party(doc, "customer_name", "party_name", "customer")
    url = _url("Quotation", doc.name)
    rows = [
        row(label("Quotation", "رقم العرض"), link(doc.name, url, QTN, mono=True)),
        row(label("Prepared by", "أعدّه"), name_cell(_who(doc.get("owner")))),
    ]
    if doc.get("valid_till"):
        rows.append(row(label("Valid until", "صالح حتى"),
                        "<strong>%s</strong>" % esc(_date(doc.get("valid_till")))))
    rows.append(row(label("Lines", "عدد المواد"),
                    esc("%d items" % len(doc.get("items") or []))))
    return envelope(
        accent=QTN, eyebrow="Quotation issued", headline=customer,
        figure=esc(money(doc.get("grand_total"), doc.get("currency"))),
        rows=rows,
        actions=[button("Open the quotation", url, QTN)],
        footnote="You are on the sales notification list.",
    )


def goods_received(doc):
    supplier = _party(doc, "supplier_name", "supplier")
    url = _url("Purchase Receipt", doc.name)
    rows = [row(label("Receipt", "رقم الاستلام"), link(doc.name, url, LOG, mono=True))]
    # The PO this settles, which the old template never showed.
    po = ""
    for it in (doc.get("items") or []):
        if it.get("purchase_order"):
            po = it.get("purchase_order")
            break
    if po:
        rows.append(row(label("Against PO", "أمر الشراء"),
                        link(po, _url("Purchase Order", po), LOG, mono=True)))
    rows.append(row(label("Received by", "استلمها"), name_cell(_who(doc.get("owner")))))
    wh = next((it.get("warehouse") for it in (doc.get("items") or []) if it.get("warehouse")), "")
    if wh:
        rows.append(row(label("Warehouse", "المخزن"), esc(wh)))
    # per_billed, NOT a lookup of invoices linked to this receipt. ALKHORA raises the
    # Purchase Invoice against the PURCHASE ORDER, so a receipt can be fully billed -
    # and paid - while nothing points at the receipt itself. MAT-PRE-2026-00084 was
    # paid on 21 June against PO 451260048 and received on 26 October; the bar used to
    # be hardcoded to "not invoiced" and said so (Ahmed, 2026-10-26).
    import frappe
    billed = frappe.utils.flt(doc.get("per_billed"))

    # Only when THIS receipt is actually billed. A PO can carry an invoice for an
    # earlier delivery while this receipt is still unbilled, and naming it there would
    # read as "this one is paid" (Ahmed, 2026-10-26).
    inv = None
    if po and billed >= 100:
        inv = frappe.db.sql(
            "SELECT pi.name, pi.status FROM `tabPurchase Invoice` pi "
            "JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name "
            "WHERE pii.purchase_order = %s AND pi.docstatus = 1 "
            "ORDER BY pi.posting_date DESC LIMIT 1", (po,), as_dict=True)
        inv = inv[0] if inv else None
    if inv:
        rows.append(row(label("Invoice", "الفاتورة"),
                        link(inv["name"], _url("Purchase Invoice", inv["name"]), LOG, mono=True)
                        + ' <span style="color:%s">· %s</span>' % (MUTED, esc(inv["status"]))))
    elif billed and billed < 100:
        rows.append(row(label("Billed", "مفوتر"), esc("%g%% of this receipt" % billed)))

    return envelope(
        accent=LOG, eyebrow="Goods received", headline=supplier,
        subline="%s · %s" % (money(doc.get("grand_total"), doc.get("currency")),
                             _date(doc.get("posting_date"))),
        extra_html=progress(
            [("Ordered", True), ("Received", True), ("Invoiced", billed >= 100)], LOG),
        rows=rows,
        actions=[button("Open the receipt", url, LOG)],
        footnote="You are on the logistics notification list.",
    )


def shipment_submitted(doc):
    url = _url("Shipping", doc.name)
    carrier = doc.get("carrier") or "TBD"
    rows = [row(label("Carrier", "الناقل"), "<strong>%s</strong>" % esc(carrier))]
    if doc.get("tracking_number"):
        rows.append(row(label("Waybill", "رقم البوليصة"),
                        '<span style="font-family:%s">%s</span>' % (_MONO, esc(doc.tracking_number))))
    rows.append(row(label("Status", "الحالة"),
                    '<strong style="color:%s">%s</strong>' % (LOG, esc(doc.get("status") or "Draft"))))
    if doc.get("purchase_order"):
        rows.append(row(label("Against PO", "أمر الشراء"),
                        link(doc.purchase_order, _url("Purchase Order", doc.purchase_order),
                             LOG, mono=True)))
    if doc.get("estimated_delivery_date"):
        rows.append(row(label("Expected", "الوصول المتوقع"),
                        esc(_date(doc.get("estimated_delivery_date")))))
    return envelope(
        accent=LOG, eyebrow="Shipment submitted",
        headline="%s · %s" % (carrier, doc.name),
        subline=_party(doc, "supplier"),
        rows=rows,
        actions=[button("Track the shipment", url, LOG)],
        footnote="You are on the logistics notification list.",
    )


def opportunity_assigned(doc):
    customer = _party(doc, "customer_name", "party_name")
    url = _url("Opportunity", doc.name)
    rows = [row(label("Opportunity", "الفرصة"), link(doc.name, url, QTN, mono=True))]
    if doc.get("expected_closing"):
        rows.append(row(label("Closing date", "تاريخ الإغلاق"),
                        "<strong>%s</strong>" % esc(_date(doc.get("expected_closing")))))
    if doc.get("opportunity_amount"):
        rows.append(row(label("Value", "القيمة"),
                        esc(money(doc.get("opportunity_amount"), doc.get("currency")))))
    rows.append(row(label("Assigned by", "أسندها"), name_cell(_who(doc.get("owner")))))
    return envelope(
        accent=QTN, eyebrow="New opportunity assigned to you", headline=customer,
        rows=rows,
        actions=[button("Open the opportunity", url, QTN)],
        footnote="You are the responsible party for this opportunity.",
    )


def closing_date_extended(doc):
    customer = _party(doc, "customer_name", "party_name")
    url = _url("Opportunity", doc.name)
    was = ""
    try:
        before = doc.get_doc_before_save()
        if before and before.get("expected_closing"):
            was = _date(before.get("expected_closing"))
    except Exception:  # noqa: BLE001 - the previous value is a nicety, not the point
        was = ""
    rows = [row(label("Opportunity", "الفرصة"), link(doc.name, url, QTN, mono=True))]
    if was:
        rows.append(row(label("Was", "كان"),
                        '<span style="text-decoration:line-through;color:%s">%s</span>'
                        % (MUTED, esc(was))))
    rows.append(row(label("Now closing", "صار الإغلاق"),
                    "<strong>%s</strong>" % esc(_date(doc.get("expected_closing")))))
    rows.append(row(label("Changed by", "غيّرها"), name_cell(_who(doc.get("modified_by")))))
    return envelope(
        accent=AMBER, eyebrow="Closing date changed", headline=customer,
        rows=rows,
        actions=[button("Open the opportunity", url, AMBER)],
        footnote="You are responsible for this opportunity.",
    )


def welcome_user(doc):
    import frappe
    base = frappe.utils.get_url()
    rows = [
        row(label("Sign in as", "الحساب"),
            '<span style="font-family:%s">%s</span>' % (_MONO, esc(doc.get("email") or doc.name))),
        row(label("Address", "الرابط"),
            '<span style="font-family:%s;color:%s">%s</span>'
            % (_MONO, BRAND, esc(base.replace("https://", "").replace("http://", "")))),
    ]
    roles = [r.get("role") for r in (doc.get("roles") or []) if r.get("role")]
    if roles:
        rows.append(row(label("Your role", "الدور"), esc(", ".join(roles[:3]))))
    greeting = doc.get("full_name") or doc.get("first_name") or ""
    return envelope(
        accent=BRAND, band=True, eyebrow="ALKHORA ERP", headline="Your account is ready",
        lead=('Welcome, <strong style="font-family:%s">%s</strong>.<br>'
              "Sign in with this address. You will be asked to set a password the first time."
              % (_AR, esc(greeting))),
        rows=rows,
        actions=[button("Set your password", base + "/update-password", BRAND)],
        footnote="If you were not expecting this, tell IT and do not set a password.",
    )


_KINDS = {
    "new_quotation": new_quotation,
    "goods_received": goods_received,
    "shipment_submitted": shipment_submitted,
    "opportunity_assigned": opportunity_assigned,
    "closing_date_extended": closing_date_extended,
    "welcome_user": welcome_user,
}


def notification_email(doc, kind):
    """Jinja entry point for the Notification records.

    Never raises: a Notification whose template blows up loses the whole email, and a
    plain-but-sent message beats a designed-but-missing one.
    """
    import frappe
    try:
        return _KINDS[kind](doc)
    except Exception as exc:  # noqa: BLE001
        frappe.log_error(
            title="Notification email build failed",
            message="kind=%s doc=%s: %s" % (kind, getattr(doc, "name", "?"), exc),
        )
        name = getattr(doc, "name", "")
        return ('<p style="font-family:sans-serif">%s <a href="%s">%s</a></p>'
                % (esc(kind.replace("_", " ").title()),
                   esc(_url(getattr(doc, "doctype", "") or "", name)), esc(name)))


def shipment_tracking(doc, snap, delivered=False, checkpoints=None):
    """A DHL tracking movement, for the hourly puller in iraqi_customs.

    Delivered gets the solid band - it is the end of the story and the one update
    anyone forwards. Everything else is an ordinary movement and takes the rule, so a
    shipment that checkpoints eight times in a day does not shout eight times.
    """
    url = _url("Shipping", doc.name)
    carrier = doc.get("carrier") or "DHL"
    accent = LOG
    rows = [
        row(label("Status", "الحالة"),
            '<strong style="color:%s">%s</strong>' % (accent, esc(snap.get("status") or ""))),
    ]
    if snap.get("location"):
        rows.append(row(label("Last seen", "آخر موقع"), esc(snap["location"])))
    if doc.get("tracking_number"):
        rows.append(row(label("Waybill", "رقم البوليصة"),
                        '<span style="font-family:%s">%s</span>'
                        % (_MONO, esc(doc.tracking_number))))
    if doc.get("purchase_order"):
        rows.append(row(label("Against PO", "أمر الشراء"),
                        link(doc.purchase_order, _url("Purchase Order", doc.purchase_order),
                             accent, mono=True)))
    if delivered and doc.get("actual_delivery_date"):
        rows.append(row(label("Delivered", "تاريخ التسليم"),
                        "<strong>%s</strong>" % esc(_date(doc.actual_delivery_date))))
    elif snap.get("estimated_delivery"):
        rows.append(row(label("Expected", "الوصول المتوقع"),
                        esc(_date(snap["estimated_delivery"]))))

    # The last few checkpoints, newest first. This is the whole point of a tracking
    # mail: the reader should not have to open the ERP to see what moved.
    trail = ""
    for i, e in enumerate(list(checkpoints or [])[:4]):
        dot = accent if i == 0 else "#c3cdcb"
        when = (e.get("datetime") or "")[:16].replace("T", " ")
        trail += (
            '<tr>'
            f'<td width="16" style="vertical-align:top;padding:5px 0 0">'
            f'<table cellpadding="0" cellspacing="0" border="0" role="presentation"><tr>'
            f'<td width="8" height="8" style="background:{dot};border-radius:4px;'
            f'font-size:0;line-height:8px">&nbsp;</td></tr></table></td>'
            f'<td style="padding:2px 0 8px;font-size:12.5px;color:{INK}">'
            f'{esc(e.get("description") or e.get("status") or "")}'
            f'<br><span style="color:{FAINT}">{esc(when)}'
            + (f' · {esc(e.get("location"))}' if e.get("location") else "")
            + '</span></td></tr>'
        )
    if trail:
        trail = (f'<p style="margin:0 0 8px;font-family:{_MONO};font-size:10.5px;'
                 f'letter-spacing:.08em;text-transform:uppercase;color:{FAINT};'
                 f'font-weight:600">Recent checkpoints</p>'
                 f'<table width="100%" cellpadding="0" cellspacing="0" border="0" '
                 f'role="presentation">{trail}</table>')

    return envelope(
        accent=accent,
        band=delivered,
        eyebrow="Shipment delivered" if delivered else "Shipment update",
        headline="%s · %s" % (carrier, doc.name),
        subline=doc.get("supplier") or None,
        rows=rows,
        extra_html=trail,
        actions=[button("Open the shipment", url, accent)],
        footnote="You are on the logistics notification list.",
    )
