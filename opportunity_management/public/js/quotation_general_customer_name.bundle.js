// From ERPNext Client Script: Quotation General Customer Name
// Doctype: Quotation | View: Form | Size: 3092 bytes
frappe.ui.form.on('Quotation', {
    opportunity: function(frm) {
        if(frm.doc.opportunity && frm.doc.customer_name == "General - عامة") {
            frappe.db.get_value('Opportunity', frm.doc.opportunity, 
                ['custom_man_customer_name', 'custom_man_customer_address'], 
                function(r) {
                    if(r && r.custom_man_customer_name) {
                        frm.set_value('custom_man_customer_name', r.custom_man_customer_name);
                    }
                    if(r && r.custom_man_customer_address) {
                        frm.set_value('custom_man_customer_address', r.custom_man_customer_address);
                    }
                }
            );
        }
    }
});

frappe.ui.form.on('Quotation Item', {
    custom_tech_desc: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.custom_tech_desc) {
            // Trim whitespace
            row.custom_tech_desc = row.custom_tech_desc.trim();
            // If empty after trim, set to empty string
            if (!row.custom_tech_desc) {
                row.custom_tech_desc = '';
            }
            frm.refresh_field('items');
        }
    }
});


frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        auto_fill_sn_po(frm);
    },
    
    before_save: function(frm) {
        auto_fill_sn_po(frm);
    }
});

frappe.ui.form.on('Quotation Item', {
    items_add: function(frm, cdt, cdn) {
        auto_fill_sn_po(frm);
    },
    
    items_remove: function(frm, cdt, cdn) {
        auto_fill_sn_po(frm);
    },
    
    custom_sn_po: function(frm, cdt, cdn) {
        auto_fill_sn_po(frm);
    }
});

function auto_fill_sn_po(frm) {
    let rows = frm.doc.items || [];
    
    if (rows.length === 0) return;
    
    // Check if user has filled any custom_sn_po
    let user_filled_index = -1;
    let user_filled_value = 0;
    
    for (let i = 0; i < rows.length; i++) {
        if (rows[i].custom_sn_po) {
            user_filled_index = i;
            user_filled_value = rows[i].custom_sn_po;
            break;
        }
    }
    
    // If no rows are filled, auto-fill all rows
    if (user_filled_index === -1) {
        rows.forEach((row, index) => {
            if (!row.custom_sn_po) {
                frappe.model.set_value(row.doctype, row.name, 'custom_sn_po', index + 1);
            }
        });
    } else {
        // Auto-fill from row 1 until the filled row
        for (let i = 0; i < user_filled_index; i++) {
            if (!rows[i].custom_sn_po) {
                frappe.model.set_value(rows[i].doctype, rows[i].name, 'custom_sn_po', i + 1);
            }
        }
        
        // Continue after the user's filled row by adding 1
        let next_value = user_filled_value + 1;
        for (let i = user_filled_index + 1; i < rows.length; i++) {
            if (!rows[i].custom_sn_po) {
                frappe.model.set_value(rows[i].doctype, rows[i].name, 'custom_sn_po', next_value);
                next_value++;
            }
        }
    }
    
    frm.refresh_field('items');
}