// From ERPNext Client Script: Delivery Time Calculation
// Doctype: Purchase Order | View: Form | Size: 745 bytes
frappe.ui.form.on('Opportunity', {
    party_name: function(frm) {
        if (frm.doc.party_name) {
            // Fetch the Customer document
            frappe.db.get_value('Customer', frm.doc.party_name, 'custom_abr')
                .then(r => {
                    if (r.message) {
                        // Set the Opportunity's custom_abr field with the Customer's custom_abr value
                        frm.set_value('custom_abr', r.message.custom_abr);
                    } else {
                        frm.set_value('custom_abr', '');
                    }
                });
        } else {
            // Clear the custom_abr field if no customer is selected
            frm.set_value('custom_abr', '');
        }
    }
});
