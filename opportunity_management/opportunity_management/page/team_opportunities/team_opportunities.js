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
            <div class="summary-cards"></div>
            <div class="opportunities-list"></div>
        </div>
    `);

    // Load available teams first
    load_teams(page);
    load_team_opportunities(page);
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
            }
        }
    });
}

function load_team_opportunities(page) {
    const team = page.fields_dict.team_filter.get_value();
    
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_team_opportunities',
        args: {
            team: team && team !== 'All Teams' ? team : null
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
        <div class="row" style="margin-bottom: 20px;">
            <div class="col-md-3">
                <div class="card" style="background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin: 0; color: #333;">${total}</h3>
                    <p style="margin: 0; color: #666;">Total Open</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="background: #dc3545; color: white; padding: 15px; border-radius: 8px;">
                    <h3 style="margin: 0;">${overdue}</h3>
                    <p style="margin: 0;">Overdue</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="background: #fd7e14; color: white; padding: 15px; border-radius: 8px;">
                    <h3 style="margin: 0;">${dueToday}</h3>
                    <p style="margin: 0;">Due Today</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card" style="background: #ffc107; padding: 15px; border-radius: 8px;">
                    <h3 style="margin: 0;">${dueSoon}</h3>
                    <p style="margin: 0;">Due in 3 days</p>
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
                    <th>Urgency</th>
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

        html += `
            <tr>
                <td>${urgencyBadge}</td>
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
