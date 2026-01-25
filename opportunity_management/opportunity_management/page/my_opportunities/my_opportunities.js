frappe.pages['my-opportunities'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'My Opportunities',
        single_column: true
    });

    // Initialize page data
    page.current_tab = 'open'; // 'open' or 'completed'
    page.sort_by = 'closing_date';
    page.sort_order = 'asc';

    // Add refresh button
    page.add_button('Refresh', () => {
        load_opportunities(page);
    }, 'primary');

    // Add hide overdue filter
    page.add_field({
        fieldname: 'hide_overdue',
        label: 'Hide Overdue Opportunities',
        fieldtype: 'Check',
        default: 1,
        change: function() {
            render_opportunities(page);
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
            <div class="row" style="margin-bottom: 20px; gap: 15px;">
                <div class="col" style="flex: 1;">
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);">
                        <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${total}</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Total Completed</p>
                    </div>
                </div>
                <div class="col" style="flex: 1;">
                    <div style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(56, 239, 125, 0.4);">
                        <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${converted}</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Converted</p>
                    </div>
                </div>
                <div class="col" style="flex: 1;">
                    <div style="background: linear-gradient(135deg, #3a7bd5 0%, #00d2ff 100%); color: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(58, 123, 213, 0.4);">
                        <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${closed}</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Closed</p>
                    </div>
                </div>
                <div class="col" style="flex: 1;">
                    <div style="background: linear-gradient(135deg, #757F9A 0%, #D7DDE8 100%); color: #333; padding: 20px; border-radius: 12px; box-shadow: 0 4px 15px rgba(117, 127, 154, 0.3);">
                        <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${lost}</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 14px;">Lost</p>
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
                        <h3 style="margin: 0; font-size: 32px; font-weight: 600;">${critical}</h3>
                        <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 14px;">Due Tomorrow</p>
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
    let opportunities = page.opportunities;

    // Filter out overdue opportunities if checkbox is checked (only for open opportunities)
    const hideOverdue = page.fields_dict.hide_overdue ? page.fields_dict.hide_overdue.get_value() : false;
    if (hideOverdue && page.current_tab === 'open') {
        opportunities = opportunities.filter(opp => opp.urgency !== 'overdue');
    }

    if (!opportunities.length) {
        const message = page.current_tab === 'completed'
            ? '<h4>No completed opportunities!</h4>'
            : hideOverdue 
                ? '<h4>🎉 No open opportunities!</h4><p>You have no pending tasks (overdue hidden).</p>'
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
                    <th onclick="window.sort_my_opportunities_handler('opportunity')">Opportunity${getSortIcon('opportunity')}</th>
                    <th onclick="window.sort_my_opportunities_handler('customer')">Customer${getSortIcon('customer')}</th>
                    ${page.current_tab === 'completed' ? `<th onclick="window.sort_my_opportunities_handler('status')">Status${getSortIcon('status')}</th>` : ''}
                    <th onclick="window.sort_my_opportunities_handler('closing_date')">Closing Date${getSortIcon('closing_date')}</th>
                    ${page.current_tab === 'open' ? `<th onclick="window.sort_my_opportunities_handler('days_remaining')">Days Left${getSortIcon('days_remaining')}</th>` : ''}
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

        // Highlight rows with closing date today and within next 3 days
        const highlightUrgencies = ['due_today', 'critical', 'high'];
        const rowStyle = highlightUrgencies.includes(opp.urgency)
            ? 'background: linear-gradient(90deg, #fff3cd 0%, #ffffff 100%); border-left: 4px solid #ffc107; box-shadow: 0 2px 4px rgba(255, 193, 7, 0.2);'
            : '';

        html += `
            <tr data-urgency="${opp.urgency}" style="${rowStyle}">
                <td>
                    <a href="/app/opportunity/${opp.opportunity}" target="_blank">
                        ${opp.opportunity}
                    </a>
                </td>
                <td>${opp.customer || 'N/A'}</td>
                ${statusColumn}
                <td>${opp.closing_date || 'Not set'}</td>
                ${page.current_tab === 'open' ? `<td style="text-align: center;">${opp.days_remaining !== null ? opp.days_remaining : '-'}</td>` : ''}
                <td style="text-align: center;">
                    <span class="badge" style="background: #6c757d; color: white;">${itemsCount} items</span>
                </td>
                ${page.current_tab === 'open' ? `
                <td>
                    <a href="/app/quotation/new-quotation?opportunity=${opp.opportunity}"
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
