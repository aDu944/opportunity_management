frappe.pages['team-opportunities'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Team Opportunities',
        single_column: true
    });

    // Add refresh button
    page.add_button('Refresh', () => {
        load_team_opportunities(page);
    }, 'primary');

    // Add team filter
    page.add_field({
        fieldname: 'team_filter',
        label: 'Filter by Team',
        fieldtype: 'Select',
        options: '\nAll Teams',
        change: function() {
            load_team_opportunities(page);
        }
    });

    page.main.html(`
        <div class="team-opportunities-container">
            <div class="filter-section" style="margin-bottom: 20px; padding: 20px; background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border: 1px solid #e1e8ed;">
                <div class="row">
                    <div class="col-md-12">
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
                </div>
            </div>
            <div class="summary-cards"></div>
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
                page.fields_dict.team_filter.refresh();
                
                // Move the field to the custom container and ensure it's visible
                const $container = page.main.find('#team-filter-container .control-input');
                $container.html(page.fields_dict.team_filter.$wrapper);
                
                // Ensure the field is properly styled
                page.fields_dict.team_filter.$wrapper.css({
                    'width': '100%',
                    'min-width': '200px'
                });
                page.fields_dict.team_filter.$input.css({
                    'width': '100%'
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
                
                // Ensure the field is properly styled
                page.fields_dict.team_filter.$wrapper.css({
                    'width': '100%',
                    'min-width': '200px'
                });
                page.fields_dict.team_filter.$input.css({
                    'width': '100%'
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
                page.opportunities = r.message;
                render_team_summary(page);
                render_team_opportunities(page);
            }
        }
    });
}

function render_team_summary(page) {
    const opportunities = page.opportunities;
    
    const overdue = opportunities.filter(o => o.urgency === 'overdue').length;
    const dueToday = opportunities.filter(o => o.urgency === 'due_today').length;
    const dueSoon = opportunities.filter(o => ['critical', 'high'].includes(o.urgency)).length;
    const total = opportunities.length;

    const summaryHtml = `
        <div class="row" style="margin-bottom: 20px; gap: 15px;">
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${total}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Total Open</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(245, 87, 108, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${overdue}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Overdue</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(254, 225, 64, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${dueToday}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Due Today</p>
                </div>
            </div>
            <div class="col" style="flex: 1;">
                <div style="background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%); color: #333; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(252, 182, 159, 0.4);">
                    <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${dueSoon}</h3>
                    <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 14px;">Due in 3 days</p>
                </div>
            </div>
        </div>
    `;

    page.main.find('.summary-cards').html(summaryHtml);
}

function render_team_opportunities(page) {
    const opportunities = page.opportunities;
    
    if (!opportunities.length) {
        page.main.find('.opportunities-list').html(`
            <div style="text-align: center; padding: 40px; color: #666;">
                <h4>🎉 No open opportunities for this team!</h4>
            </div>
        `);
        return;
    }

    let html = `
        <table class="table table-bordered" style="background: white;">
            <thead style="background: #f5f5f5;">
                <tr>
                    <th>Opportunity</th>
                    <th>Customer</th>
                    <th>Closing Date</th>
                    <th>Days Left</th>
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

        // Highlight rows with closing date today
        const rowStyle = opp.urgency === 'due_today'
            ? 'background: linear-gradient(90deg, #fff3cd 0%, #ffffff 100%); border-left: 4px solid #ffc107;'
            : '';

        html += `
            <tr data-urgency="${opp.urgency}" style="${rowStyle}">
                <td>
                    <a href="/app/opportunity/${opp.opportunity}" target="_blank">
                        ${opp.opportunity}
                    </a>
                </td>
                <td>${opp.customer || 'N/A'}</td>
                <td>${opp.closing_date || 'Not set'}</td>
                <td style="text-align: center;">${opp.days_remaining !== null ? opp.days_remaining : '-'}</td>
                <td>${assigneesList}</td>
                <td>
                    <a href="/app/quotation/new-quotation-1?opportunity=${opp.opportunity}" 
                       class="btn btn-xs btn-success">
                        Create Quotation
                    </a>
                </td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    page.main.find('.opportunities-list').html(html);
}

function getUrgencyBadge(urgency, days) {
    const badges = {
        'overdue': `<span class="badge" style="background: #dc3545; color: white;">⚠️ OVERDUE (${Math.abs(days)} days)</span>`,
        'due_today': '<span class="badge" style="background: #dc3545; color: white;">🔴 DUE TODAY</span>',
        'critical': '<span class="badge" style="background: #fd7e14; color: white;">🟠 Tomorrow</span>',
        'high': '<span class="badge" style="background: #ffc107;">🟡 3 days</span>',
        'medium': '<span class="badge" style="background: #17a2b8; color: white;">🔵 7 days</span>',
        'low': '<span class="badge" style="background: #28a745; color: white;">🟢 ' + days + ' days</span>',
        'unknown': '<span class="badge" style="background: #6c757d; color: white;">No date</span>'
    };
    return badges[urgency] || badges['unknown'];
}
