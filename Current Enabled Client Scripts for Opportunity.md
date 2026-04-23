Title: Opportunity Nextcloud Button
frappe.ui.form.on('Opportunity', {
	refresh: function(frm) {
		// Only show button if opportunity is saved (has a name)
		if (frm.doc.name && !frm.doc.__islocal) {
			// Add custom button
			frm.add_custom_button(__('Create Nextcloud Folder'), function() {
				create_nextcloud_folder(frm);
			}, __('Actions'));
		}
	}
});

function create_nextcloud_folder(frm) {
	// Show loading indicator
	frappe.show_progress(__('Creating Folder'), 50, __('Creating Nextcloud folder...'));
	
	// Call server method
	frappe.call({
		method: 'nextcloud_integration.hooks.create_nextcloud_folder_manual',
		args: {
			opportunity_name: frm.doc.name
		},
		callback: function(r) {
			frappe.hide_progress();
			
			if (r.message && r.message.success) {
				// Show success message
				frappe.show_alert({
					message: __('Nextcloud folder created successfully'),
					indicator: 'green'
			}, 5);
				
				// Reload the form to show the new comment
				frm.reload_doc();
				
				// Optionally open the folder in a new tab
				if (r.message.folder_path) {
					frappe.msgprint({
						title: __('Success'),
						message: __('Folder created successfully!<br><br><a href="{0}" target="_blank">Open Folder in Nextcloud</a>', [r.message.folder_path]),
						indicator: 'green'
				});
			}
		} else {
			// Show error message
			const error_msg = r.message && r.message.error ? r.message.error : __('Failed to create folder');
			frappe.show_alert({
				message: error_msg,
				indicator: 'red'
		}, 10);
			
			frappe.msgprint({
				title: __('Error'),
				message: error_msg,
				indicator: 'red'
		});
		}
	},
	error: function(r) {
		frappe.hide_progress();
		frappe.show_alert({
			message: __('An error occurred while creating the folder'),
			indicator: 'red'
		}, 10);
	}
});
}


Title: Opportunity Excel Export Button
// Client Script for Opportunity DocType
// Download and Upload Items with proper Excel format

frappe.ui.form.on('Opportunity', {
    refresh: function(frm) {
        // Download button
        if (frm.doc.items && frm.doc.items.length > 0) {
            frm.add_custom_button(__('Download Items Excel'), function() {
                download_formatted_excel(frm);
            });
        }
        
        // Template download button
        frm.add_custom_button(__('Download Template'), function() {
            download_template();
        });
        
        // Upload button
        let can_upload = false;
        if (frappe.user.name === frm.doc.contact_person || 
            frappe.user.has_role(['System Manager', 'Sales Manager'])) {
            can_upload = true;
        }
        
        if (can_upload) {
            frm.add_custom_button(__('Upload Items from Excel'), function() {
                upload_items_dialog(frm);
            });
        }
    }
});

function download_formatted_excel(frm) {
    function cleanHTML(html) {
        if (!html) return '';
        let temp = document.createElement('div');
        temp.innerHTML = html;
        return temp.textContent || temp.innerText || '';
    }
    
    function formatNumber(num) {
        if (!num) return '0.00';
        return parseFloat(num).toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }
    
    // Use proper Excel XML format
    let xml = '<?xml version="1.0"?>';
    xml += '<?mso-application progid="Excel.Sheet"?>';
    xml += '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" ';
    xml += 'xmlns:o="urn:schemas-microsoft-com:office:office" ';
    xml += 'xmlns:x="urn:schemas-microsoft-com:office:excel" ';
    xml += 'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet" ';
    xml += 'xmlns:html="http://www.w3.org/TR/REC-html40">';
    
    // Styles
    xml += '<Styles>';
    xml += '<Style ss:ID="Header"><Font ss:Bold="1" ss:Size="11" ss:Color="#FFFFFF"/>';
    xml += '<Interior ss:Color="#4472C4" ss:Pattern="Solid"/>';
    xml += '<Alignment ss:Horizontal="Center" ss:Vertical="Center"/>';
    xml += '<Borders><Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="2"/>';
    xml += '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="2"/>';
    xml += '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1"/>';
    xml += '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/></Borders></Style>';
    
    xml += '<Style ss:ID="Title"><Font ss:Bold="1" ss:Size="16" ss:Color="#2c5282"/>';
    xml += '<Alignment ss:Horizontal="Center" ss:Vertical="Center"/></Style>';
    
    xml += '<Style ss:ID="SubTitle"><Font ss:Bold="1" ss:Size="11"/>';
    xml += '<Interior ss:Color="#E8F4F8" ss:Pattern="Solid"/></Style>';
    
    xml += '<Style ss:ID="Data"><Alignment ss:Vertical="Center"/>';
    xml += '<Borders><Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/></Borders></Style>';
    
    xml += '<Style ss:ID="DataEven"><Interior ss:Color="#F2F2F2" ss:Pattern="Solid"/>';
    xml += '<Alignment ss:Vertical="Center"/>';
    xml += '<Borders><Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/>';
    xml += '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1" ss:Color="#DDDDDD"/></Borders></Style>';
    
    xml += '<Style ss:ID="Number"><NumberFormat ss:Format="#,##0.00"/></Style>';
    xml += '</Styles>';
    
    // Worksheet
    xml += '<Worksheet ss:Name="RFQ">';
    xml += '<Table>';
    
    // Column widths (matching RFQ template)
    xml += '<Column ss:Width="80"/>';  // SN
    xml += '<Column ss:Width="230"/>'; // Short Description
    xml += '<Column ss:Width="230"/>'; // Full Description
    xml += '<Column ss:Width="100"/>'; // Manufacturer
    xml += '<Column ss:Width="100"/>'; // Part Number
    xml += '<Column ss:Width="80"/>';  // QTY
    xml += '<Column ss:Width="80"/>';  // UOM
    xml += '<Column ss:Width="100"/>'; // Unit Cost
    xml += '<Column ss:Width="100"/>'; // Total Cost
    
    // Title Row
   // xml += '<Row ss:Height="30">';
    // xml += '<Cell ss:MergeAcross="8" ss:StyleID="Title"><Data ss:Type="String">AL KHORA TRADING LLC - Quotation</Data></Cell>';
    // xml += '</Row>';
    
    // RFQ Number
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:StyleID="SubTitle"><Data ss:Type="String">RFQ Number:</Data></Cell>';
    xml += '<Cell ss:MergeAcross="7" ss:StyleID="SubTitle"><Data ss:Type="String">' + frm.doc.name + '</Data></Cell>';
    xml += '</Row>';
    
    // Customer
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:StyleID="SubTitle"><Data ss:Type="String">Customer:</Data></Cell>';
    xml += '<Cell ss:MergeAcross="7" ss:StyleID="SubTitle"><Data ss:Type="String">' + (frm.doc.party_name || '') + '</Data></Cell>';
    xml += '</Row>';
    
    // Date
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:StyleID="SubTitle"><Data ss:Type="String">Date:</Data></Cell>';
    xml += '<Cell ss:MergeAcross="7" ss:StyleID="SubTitle"><Data ss:Type="String">' + frappe.datetime.str_to_user(frm.doc.transaction_date || frappe.datetime.nowdate()) + '</Data></Cell>';
    xml += '</Row>';
    
    // Empty row
    xml += '<Row ss:Height="10"></Row>';
    
    // Header Row
    xml += '<Row ss:Height="35">';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">SN</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Short Description</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Full Description</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Manufacturer</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Part Number</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">QTY</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">UOM</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Unit Cost</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Total Cost</Data></Cell>';
    xml += '</Row>';
    
    // Data Rows
    frm.doc.items.forEach(function(item, index) {
        let styleID = (index % 2 === 0) ? 'DataEven' : 'Data';
        xml += '<Row ss:Height="25">';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="Number">' + (index + 1) + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="String">' + cleanHTML(item.description || '') + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="String">' + cleanHTML(item.custom_tech_desc || '') + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="String">' + (item.custom_manufacturer || '') + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="String">' + (item.custom_part_number || '') + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="Number">' + (item.qty || 0) + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="String">' + (item.uom || '') + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="Number">' + (item.rate || 0) + '</Data></Cell>';
        xml += '<Cell ss:StyleID="' + styleID + '"><Data ss:Type="Number">' + (item.amount || 0) + '</Data></Cell>';
        xml += '</Row>';
    });
    
    // Total Row
    xml += '<Row ss:Height="10"></Row>';
    xml += '<Row ss:Height="30">';
    xml += '<Cell ss:MergeAcross="6" ss:StyleID="SubTitle"><Data ss:Type="String">Grand Total:</Data></Cell>';
    xml += '<Cell ss:MergeAcross="1" ss:StyleID="SubTitle"><Data ss:Type="Number">' + (frm.doc.total || 0) + '</Data></Cell>';
    xml += '</Row>';
    
    xml += '</Table></Worksheet></Workbook>';
    
    // Create proper Excel file
    let blob = new Blob([xml], { 
        type: 'application/vnd.ms-excel'
    });
    
    let filename = 'RFQ_' + frm.doc.name + '_' + frappe.datetime.nowdate() + '.xls';
    
    let link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    frappe.show_alert({ message: __('Excel file downloaded!'), indicator: 'green' });
}

function download_template() {
    let xml = '<?xml version="1.0"?>';
    xml += '<?mso-application progid="Excel.Sheet"?>';
    xml += '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" ';
    xml += 'xmlns:o="urn:schemas-microsoft-com:office:office" ';
    xml += 'xmlns:x="urn:schemas-microsoft-com:office:excel" ';
    xml += 'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet" ';
    xml += 'xmlns:html="http://www.w3.org/TR/REC-html40">';
    
    // Styles
    xml += '<Styles>';
    xml += '<Style ss:ID="Header"><Font ss:Bold="1" ss:Size="11" ss:Color="#FFFFFF"/>';
    xml += '<Interior ss:Color="#4472C4" ss:Pattern="Solid"/>';
    xml += '<Alignment ss:Horizontal="Center" ss:Vertical="Center"/></Style>';
    
    xml += '<Style ss:ID="Title"><Font ss:Bold="1" ss:Size="16" ss:Color="#2c5282"/>';
    xml += '<Alignment ss:Horizontal="Center" ss:Vertical="Center"/></Style>';
    
    xml += '<Style ss:ID="Instructions"><Font ss:Bold="1" ss:Color="#FFFFFF"/>';
    xml += '<Interior ss:Color="#7c3aed" ss:Pattern="Solid"/></Style>';
    
    xml += '<Style ss:ID="Sample"><Interior ss:Color="#FFF9E6" ss:Pattern="Solid"/>';
    xml += '<Font ss:Italic="1" ss:Color="#666666"/></Style>';
    xml += '</Styles>';
    
    xml += '<Worksheet ss:Name="Template">';
    xml += '<Table>';
    
    // Column widths
    xml += '<Column ss:Width="80"/>';
    xml += '<Column ss:Width="230"/>';
    xml += '<Column ss:Width="230"/>';
    xml += '<Column ss:Width="100"/>';
    xml += '<Column ss:Width="100"/>';
    xml += '<Column ss:Width="80"/>';
    xml += '<Column ss:Width="80"/>';
    xml += '<Column ss:Width="100"/>';
    xml += '<Column ss:Width="100"/>';
    
    // Title
    //xml += '<Row ss:Height="30">';
    //xml += '<Cell ss:MergeAcross="8" ss:StyleID="Title"><Data ss:Type="String">AL KHORA TRADING LLC - RFQ Template</Data></Cell>';
    //xml += '</Row>';
    
    // Instructions
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:MergeAcross="8" ss:StyleID="Instructions"><Data ss:Type="String">INSTRUCTIONS: Fill in your items below and upload</Data></Cell>';
    xml += '</Row>';
    
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:MergeAcross="8" ss:StyleID="Instructions"><Data ss:Type="String">Do NOT modify the header row (blue row)</Data></Cell>';
    xml += '</Row>';
    
    xml += '<Row ss:Height="10"></Row>';
    
    // Header
    xml += '<Row ss:Height="35">';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">SN</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Short Description</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Full Description</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Manufacturer</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Part Number</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">QTY</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">UOM</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Unit Cost</Data></Cell>';
    xml += '<Cell ss:StyleID="Header"><Data ss:Type="String">Total Cost</Data></Cell>';
    xml += '</Row>';
    
    // Sample row
    xml += '<Row ss:Height="25">';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="Number">1</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="String">Impact Wrench</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="String">20V Cordless Impact Wrench with LED</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="String">INGCO</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="String">CIWLI2001</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="Number">10</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="String">Nos</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="Number">0</Data></Cell>';
    xml += '<Cell ss:StyleID="Sample"><Data ss:Type="Number">0</Data></Cell>';
    xml += '</Row>';
    
    // Empty rows
    for (let i = 2; i <= 20; i++) {
        xml += '<Row ss:Height="25">';
        xml += '<Cell><Data ss:Type="Number">' + i + '</Data></Cell>';
        xml += '<Cell></Cell><Cell></Cell><Cell></Cell><Cell></Cell>';
        xml += '<Cell></Cell><Cell></Cell><Cell></Cell><Cell></Cell>';
        xml += '</Row>';
    }
    
    xml += '</Table></Worksheet></Workbook>';
    
    let blob = new Blob([xml], { type: 'application/vnd.ms-excel' });
    let filename = 'RFQ_Template_' + frappe.datetime.nowdate() + '.xls';
    
    let link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    frappe.show_alert({ message: __('Template downloaded!'), indicator: 'green' });
}

function upload_items_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Upload Items from Excel'),
        fields: [
            {
                fieldtype: 'HTML',
                options: '<div style="padding: 15px; background: #e0f2fe; border-radius: 8px; margin-bottom: 20px;"><h4 style="margin-top: 0;">Before uploading:</h4><ol style="margin-bottom: 0;"><li>Fill the template with your items</li><li>Keep the header row unchanged</li><li>Save as Excel file (.xls or .xlsx)</li></ol></div>'
            },
            {
                fieldname: 'file',
                fieldtype: 'Attach',
                label: __('Select Excel File'),
                reqd: 1
            },
            {
                fieldname: 'clear_existing',
                fieldtype: 'Check',
                label: __('Clear existing items before import'),
                default: 0
            }
        ],
        primary_action_label: __('Upload'),
        primary_action: function(values) {
            if (!values.file) {
                frappe.msgprint(__('Please select a file'));
                return;
            }
            
            d.hide();
            frappe.show_alert({ message: __('Processing file...'), indicator: 'blue' });
            
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'File',
                    filters: { file_url: values.file },
                    fieldname: ['file_url', 'file_name']
                },
                callback: function(r) {
                    if (r.message) {
                        process_uploaded_file(frm, values.file, values.clear_existing);
                    }
                }
            });
        }
    });
    
    d.show();
}

function process_uploaded_file(frm, file_url, clear_existing) {
    fetch(file_url)
        .then(response => response.arrayBuffer())
        .then(data => {
            if (typeof XLSX === 'undefined') {
                let script = document.createElement('script');
                script.src = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js';
                script.onload = function() {
                    parse_excel_data(frm, data, clear_existing);
                };
                document.head.appendChild(script);
            } else {
                parse_excel_data(frm, data, clear_existing);
            }
        })
        .catch(error => {
            frappe.msgprint({
                title: __('Error'),
                message: __('Failed to read file: ') + error.message,
                indicator: 'red'
            });
        });
}

function parse_excel_data(frm, data, clear_existing) {
    try {
        let workbook = XLSX.read(data, { type: 'array' });
        let sheet = workbook.Sheets[workbook.SheetNames[0]];
        let rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '' });
        
        let header_row_index = -1;
        for (let i = 0; i < Math.min(10, rows.length); i++) {
            let row_str = rows[i].join('').toLowerCase();
            if (row_str.includes('description') || row_str.includes('sn')) {
                header_row_index = i;
                break;
            }
        }
        
        if (header_row_index === -1) {
            frappe.msgprint(__('Could not find header row in Excel file'));
            return;
        }
        
        let headers = rows[header_row_index].map(h => String(h).toLowerCase().trim());
        
        if (clear_existing) {
            frm.clear_table('items');
        }
        
        let imported_count = 0;
        let skipped_count = 0;
        
        for (let i = header_row_index + 1; i < rows.length; i++) {
            let row = rows[i];
            
            if (!row || row.every(cell => !cell || String(cell).trim() === '')) {
                continue;
            }
            
            let first_cell = String(row[0] || '').toLowerCase();
            if (first_cell.includes('instruction') || first_cell.includes('sample')) {
                continue;
            }
            
            let short_desc = get_cell_value(row, headers, ['short description', 'description']) || '';
            let full_desc = get_cell_value(row, headers, ['full description', 'technical description']) || '';
            let qty = parseFloat(get_cell_value(row, headers, ['qty', 'quantity'])) || 0;
            
            if ((!short_desc && !full_desc) || qty <= 0) {
                skipped_count++;
                continue;
            }
            
            let item = frm.add_child('items');
            item.description = short_desc;
            item.custom_tech_desc = full_desc;
            item.custom_manufacturer = get_cell_value(row, headers, ['manufacturer', 'mfr']) || '';
            item.custom_part_number = get_cell_value(row, headers, ['part number', 'part no', 'p/n']) || '';
            item.qty = qty;
            item.uom = get_cell_value(row, headers, ['uom', 'unit']) || 'Nos';
            
            let rate_value = get_cell_value(row, headers, ['unit cost', 'rate', 'price']);
            item.rate = (rate_value && rate_value !== '' && !isNaN(parseFloat(rate_value))) ? parseFloat(rate_value) : 0;
            item.amount = item.qty * item.rate;
            
            imported_count++;
        }
        
        frm.refresh_field('items');
        
        frappe.msgprint({
            title: __('Import Successful'),
            message: __('Imported ' + imported_count + ' items. ' + (skipped_count > 0 ? 'Skipped ' + skipped_count + ' rows. ' : '') + 'Please review and save.'),
            indicator: 'green',
            primary_action: {
                label: __('Save Document'),
                action: function() {
                    frm.save();
                }
            }
        });
        
    } catch (error) {
        frappe.msgprint({
            title: __('Error'),
            message: __('Failed to parse Excel file: ') + error.message,
            indicator: 'red'
        });
    }
}

function get_cell_value(row, headers, column_names) {
    for (let name of column_names) {
        let index = headers.indexOf(name.toLowerCase().trim());
        if (index !== -1 && row[index] !== undefined && row[index] !== '') {
            return String(row[index]).trim();
        }
    }
    return '';
}

Title: Opportunity Title
frappe.ui.form.on('Opportunity', {
    before_save(frm) {
        if (frm.doc.customer_name === "General - عامة (USD)" || frm.doc.customer_name === "General - عامة (IQD)") {
            frm.doc.title = frm.doc.custom_man_customer_name;
        } else {
            frm.doc.title = frm.doc.customer_name;
        }
    }
});


Title: Opportunity Status
frappe.ui.form.on('Opportunity', {
    refresh: function(frm) {
        // Keep your existing code for the Status field visibility
        if (!frappe.user.has_role('System Manager')) {
            frm.set_df_property('status', 'hidden', 1);
        } else {
            frm.set_df_property('status', 'hidden', 0);
        }
        
        // Add new code to fetch and sum Quotation totals with currency handling
        fetch_quotation_values(frm);
    }
});

function fetch_quotation_values(frm) {
    if(frm.doc.name) {
        // Query to find linked Quotations with currency information
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Quotation',
                filters: {
                    'opportunity': frm.doc.name,
                    'docstatus': ['!=', 2]  // Not cancelled
                },
                fields: ['name', 'grand_total', 'currency', 'conversion_rate']
            },
            callback: function(response) {
                if (response.message && response.message.length > 0) {
                    // Get all quotations
                    let quotations = response.message;
                    
                    // Get the opportunity's currency
                    let opportunityCurrency = frm.doc.currency || frappe.defaults.get_global_default('currency');
                    
                    // Calculate the sum of all quotation values converted to opportunity currency
                    let totalValue = 0;
                    let quotationNames = [];
                    let differentCurrencyFound = false;
                    let currenciesFound = new Set();
                    
                    // Process each quotation
                    quotations.forEach(function(quotation) {
                        quotationNames.push(quotation.name);
                        currenciesFound.add(quotation.currency);
                        
                        if (quotation.currency === opportunityCurrency) {
                            // Same currency, add directly
                            totalValue += quotation.grand_total;
                        } else {
                            differentCurrencyFound = true;
                            
                            // Need to convert the currency
                            // First check if we have conversion_rate in the quotation
                            if (quotation.conversion_rate) {
                                // If quotation already has conversion rate to base currency
                                // We'll need to convert from base currency to opportunity currency
                                let baseValue = quotation.grand_total * quotation.conversion_rate;
                                
                                // Now get exchange rate from base currency to opportunity currency
                                get_exchange_rate(frm, baseValue, quotation, opportunityCurrency, totalValue, function(newTotal) {
                                    totalValue = newTotal;
                                    updateOpportunityValue(frm, totalValue, quotations, differentCurrencyFound, currenciesFound);
                                });
                                return; // Skip the automatic update since we'll do it in the callback
                            } else {
                                // No conversion rate available, need to fetch it
                                get_exchange_rate(frm, quotation.grand_total, quotation, opportunityCurrency, totalValue, function(newTotal) {
                                    totalValue = newTotal;
                                    updateOpportunityValue(frm, totalValue, quotations, differentCurrencyFound, currenciesFound);
                                });
                                return; // Skip the automatic update since we'll do it in the callback
                            }
                        }
                    });
                    
                    // Only update immediately if no currency conversion was needed
                    if (!differentCurrencyFound) {
                        updateOpportunityValue(frm, totalValue, quotations, differentCurrencyFound, currenciesFound);
                    }
                }
            }
        });
    }
}

function get_exchange_rate(frm, amount, quotation, targetCurrency, currentTotal, callback) {
    frappe.call({
        method: "erpnext.setup.utils.get_exchange_rate",
        args: {
            from_currency: quotation.currency,
            to_currency: targetCurrency,
            transaction_date: frappe.datetime.nowdate()
        },
        callback: function(r) {
            if (r.message) {
                let exchangeRate = r.message;
                let convertedAmount = amount * exchangeRate;
                callback(currentTotal + convertedAmount);
            }
        }
    });
}

function updateOpportunityValue(frm, totalValue, quotations, differentCurrencyFound, currenciesFound) {
    // Update the opportunity value
    frm.set_value('opportunity_amount', totalValue);
    
    // Add a button to view related quotations
    frm.add_custom_button(__('View Related Quotations (' + quotations.length + ')'), function() {
        frappe.route_options = {
            'opportunity': frm.doc.name
        };
        frappe.set_route('List', 'Quotation');
    });
    
    // Prepare notification message
    let currencyInfo = '';
    if (differentCurrencyFound) {
        currencyInfo = ' (converted from ' + Array.from(currenciesFound).join(', ') + ')';
    }
    
    // Show a notification
    frappe.show_alert({
        message: __('Opportunity value updated to sum of ' + quotations.length + 
                   ' quotations: ' + format_currency(totalValue, frm.doc.currency) + 
                   currencyInfo),
        indicator: 'green'
    }, 7);
}