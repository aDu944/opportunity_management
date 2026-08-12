// From ERPNext Client Script: Opportunity Status
// Doctype: Opportunity | View: Form | Size: 922 bytes
frappe.ui.form.on('Opportunity', {
    refresh: function(frm) {
        // Status visibility — only System Manager sees Status field
        if (!frappe.user.has_role('System Manager')) {
            frm.set_df_property('status', 'hidden', 1);
        } else {
            frm.set_df_property('status', 'hidden', 0);
        }

        // 'View Related Quotations' button (count only, no math)
        if (frm.doc.name && !frm.is_new()) {
            frappe.db.count('Quotation', {
                filters: {opportunity: frm.doc.name, docstatus: ['!=', 2]}
            }).then(c => {
                if (c > 0) {
                    frm.add_custom_button(__('View Related Quotations (' + c + ')'), () => {
                        frappe.route_options = {opportunity: frm.doc.name};
                        frappe.set_route('List', 'Quotation');
                    });
                }
            });
        }
    }
});