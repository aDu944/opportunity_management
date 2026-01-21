frappe.pages['opportunity_kpi'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Opportunity KPI Dashboard',
        single_column: true
    });

    // Add refresh button
    page.set_primary_action('Refresh', () => {
        load_kpi_data(page);
    }, 'refresh');

    // Add date range filter
    page.add_field({
        fieldname: 'date_range',
        label: __('Date Range'),
        fieldtype: 'Select',
        options: 'All Time\nLast Month\nLast Quarter\nLast Year',
        default: 'All Time',
        change: () => {
            load_kpi_data(page);
        }
    });

    load_kpi_data(page);
};

function load_kpi_data(page) {
    page.main.html('<div class="text-center" style="padding: 50px;"><i class="fa fa-spinner fa-spin fa-3x"></i><p>Loading KPI data...</p></div>');
    
    let date_range_map = {
        'All Time': 'all',
        'Last Month': 'month',
        'Last Quarter': 'quarter',
        'Last Year': 'year'
    };
    
    let selected = page.fields_dict.date_range.get_value();
    let date_range = date_range_map[selected] || 'all';
    
    frappe.call({
        method: 'opportunity_management.opportunity_management.api.get_opportunity_kpi',
        args: { date_range: date_range },
        callback: function(r) {
            if (r.message) {
                render_kpi_dashboard(page, r.message);
            }
        }
    });
}

function render_kpi_dashboard(page, data) {
    // Main KPI cards
    let rateColor = data.on_time_rate >= 80 ? '#28a745' : (data.on_time_rate >= 60 ? '#ffc107' : '#dc3545');
    
    let html = `
        <div class="kpi-dashboard">
            <!-- Summary Cards -->
            <div class="row" style="margin-bottom: 30px;">
                <div class="col-md-3">
                    <div class="kpi-card" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 12px; text-align: center;">
                        <h2 style="margin: 0; font-size: 42px;">${data.total_closed}</h2>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">Total Closed</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="kpi-card" style="background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; padding: 25px; border-radius: 12px; text-align: center;">
                        <h2 style="margin: 0; font-size: 42px;">${data.completed_on_time}</h2>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">On Time</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="kpi-card" style="background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%); color: white; padding: 25px; border-radius: 12px; text-align: center;">
                        <h2 style="margin: 0; font-size: 42px;">${data.completed_late}</h2>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">Late</p>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="kpi-card" style="background: linear-gradient(135deg, ${rateColor} 0%, ${rateColor} 100%); color: white; padding: 25px; border-radius: 12px; text-align: center;">
                        <h2 style="margin: 0; font-size: 42px;">${data.on_time_rate}%</h2>
                        <p style="margin: 5px 0 0 0; opacity: 0.9;">On-Time Rate</p>
                    </div>
                </div>
            </div>

            <!-- Progress Ring -->
            <div class="row" style="margin-bottom: 30px;">
                <div class="col-md-6">
                    <div style="background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <h4 style="margin-bottom: 20px;">Overall Performance</h4>
                        <div style="text-align: center;">
                            ${renderProgressRing(data.on_time_rate)}
                        </div>
                        <p style="text-align: center; margin-top: 15px; color: #666;">
                            ${data.on_time_rate >= 80 ? '🎉 Excellent! Keep up the great work!' : 
                              data.on_time_rate >= 60 ? '👍 Good progress, room for improvement.' : 
                              '⚠️ Needs attention. Consider reviewing processes.'}
                        </p>
                    </div>
                </div>
                <div class="col-md-6">
                    <div style="background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                        <h4 style="margin-bottom: 20px;">Completion Breakdown</h4>
                        ${renderBarChart(data.completed_on_time, data.completed_late)}
                    </div>
                </div>
            </div>
    `;

    // User metrics table
    if (data.user_metrics && data.user_metrics.length > 0) {
        html += `
            <div style="background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h4 style="margin-bottom: 20px;">Performance by Employee</h4>
                <table class="table table-hover" style="margin: 0;">
                    <thead>
                        <tr style="background: #f8f9fa;">
                            <th>Rank</th>
                            <th>Employee</th>
                            <th style="text-align: center;">Total Closed</th>
                            <th style="text-align: center;">On Time</th>
                            <th style="text-align: center;">Late</th>
                            <th style="text-align: center;">On-Time Rate</th>
                            <th>Progress</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        data.user_metrics.forEach((user, index) => {
            let rateClass = user.on_time_rate >= 80 ? 'success' : (user.on_time_rate >= 60 ? 'warning' : 'danger');
            let medal = index === 0 ? '🥇' : (index === 1 ? '🥈' : (index === 2 ? '🥉' : ''));
            
            html += `
                <tr>
                    <td>${medal} ${index + 1}</td>
                    <td><strong>${user.user_name}</strong></td>
                    <td style="text-align: center;">${user.total}</td>
                    <td style="text-align: center; color: #28a745;">${user.on_time}</td>
                    <td style="text-align: center; color: #dc3545;">${user.late}</td>
                    <td style="text-align: center;">
                        <span class="badge badge-${rateClass}" style="padding: 5px 10px;">${user.on_time_rate}%</span>
                    </td>
                    <td style="width: 150px;">
                        <div style="background: #e9ecef; border-radius: 10px; height: 10px; overflow: hidden;">
                            <div style="background: ${user.on_time_rate >= 80 ? '#28a745' : (user.on_time_rate >= 60 ? '#ffc107' : '#dc3545')}; 
                                        height: 100%; width: ${user.on_time_rate}%;"></div>
                        </div>
                    </td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
    } else {
        html += `
            <div style="background: white; padding: 50px; border-radius: 12px; text-align: center; color: #666;">
                <i class="fa fa-chart-bar fa-3x" style="opacity: 0.3;"></i>
                <p style="margin-top: 15px;">No employee performance data available yet.</p>
            </div>
        `;
    }

    html += '</div>';
    
    page.main.html(html);
}

function renderProgressRing(percentage) {
    let circumference = 2 * Math.PI * 54;
    let offset = circumference - (percentage / 100) * circumference;
    let color = percentage >= 80 ? '#28a745' : (percentage >= 60 ? '#ffc107' : '#dc3545');
    
    return `
        <svg width="150" height="150" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="54" fill="none" stroke="#e9ecef" stroke-width="12"/>
            <circle cx="60" cy="60" r="54" fill="none" stroke="${color}" stroke-width="12"
                    stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
                    stroke-linecap="round" transform="rotate(-90 60 60)"/>
            <text x="60" y="60" text-anchor="middle" dy="0.3em" font-size="24" font-weight="bold" fill="${color}">
                ${percentage}%
            </text>
        </svg>
    `;
}

function renderBarChart(onTime, late) {
    let total = onTime + late;
    let onTimePercent = total > 0 ? (onTime / total * 100) : 0;
    let latePercent = total > 0 ? (late / total * 100) : 0;
    
    return `
        <div style="margin-top: 30px;">
            <div style="margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>On Time</span>
                    <span>${onTime} (${onTimePercent.toFixed(1)}%)</span>
                </div>
                <div style="background: #e9ecef; border-radius: 5px; height: 25px; overflow: hidden;">
                    <div style="background: #28a745; height: 100%; width: ${onTimePercent}%; transition: width 0.5s;"></div>
                </div>
            </div>
            <div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                    <span>Late</span>
                    <span>${late} (${latePercent.toFixed(1)}%)</span>
                </div>
                <div style="background: #e9ecef; border-radius: 5px; height: 25px; overflow: hidden;">
                    <div style="background: #dc3545; height: 100%; width: ${latePercent}%; transition: width 0.5s;"></div>
                </div>
            </div>
        </div>
    `;
}
