// From ERPNext Client Script: Journal Entry Project & Opportunity
// Doctype: Journal Entry | View: Form | Size: 5916 bytes
frappe.ui.form.on('Journal Entry', {
    refresh: function(frm) {
        // Update visibility of parent fields based on settings
        frm.toggle_display('custom_opportunity', !frm.doc.custom_allow_multi_opportunity);
        frm.toggle_display('custom_project', !frm.doc.custom_allow_multi_project);
        frm.toggle_display('custom_cost_center', !frm.doc.custom_allow_multi_cost_center);
        
        // Set read-only status for child table fields
        update_read_only_status(frm);
        
        // Add a message to inform users which fields can be edited
        show_editable_fields_message(frm);
    },
    
    custom_opportunity: function(frm) {
        if (frm.doc.custom_opportunity && !frm.doc.custom_allow_multi_opportunity) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'custom_opportunity', frm.doc.custom_opportunity);
            });
            frm.refresh_field('accounts');
        }
    },
    
    custom_project: function(frm) {
        if (frm.doc.custom_project && !frm.doc.custom_allow_multi_project) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'project', frm.doc.custom_project);
            });
            frm.refresh_field('accounts');
        }
    },
    
    custom_cost_center: function(frm) {
        if (frm.doc.custom_cost_center && !frm.doc.custom_allow_multi_cost_center) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'cost_center', frm.doc.custom_cost_center);
            });
            frm.refresh_field('accounts');
        }
    },
    
    custom_allow_multi_opportunity: function(frm) {
        frm.toggle_display('custom_opportunity', !frm.doc.custom_allow_multi_opportunity);
        
        if (!frm.doc.custom_allow_multi_opportunity && frm.doc.custom_opportunity) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'custom_opportunity', frm.doc.custom_opportunity);
            });
        }
        
        // Update read-only status and message
        update_read_only_status(frm);
        show_editable_fields_message(frm);
        frm.refresh_field('accounts');
    },
    
    custom_allow_multi_project: function(frm) {
        frm.toggle_display('custom_project', !frm.doc.custom_allow_multi_project);
        
        if (!frm.doc.custom_allow_multi_project && frm.doc.custom_project) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'project', frm.doc.custom_project);
            });
        }
        
        // Update read-only status and message
        update_read_only_status(frm);
        show_editable_fields_message(frm);
        frm.refresh_field('accounts');
    },
    
    custom_allow_multi_cost_center: function(frm) {
        frm.toggle_display('custom_cost_center', !frm.doc.custom_allow_multi_cost_center);
        
        if (!frm.doc.custom_allow_multi_cost_center && frm.doc.custom_cost_center) {
            $.each(frm.doc.accounts || [], function(i, account) {
                frappe.model.set_value(account.doctype, account.name, 'cost_center', frm.doc.custom_cost_center);
            });
        }
        
        // Update read-only status and message
        update_read_only_status(frm);
        show_editable_fields_message(frm);
        frm.refresh_field('accounts');
    }
});

// Function to set read-only status for child table fields
function update_read_only_status(frm) {
    // Set read-only based on checkbox states
    frm.fields_dict.accounts.grid.update_docfield_property(
        'custom_opportunity', 
        'read_only', 
        !frm.doc.custom_allow_multi_opportunity
    );
    
    frm.fields_dict.accounts.grid.update_docfield_property(
        'project', 
        'read_only', 
        !frm.doc.custom_allow_multi_project
    );
    
    frm.fields_dict.accounts.grid.update_docfield_property(
        'cost_center', 
        'read_only', 
        !frm.doc.custom_allow_multi_cost_center
    );
}

// Function to show a message about which fields can be edited
function show_editable_fields_message(frm) {
    // Clear any existing messages
    frm.dashboard.clear_headline();
    
    // Build a message about editable fields
    var editable_fields = [];
    
    if (frm.doc.custom_allow_multi_opportunity) {
        editable_fields.push("Opportunity");
    }
    
    if (frm.doc.custom_allow_multi_project) {
        editable_fields.push("Project");
    }
    
    if (frm.doc.custom_allow_multi_cost_center) {
        editable_fields.push("Cost Center");
    }
    
    if (editable_fields.length > 0) {
        var editable_fields_html = '<span style="color: red;">' + editable_fields.join(", ") + '</span>';
        frm.dashboard.set_headline("Per-item editable fields: " + editable_fields_html + "  :يرجى ادخال الحقول التالية يدوياً في الجدول لكل سطر ");
    }
}


// Handle new rows added to the accounts table
frappe.ui.form.on('Journal Entry Account', {
    accounts_add: function(frm, cdt, cdn) {
        var account = locals[cdt][cdn];
        
        if (frm.doc.custom_opportunity && !frm.doc.custom_allow_multi_opportunity) {
            frappe.model.set_value(cdt, cdn, 'custom_opportunity', frm.doc.custom_opportunity);
        }
        
        if (frm.doc.custom_project && !frm.doc.custom_allow_multi_project) {
            frappe.model.set_value(cdt, cdn, 'project', frm.doc.custom_project);
        }
        
        if (frm.doc.custom_cost_center && !frm.doc.custom_allow_multi_cost_center) {
            frappe.model.set_value(cdt, cdn, 'cost_center', frm.doc.custom_cost_center);
        }
    }
});