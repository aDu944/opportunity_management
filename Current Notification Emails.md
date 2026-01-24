Notification #1:
Document Type: ToDo

Subject: New Opportunity Assigned: {{ doc.reference_name }}
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Opportunity Assigned</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {font-family: Arial, Helvetica, sans-serif !important;}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; min-width: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; background-color: #f5f7fa; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f5f7fa;">
        <!-- Email container -->
        <tr>
            <td align="center" style="padding: 20px 15px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 650px; border-collapse: collapse; background-color: #ffffff; border-radius: 12px; box-shadow: 0 10px 25px rgba(64,224,208,0.15); overflow: hidden;">
                    <!-- Header Banner -->
                    <tr>
                        <td align="center" style="background-color: #40E0D0; padding: 25px 20px;">
                            <h1 style="color: #ffffff; margin: 0; font-weight: 600; font-size: 24px;">New Opportunity Assigned</h1>
                            <p style="color: #e6ffe6; margin: 10px 0 0 0; font-size: 16px;">Opportunity ID: #{{ doc.reference_name }}</p>
                        </td>
                    </tr>
                    
                    <!-- Content Area -->
                    <tr>
                        <td style="padding: 30px 20px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 15px;">
                                        Dear {{ frappe.get_doc("User", doc.allocated_to).full_name or doc.allocated_to }},
                                    </td>
                                </tr>
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 20px;">
                                        A new opportunity has been assigned to you in the ERP system. Please review the details below and prepare your quotation accordingly.
                                    </td>
                                </tr>
                                
                                <!-- Opportunity Info Card -->
                                {% set opportunity = frappe.get_doc("Opportunity", doc.reference_name) %}
                                {% set customer_display = opportunity.custom_man_customer_name if (opportunity.party_name == "General - عامة (USD)" or opportunity.party_name == "General - عامة (IQD)") and opportunity.custom_man_customer_name else opportunity.party_name %}
                                
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8f9fa; border-left: 4px solid #40E0D0; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 20px;">
                                                    <p style="color: #555; margin: 0 0 15px 0; font-size: 15px;">Assigned By: <span style="color: #40E0D0; font-weight: 600;">{{ frappe.get_fullname(doc.modified_by) }}</span></p>
                                                    
                                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px; width: 40%;">Customer</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ customer_display or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Opportunity Type</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.opportunity_type or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Opportunity No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.name or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_no or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender Title</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_title or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Expected Closing</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #FF0000; font-weight: 700; font-size: 14px;">{{ frappe.utils.formatdate(opportunity.expected_closing) if opportunity.expected_closing else "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; color: #555; font-size: 14px;">Status</td>
                                                            <td style="padding: 8px 0; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.status }}</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Tender Documents/Attachments Section -->
                                {% set attachments = frappe.get_all('File', filters={'attached_to_doctype': 'Opportunity', 'attached_to_name': opportunity.name}, fields=['file_name', 'file_url']) %}
                                {% if attachments %}
                                <tr>
                                    <td style="padding: 0 0 10px 0;">
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">📎 Tender Documents & Attachments:</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #e8f5e9; border-left: 4px solid #4caf50; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    {% for attachment in attachments %}
                                                    <p style="margin: 8px 0;">
                                                        <a href="{{ frappe.utils.get_url() }}{{ attachment.file_url }}" style="color: #2e7d32; text-decoration: none; font-weight: 600; font-size: 14px;" target="_blank">
                                                            📄 {{ attachment.file_name }}
                                                        </a>
                                                    </p>
                                                    {% endfor %}
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                {% endif %}
                                
                                <!-- Items to Quote Section -->
                                {% if opportunity.items %}
                                <tr>
                                    <td style="padding: 0 0 10px 0;">
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">Items to be Quoted:</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #ffffff; border: 1px solid #e9ecef; border-radius: 6px; overflow: hidden;">
                                            <tr style="background-color: #40E0D0;">
                                                <th style="padding: 12px 15px; text-align: left; color: #ffffff; font-weight: 600; font-size: 14px; border-bottom: 2px solid #00CED1;">Item Code</th>
                                                <th style="padding: 12px 15px; text-align: left; color: #ffffff; font-weight: 600; font-size: 14px; border-bottom: 2px solid #00CED1;">Description</th>
                                                <th style="padding: 12px 15px; text-align: center; color: #ffffff; font-weight: 600; font-size: 14px; border-bottom: 2px solid #00CED1;">Qty</th>
                                                <th style="padding: 12px 15px; text-align: left; color: #ffffff; font-weight: 600; font-size: 14px; border-bottom: 2px solid #00CED1;">UOM</th>
                                            </tr>
                                            {% for item in opportunity.items %}
                                            <tr style="{% if loop.index is odd %}background-color: #f8f9fa;{% endif %}">
                                                <td style="padding: 10px 15px; color: #333; font-size: 14px; border-bottom: 1px solid #e9ecef;">{{ item.item_code }}</td>
                                                <td style="padding: 10px 15px; color: #555; font-size: 13px; border-bottom: 1px solid #e9ecef;">{{ item.description or item.item_name or "N/A" }}</td>
                                                <td style="padding: 10px 15px; color: #333; font-weight: 600; font-size: 14px; text-align: center; border-bottom: 1px solid #e9ecef;">{{ item.qty }}</td>
                                                <td style="padding: 10px 15px; color: #555; font-size: 14px; border-bottom: 1px solid #e9ecef;">{{ item.uom or "N/A" }}</td>
                                            </tr>
                                            {% endfor %}
                                        </table>
                                    </td>
                                </tr>
                                {% endif %}
                                
                                {% if opportunity.notes %}
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #fff3cd; border-left: 4px solid #ffc107; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    <p style="color: #856404; margin: 0 0 8px 0; font-weight: 600; font-size: 14px;">Additional Notes:</p>
                                                    <p style="color: #856404; margin: 0; font-size: 14px;">{{ opportunity.notes }}</p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                {% endif %}
                                
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 25px;">
                                        Please prepare your quotation and ensure timely completion before the closing date.
                                    </td>
                                </tr>
                                
                                <!-- CTA Button - UPDATED TO LINK TO TODO -->
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ frappe.utils.get_url() }}/app/todo/{{ doc.name }}" style="height:45px;v-text-anchor:middle;width:200px;" arcsize="50%" stroke="f" fillcolor="#40E0D0">
                                        <w:anchorlock/>
                                        <center>
                                        <![endif]-->
                                        <a href="{{ frappe.utils.get_url() }}/app/todo/{{ doc.name }}" style="display: inline-block; background-color: #40E0D0; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 25px; border-radius: 50px; font-size: 16px; box-shadow: 0 4px 10px rgba(64,224,208,0.3); mso-padding-alt: 0; text-underline-color: #40E0D0;"><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%;mso-text-raise:20pt">&nbsp;</i><![endif]--><span style="mso-text-raise:10pt;">View Task</span><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%">&nbsp;</i><![endif]--></a>
                                        <!--[if mso]>
                                        </center>
                                        </v:roundrect>
                                        <![endif]-->
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="padding-top: 10px;">
                                        <p style="color: #444; margin: 0 0 5px 0; font-size: 16px;">Best regards,</p>
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">ALKHORA for General Trading Ltd</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                            <p style="color: #6c757d; margin: 0; font-size: 13px;">This is an automated message from your ERP system.</p>
                            <p style="color: #6c757d; margin: 5px 0 0 0; font-size: 13px;">Please do not reply to this email.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>



Notification #2:
Document Type: ToDo

Subject: Reminder - Opportunity {{ doc.reference_name }} Closing in 3 days

<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Opportunity Reminder - 3 Days</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {font-family: Arial, Helvetica, sans-serif !important;}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; min-width: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; background-color: #f5f7fa; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f5f7fa;">
        <!-- Email container -->
        <tr>
            <td align="center" style="padding: 20px 15px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 650px; border-collapse: collapse; background-color: #ffffff; border-radius: 12px; box-shadow: 0 10px 25px rgba(255,193,7,0.15); overflow: hidden;">
                    <!-- Header Banner -->
                    <tr>
                        <td align="center" style="background-color: #ffc107; padding: 25px 20px;">
                            <h1 style="color: #ffffff; margin: 0; font-weight: 600; font-size: 24px;">Important Reminder</h1>
                            <p style="color: #fff3cd; margin: 10px 0 0 0; font-size: 16px;">Opportunity ID: #{{ doc.reference_name }}</p>
                        </td>
                    </tr>
                    
                    <!-- Content Area -->
                    <tr>
                        <td style="padding: 30px 20px;">
                            {% set opportunity = frappe.get_doc("Opportunity", doc.reference_name) %}
                            {% set customer_display = opportunity.custom_man_customer_name if (opportunity.party_name == "General - عامة (USD)" or opportunity.party_name == "General - عامة (IQD)") and opportunity.custom_man_customer_name else opportunity.party_name %}
                            
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 15px;">
                                        Dear {{ frappe.get_doc("User", doc.allocated_to).full_name or doc.allocated_to }},
                                    </td>
                                </tr>
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 20px;">
                                        This is an important reminder! Your assigned opportunity is closing in <strong>3 days</strong>.
                                    </td>
                                </tr>
                                
                                <!-- Urgency Alert Box -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #fff3cd; border-left: 4px solid #ffc107; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    <p style="color: #856404; margin: 0; font-weight: 700; font-size: 16px;">⏰ Closing in 3 days - Action Required</p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Opportunity Info Card -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8f9fa; border-left: 4px solid #ffc107; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 20px;">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px; width: 40%;">Opportunity No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #ffc107; font-weight: 700; font-size: 14px;">{{ opportunity.name }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Customer</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ customer_display or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Opportunity Type</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.opportunity_type or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_no or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender Title</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_title or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Expected Closing</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #FF0000; font-weight: 700; font-size: 14px;">{{ frappe.utils.formatdate(opportunity.expected_closing) }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; color: #555; font-size: 14px;">Status</td>
                                                            <td style="padding: 8px 0; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.status }}</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 25px;">
                                        Please ensure you complete your quotation and follow up accordingly.
                                    </td>
                                </tr>
                                
                                <!-- CTA Button -->
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="height:45px;v-text-anchor:middle;width:230px;" arcsize="50%" stroke="f" fillcolor="#ff9800">
                                        <w:anchorlock/>
                                        <center>
                                        <![endif]-->
                                        <a href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="display: inline-block; background-color: #ff9800; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 25px; border-radius: 50px; font-size: 16px; box-shadow: 0 4px 10px rgba(255,152,0,0.3); mso-padding-alt: 0; text-underline-color: #ff9800;"><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%;mso-text-raise:20pt">&nbsp;</i><![endif]--><span style="mso-text-raise:10pt;">Take Action Now</span><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%">&nbsp;</i><![endif]--></a>
                                        <!--[if mso]>
                                        </center>
                                        </v:roundrect>
                                        <![endif]-->
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="padding-top: 10px;">
                                        <p style="color: #444; margin: 0 0 5px 0; font-size: 16px;">Best regards,</p>
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">ALKHORA for General Trading Ltd</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                            <p style="color: #6c757d; margin: 0; font-size: 13px;">This is an automated reminder from your ERP system.</p>
                            <p style="color: #6c757d; margin: 5px 0 0 0; font-size: 13px;">Please do not reply to this email.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>

Notification #3:
Document Type: ToDo

Subject: Urgent Reminder - Opportunity {{ doc.reference_name }} Closing in 1 days

<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Opportunity Reminder - 1 Day</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {font-family: Arial, Helvetica, sans-serif !important;}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; min-width: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; background-color: #f5f7fa; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f5f7fa;">
        <!-- Email container -->
        <tr>
            <td align="center" style="padding: 20px 15px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 650px; border-collapse: collapse; background-color: #ffffff; border-radius: 12px; box-shadow: 0 10px 25px rgba(255,107,107,0.15); overflow: hidden;">
                    <!-- Header Banner -->
                    <tr>
                        <td align="center" style="background-color: #ff6b6b; padding: 25px 20px;">
                            <h1 style="color: #ffffff; margin: 0; font-weight: 600; font-size: 24px;">Urgent Reminder</h1>
                            <p style="color: #ffe6e6; margin: 10px 0 0 0; font-size: 16px;">Opportunity ID: #{{ doc.reference_name }}</p>
                        </td>
                    </tr>
                    
                    <!-- Content Area -->
                    <tr>
                        <td style="padding: 30px 20px;">
                            {% set opportunity = frappe.get_doc("Opportunity", doc.reference_name) %}
                            {% set customer_display = opportunity.custom_man_customer_name if (opportunity.party_name == "General - عامة (USD)" or opportunity.party_name == "General - عامة (IQD)") and opportunity.custom_man_customer_name else opportunity.party_name %}
                            
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 15px;">
                                        Dear {{ frappe.get_doc("User", doc.allocated_to).full_name or doc.allocated_to }},
                                    </td>
                                </tr>
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 20px;">
                                        <strong>URGENT:</strong> Your assigned opportunity is closing <strong>TOMORROW</strong>! Please take immediate action.
                                    </td>
                                </tr>
                                
                                <!-- Urgency Alert Box -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8d7da; border-left: 4px solid #dc3545; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    <p style="color: #721c24; margin: 0; font-weight: 700; font-size: 16px;">⏰ Closing Tomorrow - Immediate Action Required!</p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Opportunity Info Card -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8f9fa; border-left: 4px solid #ff6b6b; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 20px;">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px; width: 40%;">Opportunity No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #ff6b6b; font-weight: 700; font-size: 14px;">{{ opportunity.name }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Customer</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ customer_display or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Opportunity Type</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.opportunity_type or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_no or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender Title</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_title or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Expected Closing</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #FF0000; font-weight: 700; font-size: 14px;">{{ frappe.utils.formatdate(opportunity.expected_closing) }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; color: #555; font-size: 14px;">Status</td>
                                                            <td style="padding: 8px 0; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.status }}</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 25px;">
                                        Please ensure you complete your quotation and follow up accordingly.
                                    </td>
                                </tr>
                                
                                <!-- CTA Button -->
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="height:45px;v-text-anchor:middle;width:230px;" arcsize="50%" stroke="f" fillcolor="#dc3545">
                                        <w:anchorlock/>
                                        <center>
                                        <![endif]-->
                                        <a href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="display: inline-block; background-color: #dc3545; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 25px; border-radius: 50px; font-size: 16px; box-shadow: 0 4px 10px rgba(220,53,69,0.3); mso-padding-alt: 0; text-underline-color: #dc3545;"><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%;mso-text-raise:20pt">&nbsp;</i><![endif]--><span style="mso-text-raise:10pt;">Take Action Now</span><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%">&nbsp;</i><![endif]--></a>
                                        <!--[if mso]>
                                        </center>
                                        </v:roundrect>
                                        <![endif]-->
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="padding-top: 10px;">
                                        <p style="color: #444; margin: 0 0 5px 0; font-size: 16px;">Best regards,</p>
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">ALKHORA for General Trading Ltd</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                            <p style="color: #6c757d; margin: 0; font-size: 13px;">This is an automated reminder from your ERP system.</p>
                            <p style="color: #6c757d; margin: 5px 0 0 0; font-size: 13px;">Please do not reply to this email.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>

Notification #4:
Document Type: ToDo

Subject: 🚨 CRITICAL ALERT 🚨 Opportunity {{ doc.reference_name }} Closing in 0 days

<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Opportunity Reminder - Closing Today</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {font-family: Arial, Helvetica, sans-serif !important;}
    </style>
    <![endif]-->
</head>
<body style="margin: 0; padding: 0; min-width: 100%; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; background-color: #f5f7fa; -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f5f7fa;">
        <!-- Email container -->
        <tr>
            <td align="center" style="padding: 20px 15px;">
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 650px; border-collapse: collapse; background-color: #ffffff; border-radius: 12px; box-shadow: 0 10px 25px rgba(220,53,69,0.25); overflow: hidden;">
                    <!-- Header Banner -->
                    <tr>
                        <td align="center" style="background-color: #dc3545; padding: 25px 20px;">
                            <h1 style="color: #ffffff; margin: 0; font-weight: 600; font-size: 24px;">🚨 CRITICAL ALERT 🚨</h1>
                            <p style="color: #ffe6e6; margin: 10px 0 0 0; font-size: 16px;">Opportunity ID: #{{ doc.reference_name }}</p>
                        </td>
                    </tr>
                    
                    <!-- Content Area -->
                    <tr>
                        <td style="padding: 30px 20px;">
                            {% set opportunity = frappe.get_doc("Opportunity", doc.reference_name) %}
                            {% set customer_display = opportunity.custom_man_customer_name if (opportunity.party_name == "General - عامة (USD)" or opportunity.party_name == "General - عامة (IQD)") and opportunity.custom_man_customer_name else opportunity.party_name %}
                            
                            <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 15px;">
                                        Dear {{ frappe.get_doc("User", doc.allocated_to).full_name or doc.allocated_to }},
                                    </td>
                                </tr>
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 20px;">
                                        <strong style="color: #dc3545;">CRITICAL:</strong> Your assigned opportunity is closing <strong style="color: #dc3545;">TODAY</strong>! This is your final reminder.
                                    </td>
                                </tr>
                                
                                <!-- Urgency Alert Box -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8d7da; border-left: 4px solid #dc3545; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 15px 20px;">
                                                    <p style="color: #721c24; margin: 0; font-weight: 700; font-size: 16px;">⏰ CLOSING TODAY - FINAL REMINDER!</p>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <!-- Opportunity Info Card -->
                                <tr>
                                    <td style="padding: 0 0 25px 0;">
                                        <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse; background-color: #f8f9fa; border-left: 4px solid #dc3545; border-radius: 6px;">
                                            <tr>
                                                <td style="padding: 20px;">
                                                    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse: collapse;">
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px; width: 40%;">Opportunity No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #dc3545; font-weight: 700; font-size: 14px;">{{ opportunity.name }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Customer</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ customer_display or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Opportunity Type</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.opportunity_type or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender No.</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_no or "N/A" }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Tender Title</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.custom_tender_title or "N/A" }}</td>
                                                            </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; border-bottom: 1px solid #e9ecef; color: #555; font-size: 14px;">Expected Closing</td>
                                                            <td style="padding: 8px 0; border-bottom: 1px solid #e9ecef; color: #FF0000; font-weight: 700; font-size: 14px;">{{ frappe.utils.formatdate(opportunity.expected_closing) }}</td>
                                                        </tr>
                                                        <tr>
                                                            <td style="padding: 8px 10px 8px 0; color: #555; font-size: 14px;">Status</td>
                                                            <td style="padding: 8px 0; color: #333; font-weight: 600; font-size: 14px;">{{ opportunity.status }}</td>
                                                        </tr>
                                                    </table>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="color: #444; font-size: 16px; padding-bottom: 25px;">
                                        Please ensure you complete your quotation and follow up accordingly.
                                    </td>
                                </tr>
                                
                                <!-- CTA Button -->
                                <tr>
                                    <td align="center" style="padding: 10px 0 25px 0;">
                                        <!--[if mso]>
                                        <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="height:45px;v-text-anchor:middle;width:230px;" arcsize="50%" stroke="f" fillcolor="#dc3545">
                                        <w:anchorlock/>
                                        <center>
                                        <![endif]-->
                                        <a href="{{ frappe.utils.get_url() }}/app/opportunity/{{ opportunity.name }}" style="display: inline-block; background-color: #dc3545; color: #ffffff; font-weight: 600; text-decoration: none; padding: 12px 25px; border-radius: 50px; font-size: 16px; box-shadow: 0 4px 10px rgba(220,53,69,0.3); mso-padding-alt: 0; text-underline-color: #dc3545;"><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%;mso-text-raise:20pt">&nbsp;</i><![endif]--><span style="mso-text-raise:10pt;">Take Action Now</span><!--[if mso]><i style="letter-spacing: 25px;mso-font-width:-100%">&nbsp;</i><![endif]--></a>
                                        <!--[if mso]>
                                        </center>
                                        </v:roundrect>
                                        <![endif]-->
                                    </td>
                                </tr>
                                
                                <tr>
                                    <td style="padding-top: 10px;">
                                        <p style="color: #444; margin: 0 0 5px 0; font-size: 16px;">Best regards,</p>
                                        <p style="color: #444; font-weight: 600; margin: 0; font-size: 16px;">ALKHORA for General Trading Ltd</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
                            <p style="color: #6c757d; margin: 0; font-size: 13px;">This is an automated reminder from your ERP system.</p>
                            <p style="color: #6c757d; margin: 5px 0 0 0; font-size: 13px;">Please do not reply to this email.</p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>