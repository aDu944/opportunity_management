frappe.pages['my-opportunities'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'My Opportunities',
        single_column: true
    });

    // Initialize page data
    page.current_tab = 'open'; // 'open' or 'completed'
    page.sort_by = 'urgency';
    page.sort_order = 'asc';

    // Add refresh button
    page.add_button('Refresh', () => {
        load_opportunities(page);
    }, 'primary');

    // Add filter for urgency (only for open opportunities)
    page.add_field({
        fieldname: 'urgency_filter',
        label: 'Filter by Urgency',
        fieldtype: 'Select',
        options: '\nAll\nOverdue\nDue Today\nCritical (1 day)\nHigh (3 days)\nMedium (7 days)\nLow',
        change: function() {
            filter_opportunities(page);
        }
    });

    // Add tabs
    page.main.html(`
        <div class="opportunities-container">
            <div class="tabs-container" style="margin-bottom: 20px;">
                <button class="btn btn-default tab-btn" data-tab="open" style="margin-right: 10px;">
                    Open Opportunities
                </button>
                <button class="btn btn-default tab-btn" data-tab="completed">
                    Completed Opportunities
                </button>
            </div>
            <div class="summary-cards"></div>
            <div class="opportunities-list"></div>
        </div>
    `);

    // Tab click handlers
    page.main.find('.tab-btn').on('click', function() {
        const tab = $(this).data('tab');
        page.current_tab = tab;

        // Update active tab styling
        page.main.find('.tab-btn').removeClass('btn-primary').addClass('btn-default');
        $(this).removeClass('btn-default').addClass('btn-primary');

        // Show/hide urgency filter based on tab
        if (tab === 'completed') {
            page.fields_dict.urgency_filter.$wrapper.hide();
        } else {
            page.fields_dict.urgency_filter.$wrapper.show();
        }

        // Reload data
        load_opportunities(page);
    });

    // Set initial active tab
    page.main.find('.tab-btn[data-tab="open"]').addClass('btn-primary').removeClass('btn-default');

    load_opportunities(page);
};

function load_opportunities(page) {
    const is_completed = page.current_tab === 'completed';

    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_my_opportunities',
        args: {
            include_completed: is_completed
        },
        freeze: true,
        freeze_message: 'Loading opportunities...',
        callback: function(r) {
            if (r.message) {
                page.opportunities = r.message;
                render_summary(page);
                render_opportunities(page);
            }
        }
    });
}

function render_summary(page) {
    const opportunities = page.opportunities;

    if (page.current_tab === 'completed') {
        // Summary for completed opportunities
        const total = opportunities.length;
        const converted = opportunities.filter(o => o.status === 'Converted').length;
        const closed = opportunities.filter(o => o.status === 'Closed').length;
        const lost = opportunities.filter(o => o.status === 'Lost').length;

        const summaryHtml = `
            <div class="row" style="margin-bottom: 20px;">
                <div class="col-md-3">
                    <div class="card" style="background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <h3 style="margin: 0; color: #333;">${total}</h3>
                        <p style="margin: 0; color: #666;">Total Completed</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card" style="background: #28a745; color: white; padding: 15px; border-radius: 8px;">
                        <h3 style="margin: 0;">${converted}</h3>
                        <p style="margin: 0;">Converted</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card" style="background: #17a2b8; color: white; padding: 15px; border-radius: 8px;">
                        <h3 style="margin: 0;">${closed}</h3>
                        <p style="margin: 0;">Closed</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card" style="background: #6c757d; color: white; padding: 15px; border-radius: 8px;">
                        <h3 style="margin: 0;">${lost}</h3>
                        <p style="margin: 0;">Lost</p>
                    </div>
                </div>
            </div>
        `;
        page.main.find('.summary-cards').html(summaryHtml);
    } else {
        // Summary for open opportunities
        const overdue = opportunities.filter(o => o.urgency === 'overdue').length;
        const dueToday = opportunities.filter(o => o.urgency === 'due_today').length;
        const critical = opportunities.filter(o => o.urgency === 'critical').length;
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
                        <h3 style="margin: 0;">${critical}</h3>
                        <p style="margin: 0;">Due Tomorrow</p>
                    </div>
                </div>
            </div>
        `;
        page.main.find('.summary-cards').html(summaryHtml);
    }
}

function sort_my_opportunities(page, column) {
    // Toggle sort order if clicking same column
    if (page.sort_by === column) {
        page.sort_order = page.sort_order === 'asc' ? 'desc' : 'asc';
    } else {
        page.sort_by = column;
        page.sort_order = 'asc';
    }

    // Sort the opportunities array
    page.opportunities.sort((a, b) => {
        let aVal, bVal;

        switch(column) {
            case 'urgency':
                const urgency_order = {"overdue": 0, "due_today": 1, "critical": 2, "high": 3, "medium": 4, "low": 5, "unknown": 6};
                aVal = urgency_order[a.urgency] || 99;
                bVal = urgency_order[b.urgency] || 99;
                break;
            case 'opportunity':
                aVal = a.opportunity || '';
                bVal = b.opportunity || '';
                break;
            case 'customer':
                aVal = a.customer || '';
                bVal = b.customer || '';
                break;
            case 'status':
                aVal = a.status || '';
                bVal = b.status || '';
                break;
            case 'closing_date':
                aVal = a.closing_date || '9999-12-31';
                bVal = b.closing_date || '9999-12-31';
                break;
            case 'days_remaining':
                aVal = a.days_remaining !== null ? a.days_remaining : 9999;
                bVal = b.days_remaining !== null ? b.days_remaining : 9999;
                break;
            default:
                return 0;
        }

        if (aVal < bVal) return page.sort_order === 'asc' ? -1 : 1;
        if (aVal > bVal) return page.sort_order === 'asc' ? 1 : -1;
        return 0;
    });

    // Re-render
    render_opportunities(page);
}

function render_opportunities(page) {
    const opportunities = page.opportunities;

    if (!opportunities.length) {
        const message = page.current_tab === 'completed'
            ? '<h4>No completed opportunities!</h4>'
            : '<h4>🎉 No open opportunities!</h4><p>You have no pending tasks.</p>';

        page.main.find('.opportunities-list').html(`
            <div style="text-align: center; padding: 40px; color: #666;">
                ${message}
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
        <table class="table table-bordered" style="background: white;">
            <thead style="background: #f5f5f5; cursor: pointer;">
                <tr>
                    <th onclick="window.sort_my_opportunities_handler('urgency')">Urgency${getSortIcon('urgency')}</th>
                    <th onclick="window.sort_my_opportunities_handler('opportunity')">Opportunity${getSortIcon('opportunity')}</th>
                    <th onclick="window.sort_my_opportunities_handler('customer')">Customer${getSortIcon('customer')}</th>
                    ${page.current_tab === 'completed' ? `<th onclick="window.sort_my_opportunities_handler('status')">Status${getSortIcon('status')}</th>` : ''}
                    <th onclick="window.sort_my_opportunities_handler('closing_date')">Closing Date${getSortIcon('closing_date')}</th>
                    <th onclick="window.sort_my_opportunities_handler('days_remaining')">Days Left${getSortIcon('days_remaining')}</th>
                    <th>Items</th>
                    ${page.current_tab === 'open' ? '<th>Actions</th>' : ''}
                </tr>
            </thead>
            <tbody>
    `;

    opportunities.forEach(opp => {
        const urgencyBadge = page.current_tab === 'completed'
            ? getStatusBadge(opp.status)
            : getUrgencyBadge(opp.urgency, opp.days_remaining);

        const statusColumn = page.current_tab === 'completed'
            ? `<td><span class="badge" style="background: #6c757d; color: white;">${opp.status}</span></td>`
            : '';

        const itemsCount = opp.items ? opp.items.length : 0;

        html += `
            <tr data-urgency="${opp.urgency}">
                <td>${urgencyBadge}</td>
                <td>
                    <a href="/app/opportunity/${opp.opportunity}" target="_blank">
                        ${opp.opportunity}
                    </a>
                </td>
                <td>${opp.customer || 'N/A'}</td>
                ${statusColumn}
                <td>${opp.closing_date || 'Not set'}</td>
                <td style="text-align: center;">${opp.days_remaining !== null ? opp.days_remaining : '-'}</td>
                <td style="text-align: center;">
                    <span class="badge" style="background: #6c757d; color: white;">${itemsCount} items</span>
                </td>
                ${page.current_tab === 'open' ? `
                <td>
                    <a href="/app/quotation/new-quotation-1?opportunity=${opp.opportunity}"
                       class="btn btn-xs btn-success">
                        Create Quotation
                    </a>
                </td>
                ` : ''}
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

function getStatusBadge(status) {
    const badges = {
        'Converted': '<span class="badge" style="background: #28a745; color: white;">✓ Converted</span>',
        'Closed': '<span class="badge" style="background: #17a2b8; color: white;">Closed</span>',
        'Lost': '<span class="badge" style="background: #6c757d; color: white;">Lost</span>'
    };
    return badges[status] || `<span class="badge" style="background: #6c757d; color: white;">${status}</span>`;
}

// Global handler for sorting (accessed from onclick in table headers)
window.sort_my_opportunities_handler = function(column) {
    // Find the page object
    const page = frappe.pages['my-opportunities'].page;
    if (page && page.opportunities) {
        sort_my_opportunities(page, column);
    }
};

function filter_opportunities(page) {
    const filter = page.fields_dict.urgency_filter.get_value();
    const rows = page.main.find('tbody tr');
    
    if (!filter || filter === 'All') {
        rows.show();
        return;
    }

    const filterMap = {
        'Overdue': 'overdue',
        'Due Today': 'due_today',
        'Critical (1 day)': 'critical',
        'High (3 days)': 'high',
        'Medium (7 days)': 'medium',
        'Low': 'low'
    };

    const urgencyValue = filterMap[filter];
    
    rows.each(function() {
        const rowUrgency = $(this).data('urgency');
        $(this).toggle(rowUrgency === urgencyValue);
    });
}
