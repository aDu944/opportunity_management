// From ERPNext Client Script: Show Subtotals for Each Section in Quotations
// Doctype: Quotation | View: Form | Size: 6377 bytes
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
                row.item_code = 'TITLE-ROW';
                row.qty = 1;
                row.rate = 0;
                row.amount = 0;
                frm.refresh_field('items');
                
                // Calculate section totals if enabled
                if (frm.doc.custom_show_section_subtotals) {
                    calculate_section_totals(frm);
                }
                
                frappe.show_alert({
                    message: 'Title row added: ' + values.title_text,
                    indicator: 'green'
                });
            }, __('Add Section Title'), __('Add'));
        });
        
        // Style title rows and calculate totals
        setTimeout(function() {
            style_title_rows(frm);
            if (frm.doc.custom_show_section_subtotals) {
                calculate_section_totals(frm);
            }
        }, 100);
    },
    
    custom_show_section_subtotals: function(frm) {
        if (frm.doc.custom_show_section_subtotals) {
            calculate_section_totals(frm);
        } else {
            clear_section_totals(frm);
        }
        style_title_rows(frm);
    },
    
    validate: function(frm) {
        // Calculate section totals before save if enabled
        if (frm.doc.custom_show_section_subtotals) {
            calculate_section_totals(frm);
        }
    }
});

frappe.ui.form.on('Quotation Item', {
    custom_is_title_row: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.custom_is_title_row) {
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
    
    amount: function(frm, cdt, cdn) {
        if (frm.doc.custom_show_section_subtotals) {
            calculate_section_totals(frm);
        }
    },
    
    items_remove: function(frm) {
        if (frm.doc.custom_show_section_subtotals) {
            setTimeout(() => calculate_section_totals(frm), 100);
        }
    }
});

function calculate_section_totals(frm) {
    let sections = [];
    let current_section = null;
    
    // Group items by sections
    frm.doc.items.forEach((item, idx) => {
        if (item.custom_is_title_row) {
            // Start a new section
            if (current_section) {
                sections.push(current_section);
            }
            current_section = {
                title: item.custom_title_text || 'Untitled Section',
                title_row_idx: idx,
                items: [],
                total: 0
            };
        } else if (current_section) {
            // Add item to current section
            current_section.items.push(item);
            current_section.total += (item.amount || 0);
        }
    });
    
    // Don't forget the last section
    if (current_section) {
        sections.push(current_section);
    }
    
    // Store section totals for display
    frm.section_totals = sections;
    
    // Update the display
    style_title_rows(frm);
}

function clear_section_totals(frm) {
    frm.section_totals = [];
    style_title_rows(frm);
}

function style_title_rows(frm) {
    // Add custom CSS if not already added
    if (!document.getElementById('title-row-styles')) {
        var style = document.createElement('style');
        style.id = 'title-row-styles';
        style.innerHTML = `
            .grid-row[data-is-title="1"] {
                background-color: #f0f4f7 !important;
                font-weight: bold;
            }
            .grid-row[data-is-title="1"] .grid-static-col[data-fieldname="description"] {
                font-size: 14px;
                color: #2c3e50;
            }
            .section-total {
                font-size: 12px;
                color: #5e64ff;
                font-weight: normal;
                float: right;
                margin-right: 20px;
            }
        `;
        document.head.appendChild(style);
    }
    
    // Mark title rows and add section totals
    if (frm.fields_dict.items && frm.fields_dict.items.grid) {
        frm.fields_dict.items.grid.wrapper.find('.grid-row').each(function(idx) {
            var row_name = $(this).attr('data-name');
            var row_doc = locals['Quotation Item'][row_name];
            
            if (row_doc && row_doc.custom_is_title_row) {
                $(this).attr('data-is-title', '1');
                
                // Add section total if enabled
                if (frm.doc.custom_show_section_subtotals && frm.section_totals) {
                    let section = frm.section_totals.find(s => s.title_row_idx === idx);
                    if (section) {
                        let desc_field = $(this).find('.grid-static-col[data-fieldname="description"]');
                        desc_field.find('.section-total').remove(); // Remove any existing total
                        
                        if (section.total > 0) {
                            desc_field.append(`
                                <span class="section-total">
                                    Section Total: ${format_currency(section.total, frm.doc.currency)}
                                </span>
                            `);
                        }
                    }
                }
            }
        });
    }
}