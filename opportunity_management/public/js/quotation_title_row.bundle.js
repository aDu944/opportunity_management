// From ERPNext Client Script: Quotation Title Row
// Doctype: Quotation | View: Form | Size: 5284 bytes
// SOLUTION 1: Create a dedicated "Title Row" item in your Item Master
// Go to Item List > New Item
// Item Code: TITLE-ROW (or any code you prefer)
// Item Name: Section Title
// Item Group: (your default group)
// Stock UOM: Nos
// Is Stock Item: Unchecked
// Is Sales Item: Checked
// Default Price List Rate: 0 (or don't set any price list)

// Then update your Client Script to use this item:

frappe.ui.form.on('Quotation', {
    refresh: function(frm) {
        // Add custom button in toolbar
        frm.add_custom_button(__('Add Title Row'), function() {
            frappe.prompt([
                {
                    label: 'Section Title',
                    fieldname: 'title_text',
                    fieldtype: 'Data',
                    reqd: 1
                }
            ], function(values) {
                let row = frm.add_child('items');
                row.custom_is_title_row = 1;
                row.custom_title_text = values.title_text;
                row.description = values.title_text;
                row.item_code = 'TITLE-ROW'; // Use the dedicated title row item
                row.qty = 1; // Set qty to 1 to satisfy mandatory requirement
                row.rate = 0; // Override any default rate
                row.amount = 0;
                frm.refresh_field('items');
                
                frappe.show_alert({
                    message: 'Title row added: ' + values.title_text,
                    indicator: 'green'
                });
            }, __('Add Section Title'), __('Add'));
        });
        
        // Style title rows after refresh
        setTimeout(function() {
            style_title_rows(frm);
        }, 100);
    }
});

frappe.ui.form.on('Quotation Item', {
    custom_is_title_row: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.custom_is_title_row) {
            // Set mandatory fields with appropriate values
            frappe.model.set_value(cdt, cdn, 'item_code', 'TITLE-ROW');
            frappe.model.set_value(cdt, cdn, 'qty', 1);
            frappe.model.set_value(cdt, cdn, 'rate', 0);
            frappe.model.set_value(cdt, cdn, 'amount', 0);
            frappe.model.set_value(cdt, cdn, 'description', row.custom_title_text || '');
        }
    },
    
    custom_title_text: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.custom_is_title_row) {
            frappe.model.set_value(cdt, cdn, 'description', row.custom_title_text);
        }
    },
    
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // If it's a title row and someone tries to change the item code
        if (row.custom_is_title_row && row.item_code !== 'TITLE-ROW') {
            frappe.model.set_value(cdt, cdn, 'item_code', 'TITLE-ROW');
            frappe.model.set_value(cdt, cdn, 'rate', 0);
            frappe.msgprint(__('Title rows must use TITLE-ROW item code'));
        }
    },
    
    rate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // Force rate to 0 for title rows
        if (row.custom_is_title_row && row.rate !== 0) {
            frappe.model.set_value(cdt, cdn, 'rate', 0);
            frappe.model.set_value(cdt, cdn, 'amount', 0);
        }
    }
});

// ALTERNATIVE SOLUTION 2: Override the rate fetch for your existing item
// If you want to keep using item 101:

frappe.ui.form.on('Quotation Item', {
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        
        // Override rate for title rows using item 101
        if (row.custom_is_title_row && row.item_code === '101') {
            setTimeout(function() {
                frappe.model.set_value(cdt, cdn, 'rate', 0);
                frappe.model.set_value(cdt, cdn, 'amount', 0);
            }, 100); // Small delay to override the fetched rate
        }
    },
    
    rate: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        // Force rate to 0 for title rows
        if (row.custom_is_title_row && row.rate !== 0) {
            frappe.model.set_value(cdt, cdn, 'rate', 0);
            frappe.model.set_value(cdt, cdn, 'amount', 0);
        }
    }
});

// Style function remains the same
function style_title_rows(frm) {
    // Add custom CSS if not already added
    if (!document.getElementById('title-row-styles')) {
        var style = document.createElement('style');
        style.id = 'title-row-styles';
        style.innerHTML = `
            .grid-row[data-is-title="1"] {
                background-color: #fff7d1 !important;
                font-weight: bold;
            }
            .grid-row[data-is-title="1"] .grid-static-col[data-fieldname="description"] {
                font-size: 14px;
                color: #2c3e50;
            }
        `;
        document.head.appendChild(style);
    }
    
    // Mark title rows
    if (frm.fields_dict.items && frm.fields_dict.items.grid) {
        frm.fields_dict.items.grid.wrapper.find('.grid-row').each(function() {
            var row_name = $(this).attr('data-name');
            var row_doc = locals['Quotation Item'][row_name];
            if (row_doc && row_doc.custom_is_title_row) {
                $(this).attr('data-is-title', '1');
            }
        });
    }
}