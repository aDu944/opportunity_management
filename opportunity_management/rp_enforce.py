"""Enforce Project.custom_responsible_party mirrors linked Opportunity.

Project has a direct Link field `custom_opportunity` — no chain-walk needed.
Server hook forces the field to match on validate; client script mirrors this
in the UI by disabling the field when the opportunity has parties.
"""
import frappe


def _opportunity_of_project(doc):
    """Return linked Opportunity name, or None."""
    return doc.get("custom_opportunity") or None


def enforce_project_responsible_party(doc, method=None):
    opp = _opportunity_of_project(doc)
    if not opp:
        return
    parties = [
        r[0] for r in frappe.db.sql("""
            SELECT responsible_party FROM `tabOpportunity Responsible Party`
            WHERE parent=%s AND parenttype='Opportunity'
              AND parentfield='custom_responsible_party'
              AND responsible_party IS NOT NULL
            ORDER BY idx
        """, (opp,)) if r[0]
    ]
    if not parties:
        return
    doc.set("custom_responsible_party", [])
    for idx, rp in enumerate(parties, start=1):
        doc.append("custom_responsible_party", {"responsible_party": rp, "idx": idx})


def install():
    cs_name = "Project — Responsible Party from Opportunity (read-only)"
    if frappe.db.exists("Client Script", cs_name):
        cs = frappe.get_doc("Client Script", cs_name)
    else:
        cs = frappe.new_doc("Client Script"); cs.name = cs_name
    cs.dt = "Project"; cs.view = "Form"; cs.enabled = 1
    cs.script = r"""
frappe.ui.form.on('Project', {
    refresh: async function(frm) {
        frm.set_df_property('custom_responsible_party', 'read_only', 0);
        frm.set_df_property('custom_responsible_party', 'description', '');
        const oppName = frm.doc.custom_opportunity;
        if (!oppName) return;
        try {
            const opp = await frappe.db.get_doc('Opportunity', oppName);
            const parties = opp.custom_responsible_party || [];
            if (parties.length === 0) return;
            frm.set_df_property('custom_responsible_party', 'read_only', 1);
            frm.set_df_property('custom_responsible_party', 'description',
                __('Inherited from Opportunity <a href="/app/opportunity/{0}">{0}</a> — edit there.', [oppName]));
        } catch (e) { /* leave editable */ }
    },
    custom_opportunity: function(frm) { frm.trigger('refresh'); },
});
""".strip()
    cs.save(ignore_permissions=True)
    frappe.db.commit()
    print(f"Client Script installed & enabled: {cs.name}")
