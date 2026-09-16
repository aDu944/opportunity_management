import frappe
from frappe import _
from frappe.utils import nowdate, getdate, flt


def on_quotation_save(doc, method):
    """
    When a new Quotation is inserted with items + total > 0:
      - move the Opportunity's status Open -> Quotation (intermediate state,
        never Converted/'Won' — that only happens on Sales Order submission)
      - notify the Opportunity's assignees + log the assignment (once per opp)

    Status transition rules:
      Open       -> Quotation
      Quotation  -> Quotation (no-op)
      Converted  -> no change (Won stays Won)
      Lost       -> no change
      Closed     -> no change
    """
    if not doc or doc.docstatus == 2:
        return

    if not doc.items or (doc.get("grand_total") or 0) <= 0:
        return
    opportunity_name = doc.get("opportunity")

    if not opportunity_name:
        # Try to find opportunity from items or other links
        opportunity_name = find_linked_opportunity(doc)

    if not opportunity_name:
        return

    # Advance status Open -> Quotation. Never touch Converted/Lost/Closed —
    # ERPNext auto-sets Converted on Sales Order submission and other states
    # are manual/meaningful.
    opp_status = frappe.db.get_value("Opportunity", opportunity_name, "status")
    if opp_status == "Open":
        try:
            frappe.db.set_value(
                "Opportunity", opportunity_name, "status", "Quotation",
                update_modified=False,
            )
            opp = frappe.get_doc("Opportunity", opportunity_name)
            opp.add_comment(
                "Comment",
                f"Status: Open -> Quotation (draft Quotation {doc.name} created)",
            )
        except Exception as e:
            frappe.log_error(f"Failed to advance Opportunity {opportunity_name} to Quotation: {e}")

    # Notify + log only on the FIRST quotation per opportunity — skip if
    # another non-cancelled quotation already exists.
    existing = frappe.db.count(
        "Quotation",
        filters={
            "opportunity": opportunity_name,
            "docstatus": ["!=", 2],
            "name": ["!=", doc.name],
        },
    )
    if existing > 0:
        return

    notify_opportunity_assignees(opportunity_name, doc.name)
    update_assignment_log(opportunity_name, doc.name)


def on_sales_order_save(doc, method):
    """
    When a Sales Order is created (draft OR submitted), mark every linked
    Opportunity as Converted ("Won"). Linkage traversal:

        Sales Order Item.prevdoc_docname -> Quotation.opportunity -> Opportunity

    Never overwrites Lost/Closed — those are terminal states.
    Idempotent: if the Opportunity is already Converted, no change.
    """
    if not doc:
        return
    if doc.docstatus == 2:  # cancelled
        return

    opps = frappe.db.sql_list(
        """
        SELECT DISTINCT q.opportunity
        FROM `tabSales Order Item` sit
        JOIN tabQuotation q ON q.name = sit.prevdoc_docname
        WHERE sit.parent = %s
          AND q.opportunity IS NOT NULL
          AND q.opportunity != ''
        """,
        doc.name,
    )
    if not opps:
        return

    for opp_name in opps:
        try:
            current = frappe.db.get_value("Opportunity", opp_name, "status")
            if current in ("Converted", "Lost", "Closed"):
                continue
            frappe.db.set_value(
                "Opportunity", opp_name, "status", "Converted",
                update_modified=False,
            )
            opp = frappe.get_doc("Opportunity", opp_name)
            stage = "draft" if doc.docstatus == 0 else "submitted"
            opp.add_comment(
                "Comment",
                f"Status: {current} -> Converted (Won) — Sales Order {doc.name} created ({stage})",
            )
        except Exception as e:
            frappe.log_error(f"Failed to mark Opportunity {opp_name} Won from SO {doc.name}: {e}")


def find_linked_opportunity(doc):
    """Try to find linked opportunity from various sources"""

    # Check quotation items for opportunity reference
    for item in doc.items:
        if item.get("prevdoc_docname") and item.get("prevdoc_doctype") == "Opportunity":
            return item.prevdoc_docname

    # Check if there's a direct opportunity field
    if doc.get("opportunity"):
        return doc.opportunity

    return None


def close_opportunity(opportunity_name, quotation_name):
    """Close the Opportunity by updating its status"""

    try:
        opportunity = frappe.get_doc("Opportunity", opportunity_name)

        # Update status to Closed or Converted based on your workflow
        # Check if 'Converted' status exists, otherwise use 'Closed'
        if "Converted" in [o.strip() for o in (frappe.get_meta("Opportunity").get_field("status").options or "").splitlines() if o.strip()]:
            opportunity.status = "Converted"
        else:
            opportunity.status = "Closed"

        # Add reference to the quotation
        opportunity.add_comment("Comment", f"Converted to Quotation {quotation_name}")

        # Save the opportunity
        opportunity.save(ignore_permissions=True)

        frappe.msgprint(
            _(f"Opportunity {opportunity_name} has been closed."),
            alert=True
        )

    except Exception as e:
        frappe.log_error(f"Failed to close Opportunity {opportunity_name}: {str(e)}")
        frappe.msgprint(
            _(f"Warning: Could not close Opportunity {opportunity_name}. Please check manually."),
            alert=True,
            indicator="orange"
        )


def notify_opportunity_assignees(opportunity_name, quotation_name):
    """Notify assignees that their opportunity was converted to a quotation."""
    try:
        from opportunity_management.opportunity_management.notification_utils import (
            get_opportunity_assignee_recipients_for_notification
        )

        opp = frappe.get_doc("Opportunity", opportunity_name)
        recipients = get_opportunity_assignee_recipients_for_notification(opp) or []

        if not recipients:
            return

        subject = f"Opportunity Converted: {opportunity_name}"
        message = f"""
        <h3>Opportunity converted to Quotation</h3>

        <p>The Opportunity <b>{opportunity_name}</b> has been converted to a Quotation.</p>

        <p><b>Quotation:</b> {quotation_name}</p>

        <p>
            <a href=\"{frappe.utils.get_url()}/app/quotation/{quotation_name}\"
               style=\"background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;\">
                View Quotation
            </a>
        </p>
        """

        frappe.sendmail(
            recipients=recipients,
            subject=subject,
            message=message,
            now=True
        )
    except Exception as e:
        frappe.log_error(f"Failed to send conversion email for {opportunity_name}: {str(e)}")


def update_assignment_log(opportunity_name, quotation_name):
    """Update the assignment log with completion details"""
    
    if not frappe.db.exists("DocType", "Opportunity Assignment Log"):
        return
    
    logs = frappe.get_all("Opportunity Assignment Log",
        filters={"opportunity": opportunity_name},
        fields=["name"]
    )
    
    closing_date = getdate(nowdate())
    
    for log in logs:
        log_doc = frappe.get_doc("Opportunity Assignment Log", log.name)
        
        # Calculate if completed on time
        on_time = True
        if log_doc.closing_date:
            on_time = closing_date <= getdate(log_doc.closing_date)
        
        log_doc.db_set({
            "status": "Completed",
            "completed_date": closing_date,
            "quotation": quotation_name,
            "completed_on_time": on_time
        })


def check_and_close_todos():
    """Deprecated: ToDo-based cleanup is no longer used."""
    return


def recalc_opportunity_amount(doc, method=None):
    """Recompute Opportunity.opportunity_amount as the sum of its non-cancelled
    Quotations' grand totals, converted to the opportunity's currency.

    Runs server-side on Quotation lifecycle events — no user save required.
    Currency conversion: each quotation's grand_total is multiplied by its
    conversion_rate to land in company (base) currency, then divided by the
    opportunity's own conversion_rate to land in opportunity currency.
    """
    import frappe
    opp_name = doc.get("opportunity") if hasattr(doc, "get") else None
    if not opp_name:
        return
    if not frappe.db.exists("Opportunity", opp_name):
        return

    opp = frappe.db.get_value(
        "Opportunity", opp_name,
        ["currency", "conversion_rate"],
        as_dict=True,
    )
    if not opp:
        return

    quotations = frappe.get_all(
        "Quotation",
        filters={"opportunity": opp_name, "docstatus": ["!=", 2]},
        fields=["grand_total", "conversion_rate"],
    )

    base_total = sum(flt(q.grand_total) * (flt(q.conversion_rate) or 1.0) for q in quotations)
    opp_rate = flt(opp.conversion_rate) or 1.0
    opp_total = base_total / opp_rate if opp_rate else 0.0

    frappe.db.set_value(
        "Opportunity",
        opp_name,
        {"opportunity_amount": opp_total, "base_opportunity_amount": base_total},
        update_modified=False,
    )
