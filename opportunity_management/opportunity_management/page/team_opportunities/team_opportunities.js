frappe.pages['team-opportunities'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Team Opportunities',
        single_column: true
    });

    // Initialize page data
    page.sort_by = 'days_remaining';
    page.sort_order = 'asc';

    // Add refresh button
    page.add_button('Refresh', () => {
        load_team_opportunities(page);
    }, 'primary');

    // Add team filter
    page.add_field({
        fieldname: 'team_filter',
        label: '',
        fieldtype: 'Select',
        options: '\nAll Teams',
        change: function() {
            load_team_opportunities(page);
        }
    });

    // Add hide overdue filter
    page.add_field({
        fieldname: 'hide_overdue',
        label: 'Hide Overdue Opportunities',
        fieldtype: 'Check',
        default: 1,
        change: function() {
            render_team_opportunities(page);
        }
    });

    page.main.html(`
        <div class="team-opportunities-container">
            <div class="filter-section" style="margin-bottom: 20px; padding: 20px; background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border: 1px solid #e1e8ed;">
                <div class="row">
                    <div class="col-md-8">
                        <div style="display: flex; align-items: center; gap: 15px;">
                            <label style="margin: 0; font-weight: 600; color: #2c3e50; font-size: 14px; white-space: nowrap;">Filter by Team:</label>
                            <div id="team-filter-container" style="flex: 1; max-width: 400px; min-width: 200px;">
                                <div class="form-group frappe-control input-max-width" style="margin: 0;">
                                    <div class="control-input-wrapper">
                                        <div class="control-input" style="width: 100%;"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div id="overdue-filter-container"></div>
                    </div>
                </div>
            </div>
            <div style="margin: -8px 0 16px 0; padding: 10px 12px; background: #fff3cd; border: 1px solid #ffeeba; border-radius: 8px; color: #856404; font-size: 13px;">
                Note: Opportunities without a Responsible Party are hidden.
            </div>
            <div class="summary-cards"></div>
            <div class="employee-cards" style="margin-bottom: 20px;"></div>
            <div class="opportunities-list"></div>
        </div>
    `);

    // Load available teams first, then set default to user's department
    load_teams(page);
};

function load_teams(page) {
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_available_teams',
        callback: function(r) {
            if (r.message) {
                let options = '\nAll Teams';
                r.message.forEach(team => {
                    options += '\n' + team;
                });
                page.fields_dict.team_filter.df.options = options;
                page.fields_dict.team_filter.df.label = '';
                page.fields_dict.team_filter.df.placeholder = '';
                page.fields_dict.team_filter.refresh();
                
                // Move the field to the custom container and ensure it's visible
                const $container = page.main.find('#team-filter-container .control-input');
                $container.html(page.fields_dict.team_filter.$wrapper);
                page.fields_dict.team_filter.$wrapper.find('label').hide();
                
                // Ensure the field is properly styled
                page.fields_dict.team_filter.$wrapper.css({
                    'width': '100%',
                    'min-width': '200px'
                });
                page.fields_dict.team_filter.$input.css({
                    'width': '100%',
                    'padding-left': '12px'
                });
                page.fields_dict.team_filter.$input.attr('placeholder', '');
                
                // Move the hide overdue field
                const $overdueContainer = page.main.find('#overdue-filter-container');
                $overdueContainer.html(page.fields_dict.hide_overdue.$wrapper);
                
                // Rebind the change event after moving the field
                page.fields_dict.team_filter.$input.on('change', function() {
                    load_team_opportunities(page);
                });
                
                // Ensure hide_overdue change event works
                page.fields_dict.hide_overdue.$input.on('change', function() {
                    render_team_opportunities(page);
                });
                
                // Set default team to current user's department
                frappe.call({
                    method: 'frappe.client.get_value',
                    args: {
                        doctype: 'Employee',
                        filters: {
                            user_id: frappe.session.user,
                            status: 'Active'
                        },
                        fieldname: 'department'
                    },
                    callback: function(user_dept) {
                        if (user_dept.message && user_dept.message.department) {
                            const user_department = user_dept.message.department;
                            // Check if user's department is in available teams
                            if (r.message.includes(user_department)) {
                                page.fields_dict.team_filter.set_value(user_department);
                            } else {
                                page.fields_dict.team_filter.set_value('All Teams');
                            }
                        } else {
                            page.fields_dict.team_filter.set_value('All Teams');
                        }
                        // Now load opportunities with the default team
                        load_team_opportunities(page);
                    }
                });
            } else {
                // Move the field to the custom container even if no teams
                const $container = page.main.find('#team-filter-container .control-input');
                $container.html(page.fields_dict.team_filter.$wrapper);
                page.fields_dict.team_filter.$wrapper.find('label').hide();
                
                // Ensure the field is properly styled
                page.fields_dict.team_filter.$wrapper.css({
                    'width': '100%',
                    'min-width': '200px'
                });
                page.fields_dict.team_filter.$input.css({
                    'width': '100%',
                    'padding-left': '12px'
                });
                page.fields_dict.team_filter.$input.attr('placeholder', '');
                
                // Move the hide overdue field
                const $overdueContainer = page.main.find('#overdue-filter-container');
                $overdueContainer.html(page.fields_dict.hide_overdue.$wrapper);
                
                // Rebind the change event after moving the field
                page.fields_dict.team_filter.$input.on('change', function() {
                    load_team_opportunities(page);
                });
                
                // If no teams available, just load all opportunities
                load_team_opportunities(page);
            }
        }
    });
}

function load_team_opportunities(page) {
    const team = page.fields_dict.team_filter.get_value();
    
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_team_opportunities',
        args: {
            team: team || null
        },
        freeze: true,
        freeze_message: 'Loading team opportunities...',
        callback: function(r) {
            if (r.message) {
                page.opportunities = r.message.opportunities || [];
                page.employee_stats = r.message.employee_stats || [];
                
                // Sort by days remaining (ascending) by default
                page.sort_by = 'days_remaining';
                page.sort_order = 'asc';
                sort_team_opportunities(page, 'days_remaining', { toggle: false });
                
                render_team_summary(page);
                render_employee_cards(page);
                render_team_opportunities(page);
            }
        }
    });
}

function render_team_summary(page) {
    const opportunities = page.opportunities;
    
    const overdue = opportunities.filter(o => o.urgency === 'overdue').length;
    const dueToday = opportunities.filter(o => o.urgency === 'due_today').length;
    const dueSoon = opportunities.filter(o => o.days_remaining !== null && o.days_remaining >= 1 && o.days_remaining <= 3).length;
    const hideOverdue = page.fields_dict.hide_overdue ? page.fields_dict.hide_overdue.get_value() : false;
    const total = opportunities.filter(o => o.days_remaining !== null && (!hideOverdue || o.days_remaining >= 0)).length;

    const summaryHtml = `
        <div class="row" style="margin-bottom: 20px; gap: 15px;">
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600; color: #ffffff !important;">${total}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px; color: #ffffff !important;">Total Open</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(245, 87, 108, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600; color: #ffffff !important;">${overdue}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px; color: #ffffff !important;">Overdue</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: #e03131; color: white; padding: 20px; border-radius: 12px; box-shadow: 0 8px 24px rgba(224,49,49,0.55); border: 2px solid rgba(255,255,255,0.35);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600; color: #ffffff !important;">${dueToday}</h3>
                    <p style="margin: 5px 0 0 0; font-weight: 700; font-size: 14px; letter-spacing: 0.3px; text-transform: uppercase; color: #ffffff !important;">Due Today</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%); color: #333; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(252, 182, 159, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${dueSoon}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 14px;">Due Soon</p>
                </div>
            </div>
        </div>
    `;

    page.main.find('.summary-cards').html(summaryHtml);
}

function render_employee_cards(page) {
    const employeeStats = page.employee_stats || [];
    
    if (!employeeStats.length) {
        page.main.find('.employee-cards').html(`
            <div style="text-align: center; padding: 20px; color: #666; background: #f8f9fa; border-radius: 8px;">
                <h5>No team members with open opportunities</h5>
            </div>
        `);
        return;
    }

    let html = `
        <div style="margin-bottom: 15px;">
            <h4 style="color: #2c3e50; margin-bottom: 15px; font-weight: 600;">Team Members & Open Opportunities</h4>
        </div>
        <div class="row" style="gap: 15px;">
    `;

    employeeStats.forEach(employee => {
        const dept = employee.department ? ` (${employee.department})` : '';
        const cardColor = getEmployeeCardColor(employee.open_opportunities);
        
        html += `
            <div class="col" style="flex: 1; min-width: 200px; max-width: 250px;">
                <div style="background: ${cardColor}; color: white; padding: 15px; border-radius: 10px; box-shadow: 0 3px 10px rgba(0,0,0,0.15); text-align: center;">
                    <h4 style="margin: 0 0 5px 0; font-size: 18px; font-weight: 600;">${employee.employee_name}</h4>
                    <p style="margin: 0 0 10px 0; opacity: 0.9; font-size: 12px;">${dept}</p>
                    <div style="font-size: 28px; font-weight: 700; margin-bottom: 5px;">${employee.open_opportunities}</div>
                    <p style="margin: 0; opacity: 0.9; font-size: 12px;">Open Opportunities</p>
                </div>
            </div>
        `;
    });

    html += '</div>';
    page.main.find('.employee-cards').html(html);
}

function getEmployeeCardColor(opportunityCount) {
    if (opportunityCount >= 5) {
        return 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'; // Purple - high workload
    } else if (opportunityCount >= 3) {
        return 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)'; // Pink - medium workload
    } else if (opportunityCount >= 1) {
        return 'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)'; // Blue - light workload
    } else {
        return 'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)'; // Green - no workload
    }
}

function sort_team_opportunities(page, column, options = {}) {
    const toggle = options.toggle !== false;
    // Toggle sort order if clicking same column
    if (toggle && page.sort_by === column) {
        page.sort_order = page.sort_order === 'asc' ? 'desc' : 'asc';
    } else if (page.sort_by !== column) {
        page.sort_by = column;
        page.sort_order = 'asc';
    }

    // Sort the opportunities array
    page.opportunities.sort((a, b) => {
        let aVal, bVal;

        switch(column) {
            case 'opportunity':
                aVal = a.opportunity || '';
                bVal = b.opportunity || '';
                break;
            case 'customer':
                aVal = a.customer || '';
                bVal = b.customer || '';
                break;
            case 'closing_date':
                aVal = a.closing_date || '9999-12-31';
                bVal = b.closing_date || '9999-12-31';
                break;
            case 'days_remaining':
                aVal = a.days_remaining !== null ? a.days_remaining : -9999;
                bVal = b.days_remaining !== null ? b.days_remaining : -9999;
                break;
            default:
                return 0;
        }

        if (aVal < bVal) return page.sort_order === 'asc' ? -1 : 1;
        if (aVal > bVal) return page.sort_order === 'asc' ? 1 : -1;
        return 0;
    });

    // Re-render
    render_team_opportunities(page);
}

function render_team_opportunities(page) {
    let opportunities = page.opportunities;
    
    // Filter out overdue opportunities if checkbox is checked
    const hideOverdue = page.fields_dict.hide_overdue ? page.fields_dict.hide_overdue.get_value() : false;
    if (hideOverdue) {
        opportunities = opportunities.filter(opp => opp.days_remaining !== null && opp.days_remaining >= 0);
    }
    
    if (!opportunities.length) {
        const message = hideOverdue ? 'No open opportunities for this team (overdue hidden)!' : 'No open opportunities for this team!';
        page.main.find('.opportunities-list').html(`
            <div style="text-align: center; padding: 40px; color: #666;">
                <h4>🎉 ${message}</h4>
            </div>
        `);
        return;
    }

    const getSortIcon = (column) => {
        if (page.sort_by === column) {
            return page.sort_order === 'asc' ? ' ▲' : ' ▼';
        }
        return ' ⇅';
    };

    let html = `
        <div style="background: linear-gradient(135deg, #eef2f7, #f7f9fc); padding: 12px; border-radius: 14px;">
        <table class="table table-bordered" style="background: transparent; border-collapse: separate; border-spacing: 0 8px;">
            <thead style="background: transparent; cursor: pointer;">
                <tr>
                    <th onclick="window.sort_team_opportunities_handler('opportunity')">Opportunity${getSortIcon('opportunity')}</th>
                    <th>Request No.</th>
                    <th>Request Title</th>
                    <th onclick="window.sort_team_opportunities_handler('customer')">Customer${getSortIcon('customer')}</th>
                    <th onclick="window.sort_team_opportunities_handler('closing_date')">Closing Date${getSortIcon('closing_date')}</th>
                    <th onclick="window.sort_team_opportunities_handler('days_remaining')">Days Left${getSortIcon('days_remaining')}</th>
                    <th>Quotation</th>
                    <th>Assigned To</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
    `;

    opportunities.forEach(opp => {
        const urgencyBadge = getUrgencyBadge(opp.urgency, opp.days_remaining);
        
        // Format assignees
        const assigneesList = opp.assignees.map(a => {
            const name = a.employee || a.user;
            const dept = a.department ? ` (${a.department})` : '';
            return `<div class="assignee-badge" style="display: inline-block; background: #e9ecef; padding: 2px 8px; border-radius: 12px; margin: 2px; font-size: 12px;">${name}${dept}</div>`;
        }).join('');

        // Highlight rows based on days remaining
        let rowStyle = 'background: rgba(255,255,255,0.75); backdrop-filter: blur(6px);';
        let rowBorder = '#e5e7eb';
        if (opp.days_remaining === null || opp.days_remaining < 0) {
            rowBorder = '#dc3545';
        } else if (opp.days_remaining <= 3) {
            rowBorder = '#fd7e14';
        } else if (opp.days_remaining <= 7) {
            rowBorder = '#f1c21b';
        } else {
            rowBorder = '#28a745';
        }

        const quotationBadge = opp.has_draft_quotation
            ? '<span class="badge" style="background: #6f42c1; color: white;">Draft</span>'
            : (opp.has_quotation ? '<span class="badge" style="background: #17a2b8; color: white;">Created</span>' : '<span class="badge" style="background: #e9ecef; color: #666;">None</span>');

        const tenderNo = opp.tender_no && opp.tender_no !== '0' && opp.tender_no !== 0 ? opp.tender_no : 'N/A';
        const tenderTitle = opp.tender_title && opp.tender_title !== '0' && opp.tender_title !== 0 ? opp.tender_title : 'N/A';

        html += `
            <tr data-urgency="${opp.urgency}" style="${rowStyle}">
                <td>
                    <a href="/app/opportunity/${opp.opportunity}" target="_blank" style="display:block; padding:12px; border-left:4px solid ${rowBorder}; border-radius:10px 0 0 10px; color:#1f2937;">
                        ${opp.opportunity}
                    </a>
                </td>
                <td style="padding:12px;">${tenderNo}</td>
                <td style="padding:12px;">${tenderTitle}</td>
                <td style="padding:12px;">${opp.customer || 'N/A'}</td>
                <td style="padding:12px;">${opp.closing_date || 'Not set'}</td>
                <td style="text-align: center; padding:12px;">${opp.days_remaining !== null ? opp.days_remaining : 'No date'}</td>
                <td style="text-align: center; padding:12px;">${quotationBadge}</td>
                <td style="padding:12px;">${assigneesList}</td>
                <td style="padding:12px; border-radius:0 10px 10px 0;">
                    ${opp.has_quotation && opp.quotation_name ? `
                        <a href="/app/quotation/${opp.quotation_name}" 
                           class="btn btn-xs btn-default" style="cursor: pointer;">
                            View Quotation
                        </a>
                    ` : `
                        <a onclick="create_quotation('${opp.opportunity}')"
                           class="btn btn-xs btn-success" style="cursor: pointer;">
                            Create Quotation
                        </a>
                    `}
                </td>
            </tr>
        `;
    });

    html += '</tbody></table></div>';
    page.main.find('.opportunities-list').html(html);
}

function getUrgencyBadge(urgency, days) {
    const badges = {
        'overdue': `<span class="badge" style="background: #dc3545; color: white;">⚠️ OVERDUE (${days === null ? 'No date' : Math.abs(days) + ' days'})</span>`,
        'due_today': '<span class="badge" style="background: #dc3545; color: white;">🔴 DUE TODAY</span>',
        'critical': '<span class="badge" style="background: #fd7e14; color: white;">🟠 Tomorrow</span>',
        'high': '<span class="badge" style="background: #ffc107;">🟡 3 days</span>',
        'medium': '<span class="badge" style="background: #17a2b8; color: white;">🔵 7 days</span>',
        'low': '<span class="badge" style="background: #28a745; color: white;">🟢 ' + days + ' days</span>',
        'unknown': '<span class="badge" style="background: #6c757d; color: white;">No date</span>'
    };
    return badges[urgency] || badges['unknown'];
}

// Global handler for sorting (accessed from onclick in table headers)
window.sort_team_opportunities_handler = function(column) {
    // Find the page object
    const page = frappe.pages['team-opportunities'].page;
    if (page && page.opportunities) {
        sort_team_opportunities(page, column, { toggle: true });
    }
};

// Function to create quotation from opportunity
window.create_quotation = function(opportunity_name) {
    if (!opportunity_name) {
        return;
    }

    frappe.model.open_mapped_doc({
        method: "erpnext.crm.doctype.opportunity.opportunity.make_quotation",
        source_name: opportunity_name
    });
};
