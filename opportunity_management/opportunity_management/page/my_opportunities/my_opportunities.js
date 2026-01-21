frappe.pages['my_opportunities'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'My Opportunities',
        single_column: true
    });

    // Add refresh button
    page.set_primary_action('Refresh', () => {
        load_opportunities(page);
    }, 'refresh');

    // Add filter for status
    page.add_field({
        fieldname: 'status_filter',
        label: __('Status'),
        fieldtype: 'Select',
        options: 'All\nOverdue\nDue Today\nDue This Week\nUpcoming',
        default: 'All',
        change: () => {
            load_opportunities(page);
        }
    });

    load_opportunities(page);
};

function load_opportunities(page) {
    page.main.html('<div class="text-center"><i class="fa fa-spinner fa-spin fa-3x"></i><p>Loading...</p></div>');
    
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_my_opportunities',
        callback: function(r) {
            if (r.message) {
                render_opportunities(page, r.message);
            }
        }
    });
}

function render_opportunities(page, opportunities) {
    let filter = page.fields_dict.status_filter.get_value();
    
    // Apply filter
    let filtered = opportunities;
    if (filter === 'Overdue') {
        filtered = opportunities.filter(o => o.days_remaining !== null && o.days_remaining < 0);
    } else if (filter === 'Due Today') {
        filtered = opportunities.filter(o => o.days_remaining === 0);
    } else if (filter === 'Due This Week') {
        filtered = opportunities.filter(o => o.days_remaining !== null && o.days_remaining >= 0 && o.days_remaining <= 7);
    } else if (filter === 'Upcoming') {
        filtered = opportunities.filter(o => o.days_remaining === null || o.days_remaining > 7);
    }

    if (filtered.length === 0) {
        page.main.html(`
            <div class="text-center text-muted" style="padding: 50px;">
                <i class="fa fa-check-circle fa-4x"></i>
                <h4>No opportunities found</h4>
                <p>You have no open opportunity tasks${filter !== 'All' ? ' matching this filter' : ''}.</p>
            </div>
        `);
        return;
    }

    let html = `
        <div class="opportunity-list">
            <div class="row" style="margin-bottom: 10px; font-weight: bold; padding: 10px; background: #f5f5f5; border-radius: 5px;">
                <div class="col-md-3">Opportunity</div>
                <div class="col-md-2">Customer</div>
                <div class="col-md-2">Closing Date</div>
                <div class="col-md-2">Status</div>
                <div class="col-md-2">Priority</div>
                <div class="col-md-1">Actions</div>
            </div>
    `;

    filtered.forEach(opp => {
        let statusBadge = get_status_badge(opp.status_color, opp.status_label);
        let priorityBadge = get_priority_badge(opp.priority);
        
        html += `
            <div class="row opportunity-row" style="padding: 15px 10px; border-bottom: 1px solid #eee; align-items: center;">
                <div class="col-md-3">
                    <a href="/app/opportunity/${opp.opportunity_name}" style="font-weight: 500;">
                        ${opp.opportunity_name}
                    </a>
                    <br>
                    <small class="text-muted">${opp.opportunity_type || ''}</small>
                </div>
                <div class="col-md-2">${opp.party_name || '-'}</div>
                <div class="col-md-2">${opp.expected_closing || 'Not set'}</div>
                <div class="col-md-2">${statusBadge}</div>
                <div class="col-md-2">${priorityBadge}</div>
                <div class="col-md-1">
                    <button class="btn btn-xs btn-success" onclick="close_task('${opp.todo_name}')">
                        <i class="fa fa-check"></i>
                    </button>
                </div>
            </div>
        `;
    });

    html += '</div>';
    
    // Summary stats
    let overdue = opportunities.filter(o => o.days_remaining !== null && o.days_remaining < 0).length;
    let dueToday = opportunities.filter(o => o.days_remaining === 0).length;
    let dueThisWeek = opportunities.filter(o => o.days_remaining !== null && o.days_remaining > 0 && o.days_remaining <= 7).length;
    
    let summary = `
        <div class="row" style="margin-bottom: 20px;">
            <div class="col-md-3">
                <div class="stat-card" style="background: #fff; padding: 15px; border-radius: 8px; border-left: 4px solid #dc3545;">
                    <h3 style="margin: 0; color: #dc3545;">${overdue}</h3>
                    <small class="text-muted">Overdue</small>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card" style="background: #fff; padding: 15px; border-radius: 8px; border-left: 4px solid #fd7e14;">
                    <h3 style="margin: 0; color: #fd7e14;">${dueToday}</h3>
                    <small class="text-muted">Due Today</small>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card" style="background: #fff; padding: 15px; border-radius: 8px; border-left: 4px solid #ffc107;">
                    <h3 style="margin: 0; color: #ffc107;">${dueThisWeek}</h3>
                    <small class="text-muted">Due This Week</small>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card" style="background: #fff; padding: 15px; border-radius: 8px; border-left: 4px solid #28a745;">
                    <h3 style="margin: 0; color: #28a745;">${opportunities.length}</h3>
                    <small class="text-muted">Total Open</small>
                </div>
            </div>
        </div>
    `;

    page.main.html(summary + html);
}

function get_status_badge(color, label) {
    let bgColor = {
        'red': '#dc3545',
        'orange': '#fd7e14',
        'yellow': '#ffc107',
        'green': '#28a745',
        'gray': '#6c757d'
    }[color] || '#6c757d';
    
    let textColor = color === 'yellow' ? '#000' : '#fff';
    
    return `<span style="background: ${bgColor}; color: ${textColor}; padding: 3px 8px; border-radius: 3px; font-size: 11px;">${label}</span>`;
}

function get_priority_badge(priority) {
    let colors = {
        'High': '#dc3545',
        'Medium': '#ffc107',
        'Low': '#28a745'
    };
    let color = colors[priority] || '#6c757d';
    return `<span style="color: ${color}; font-weight: 500;">${priority || 'Medium'}</span>`;
}

function close_task(todo_name) {
    frappe.confirm(
        'Are you sure you want to mark this task as complete?',
        () => {
            frappe.call({
                method: 'opportunity_management.opportunity_management.api.close_opportunity_todo',
                args: { todo_name: todo_name },
                callback: function(r) {
                    if (r.message && r.message.status === 'success') {
                        frappe.show_alert({message: 'Task closed', indicator: 'green'});
                        // Reload the page
                        frappe.pages['my_opportunities'].on_page_load(cur_page.page);
                    }
                }
            });
        }
    );
}
