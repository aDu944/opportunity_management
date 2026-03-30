frappe.pages['opportunity-kpi'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Opportunity KPI Dashboard',
        single_column: true
    });

    // Add refresh button
    page.add_button('Refresh', () => {
        load_kpi_data(page);
    }, 'primary');

    // Add date filters
    page.add_field({
        fieldname: 'from_date',
        label: 'From Date',
        fieldtype: 'Date',
        default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
        change: function() {
            load_kpi_data(page);
        }
    });

    page.add_field({
        fieldname: 'to_date',
        label: 'To Date',
        fieldtype: 'Date',
        default: frappe.datetime.get_today(),
        change: function() {
            load_kpi_data(page);
        }
    });

    // Add view toggle
    page.add_field({
        fieldname: 'view_type',
        label: 'View',
        fieldtype: 'Select',
        options: 'By Employee\nBy Team',
        default: 'By Employee',
        change: function() {
            load_kpi_data(page);
        }
    });

    page.main.html(`
        <div class="kpi-dashboard-container">
            <div class="overall-kpi"></div>
            <div class="kpi-chart" style="height: 300px; margin: 20px 0;"></div>
            <div class="kpi-breakdown"></div>
        </div>
    `);

    load_kpi_data(page);
};

function load_kpi_data(page) {
    const fromDate = page.fields_dict.from_date.get_value();
    const toDate = page.fields_dict.to_date.get_value();
    const viewType = page.fields_dict.view_type.get_value();

    // Load overall KPI
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_opportunity_kpi',
        args: {
            from_date: fromDate,
            to_date: toDate
        },
        callback: function(r) {
            if (r.message) {
                render_overall_kpi(page, r.message);
            }
        }
    });

    // Load breakdown
    const breakdownMethod = viewType === 'By Team' 
        ? 'opportunity_management.opportunity_management.api.get_kpi_by_team'
        : 'opportunity_management.opportunity_management.api.get_kpi_by_employee';

    frappe.call({
        method: breakdownMethod,
        args: {
            from_date: fromDate,
            to_date: toDate
        },
        callback: function(r) {
            if (r.message) {
                render_kpi_breakdown(page, r.message, viewType);
                render_kpi_chart(page, r.message, viewType);
            }
        }
    });
}

function render_overall_kpi(page, kpi) {
    const html = `
        <div class="row" style="margin-bottom: 30px;">
            <div class="col-md-3">
                <div class="kpi-card" style="background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center;">
                    <h2 style="margin: 0; color: #333; font-size: 36px;">${kpi.total}</h2>
                    <p style="margin: 5px 0 0 0; color: #666;">Total Assigned</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #28a745; color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.completed}</h2>
                    <p style="margin: 5px 0 0 0;">Completed</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #17a2b8; color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.completed_on_time}</h2>
                    <p style="margin: 5px 0 0 0;">On Time</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #ffc107; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.completed_late}</h2>
                    <p style="margin: 5px 0 0 0;">Late</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #6c757d; color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.still_open}</h2>
                    <p style="margin: 5px 0 0 0;">Still Open</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.on_time_rate}%</h2>
                    <p style="margin: 5px 0 0 0;">On-Time Rate</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #dc3545; color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.overdue_rate}%</h2>
                    <p style="margin: 5px 0 0 0;">Overdue Rate</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="kpi-card" style="background: #0d6efd; color: white; padding: 20px; border-radius: 8px; text-align: center;">
                    <h2 style="margin: 0; font-size: 36px;">${kpi.median_close_days}</h2>
                    <p style="margin: 5px 0 0 0;">Median Close Days</p>
                </div>
            </div>
        </div>
    `;
    
    page.main.find('.overall-kpi').html(html);
}

function render_kpi_breakdown(page, data, viewType) {
    if (!data.length) {
        page.main.find('.kpi-breakdown').html(`
            <div style="text-align: center; padding: 40px; color: #666;">
                <p>No data available for the selected period.</p>
            </div>
        `);
        return;
    }

    const nameColumn = viewType === 'By Team' ? 'Team' : 'Employee';
    const nameField = viewType === 'By Team' ? 'team' : 'employee_name';

    let html = `
        <h4 style="margin-bottom: 15px;">Performance ${viewType}</h4>
        <table class="table table-bordered" style="background: white;">
            <thead style="background: #f5f5f5;">
                <tr>
                    <th>Rank</th>
                    <th>${nameColumn}</th>
                    <th style="text-align: center;">Total</th>
                    <th style="text-align: center;">Completed</th>
                    <th style="text-align: center;">On Time</th>
                    <th style="text-align: center;">Late</th>
                    <th style="text-align: center;">Open</th>
                    <th style="text-align: center;">On-Time Rate</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach((item, index) => {
        const rankBadge = getRankBadge(index + 1);
        const rateColor = getPerformanceColor(item.on_time_rate);
        
        html += `
            <tr>
                <td style="text-align: center;">${rankBadge}</td>
                <td><strong>${item[nameField] || 'Unknown'}</strong></td>
                <td style="text-align: center;">${item.total}</td>
                <td style="text-align: center;">${item.completed}</td>
                <td style="text-align: center; color: #28a745; font-weight: bold;">${item.completed_on_time}</td>
                <td style="text-align: center; color: #dc3545;">${item.completed_late}</td>
                <td style="text-align: center;">${item.still_open}</td>
                <td style="text-align: center;">
                    <div style="background: ${rateColor}; color: white; padding: 4px 12px; border-radius: 20px; display: inline-block; font-weight: bold;">
                        ${item.on_time_rate}%
                    </div>
                </td>
            </tr>
        `;
    });

    html += '</tbody></table>';
    page.main.find('.kpi-breakdown').html(html);
}

function render_kpi_chart(page, data, viewType) {
    if (!data.length) {
        page.main.find('.kpi-chart').html('');
        return;
    }

    const nameField = viewType === 'By Team' ? 'team' : 'employee_name';
    
    // Prepare data for chart
    const chartData = {
        labels: data.map(d => d[nameField] || 'Unknown'),
        datasets: [
            {
                name: 'On Time',
                values: data.map(d => d.completed_on_time),
                chartType: 'bar'
            },
            {
                name: 'Late',
                values: data.map(d => d.completed_late),
                chartType: 'bar'
            }
        ]
    };

    const chartContainer = page.main.find('.kpi-chart')[0];
    
    // Clear previous chart
    chartContainer.innerHTML = '';

    // Create new chart using Frappe Charts
    new frappe.Chart(chartContainer, {
        title: `Completion Breakdown ${viewType}`,
        data: chartData,
        type: 'bar',
        height: 280,
        colors: ['#28a745', '#ffc107'],
        barOptions: {
            stacked: true,
            spaceRatio: 0.3
        }
    });
}

function getRankBadge(rank) {
    if (rank === 1) {
        return '<span style="font-size: 20px;">🥇</span>';
    } else if (rank === 2) {
        return '<span style="font-size: 20px;">🥈</span>';
    } else if (rank === 3) {
        return '<span style="font-size: 20px;">🥉</span>';
    }
    return `<span style="background: #e9ecef; padding: 4px 10px; border-radius: 50%;">${rank}</span>`;
}

function getPerformanceColor(rate) {
    if (rate >= 90) return '#28a745';  // Green
    if (rate >= 75) return '#17a2b8';  // Blue
    if (rate >= 50) return '#ffc107';  // Yellow
    return '#dc3545';  // Red
}
