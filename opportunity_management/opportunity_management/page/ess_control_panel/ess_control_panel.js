frappe.pages['ess-control-panel'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'ESS Control Panel',
        single_column: true,
    });

    new ESSControlPanel(page);
};

class ESSControlPanel {
    constructor(page) {
        this.page = page;
        this.METHOD = 'opportunity_management.opportunity_management.page.ess_control_panel.ess_control_panel';
        this.setup_page();
        this.load_all();
    }

    setup_page() {
        this.page.set_title_sub(__('ALKHORA Employee Self Service — App Management'));

        this.page.add_button(__('Refresh'), () => this.load_all(), { icon: 'refresh' });

        this.page.main.html(`
            <div style="padding: 20px; max-width: 1200px; margin: 0 auto;">

                <!-- Stats Row -->
                <div class="row" id="ess-stats" style="margin-bottom: 24px;"></div>

                <!-- Firebase Status -->
                <div class="card" id="ess-firebase-status" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">🔔 Firebase / FCM Status</h5>
                    <div id="ess-firebase-body">Loading…</div>
                </div>

                <!-- Broadcast Notification -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">📢 Broadcast Notification</h5>
                    <div class="row">
                        <div class="col-sm-4">
                            <input id="broadcast-title" class="form-control" placeholder="Title (e.g. Important Update)" style="margin-bottom: 8px;">
                        </div>
                        <div class="col-sm-5">
                            <input id="broadcast-body" class="form-control" placeholder="Message body" style="margin-bottom: 8px;">
                        </div>
                        <div class="col-sm-3">
                            <button class="btn btn-primary btn-sm" id="broadcast-btn" style="margin-top: 2px;">
                                Send to All Employees
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Test Notification -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">🧪 Test Notification</h5>
                    <div class="row">
                        <div class="col-sm-3">
                            <select id="test-employee" class="form-control" style="margin-bottom: 8px;">
                                <option value="">Select Employee…</option>
                            </select>
                        </div>
                        <div class="col-sm-3">
                            <input id="test-title" class="form-control" placeholder="Title" value="Test Notification" style="margin-bottom: 8px;">
                        </div>
                        <div class="col-sm-4">
                            <input id="test-body" class="form-control" placeholder="Body" value="This is a test from ESS Control Panel." style="margin-bottom: 8px;">
                        </div>
                        <div class="col-sm-2">
                            <button class="btn btn-warning btn-sm" id="test-btn" style="margin-top: 2px;">Send</button>
                        </div>
                    </div>
                </div>

                <!-- Employees FCM Status -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">👥 Employee FCM Token Status</h5>
                    <div id="ess-employees-table">Loading…</div>
                </div>

                <!-- Punch Locations -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <h5 style="margin: 0;">📍 Punch Geolocations</h5>
                        <a href="/app/punch-geolocation" class="btn btn-xs btn-default">Manage in ERPNext →</a>
                    </div>
                    <div id="ess-locations-table">Loading…</div>
                </div>

                <!-- Recent Check-ins -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">🕐 Recent Check-ins</h5>
                    <div id="ess-checkins-table">Loading…</div>
                </div>

                <!-- Error Log -->
                <div class="card" style="margin-bottom: 24px; padding: 16px;">
                    <h5 style="margin-bottom: 12px;">⚠️ FCM Error Log</h5>
                    <div id="ess-error-log">Loading…</div>
                </div>

            </div>
        `);

        this._bind_events();
    }

    _bind_events() {
        const $w = this.page.main;

        $w.find('#broadcast-btn').on('click', () => {
            const title = $w.find('#broadcast-title').val().trim();
            const body = $w.find('#broadcast-body').val().trim();
            if (!title || !body) { frappe.msgprint(__('Please fill in title and body.')); return; }
            frappe.confirm(`Send "${title}" to ALL active employees?`, () => {
                frappe.call({
                    method: `${this.METHOD}.broadcast_notification`,
                    args: { title, body },
                    callback: (r) => {
                        if (r.message) {
                            frappe.msgprint(__(`Sent: ${r.message.sent}, Failed: ${r.message.failed}`));
                        }
                    }
                });
            });
        });

        $w.find('#test-btn').on('click', () => {
            const employee_id = $w.find('#test-employee').val();
            const title = $w.find('#test-title').val().trim();
            const body = $w.find('#test-body').val().trim();
            if (!employee_id) { frappe.msgprint(__('Please select an employee.')); return; }
            frappe.call({
                method: `${this.METHOD}.send_test_notification`,
                args: { employee_id, title, body },
                callback: (r) => {
                    const status = r.message && r.message.status;
                    if (status === 'sent') {
                        frappe.show_alert({ message: __('Notification sent!'), indicator: 'green' });
                    } else {
                        frappe.show_alert({ message: __('Failed — check FCM Error Log below.'), indicator: 'red' });
                        this.load_error_log();
                    }
                }
            });
        });
    }

    load_all() {
        this.load_stats();
        this.load_employees();
        this.load_locations();
        this.load_checkins();
        this.load_error_log();
        this.load_settings();
    }

    load_stats() {
        frappe.call({
            method: `${this.METHOD}.get_dashboard_stats`,
            callback: (r) => {
                if (!r.message) return;
                const d = r.message;
                const tokenPct = d.total_employees > 0
                    ? Math.round((d.with_fcm_token / d.total_employees) * 100)
                    : 0;
                this.page.main.find('#ess-stats').html(`
                    ${this._stat_card('👥 Active Employees', d.total_employees, 'blue')}
                    ${this._stat_card('🔔 FCM Registered', `${d.with_fcm_token} / ${d.total_employees} (${tokenPct}%)`, d.without_fcm_token === 0 ? 'green' : 'orange')}
                    ${this._stat_card('✅ Check-ins Today', d.checkins_today, 'blue')}
                    ${this._stat_card('📋 Pending Leaves', d.pending_leaves, d.pending_leaves > 0 ? 'orange' : 'green')}
                    ${this._stat_card('💰 Pending Expenses', d.pending_expenses, d.pending_expenses > 0 ? 'orange' : 'green')}
                `);
            }
        });
    }

    _stat_card(label, value, color) {
        const colors = { blue: '#1565C0', green: '#2e7d32', orange: '#e65100' };
        const bg = { blue: '#e3f2fd', green: '#e8f5e9', orange: '#fff3e0' };
        const c = colors[color] || colors.blue;
        const b = bg[color] || bg.blue;
        return `
            <div class="col-sm-2" style="margin-bottom: 12px;">
                <div style="background: ${b}; border-radius: 12px; padding: 16px; text-align: center;">
                    <div style="font-size: 22px; font-weight: 800; color: ${c};">${value}</div>
                    <div style="font-size: 11px; color: #555; margin-top: 4px;">${label}</div>
                </div>
            </div>`;
    }

    load_settings() {
        frappe.call({
            method: `${this.METHOD}.get_ess_settings`,
            callback: (r) => {
                if (!r.message) return;
                const d = r.message;
                const fbStatus = d.firebase_configured
                    ? '<span class="badge badge-success">✓ Configured</span>'
                    : '<span class="badge badge-danger">✗ Not configured — add firebase_service_account to Site Config</span>';
                this.page.main.find('#ess-firebase-body').html(`
                    <table class="table table-bordered table-sm" style="max-width: 600px;">
                        <tr><td><strong>Firebase / FCM</strong></td><td>${fbStatus}</td></tr>
                        <tr><td><strong>Check-in Window</strong></td>
                            <td>${d.checkin_start_hour}:00 AM – ${d.checkin_end_hour}:00 AM
                            <small style="color:#888"> (configurable in mobile app code)</small></td></tr>
                    </table>
                `);
            }
        });
    }

    load_employees() {
        frappe.call({
            method: `${this.METHOD}.get_employees_fcm_status`,
            callback: (r) => {
                if (!r.message) return;
                const emps = r.message;

                // Populate test notification dropdown
                const $sel = this.page.main.find('#test-employee');
                $sel.find('option:not(:first)').remove();
                emps.forEach(e => {
                    if (e.has_token) {
                        $sel.append(`<option value="${e.name}">${e.employee_name}</option>`);
                    }
                });

                const rows = emps.map(e => `
                    <tr>
                        <td>${e.employee_name}</td>
                        <td><small style="color:#888">${e.name}</small></td>
                        <td>${e.department || '—'}</td>
                        <td>${e.designation || '—'}</td>
                        <td>
                            ${e.has_token
                                ? `<span style="color:green;">✓</span> <small style="color:#888;">${e.custom_fcm_token}</small>`
                                : '<span style="color:red;">✗ No token</span>'}
                        </td>
                    </tr>`).join('');

                this.page.main.find('#ess-employees-table').html(`
                    <div style="overflow-x: auto;">
                    <table class="table table-bordered table-sm">
                        <thead style="background:#f5f5f5;">
                            <tr>
                                <th>Employee</th><th>ID</th><th>Department</th>
                                <th>Designation</th><th>FCM Token</th>
                            </tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                    </div>
                `);
            }
        });
    }

    load_locations() {
        frappe.call({
            method: `${this.METHOD}.get_punch_locations`,
            callback: (r) => {
                if (!r.message) return;
                const locs = r.message;
                const rows = locs.map(l => `
                    <tr>
                        <td><a href="/app/punch-geolocation/${l.name}">${l.location_name}</a></td>
                        <td>${l.custom_location_name_ar || '—'}</td>
                        <td>${l.latitude || '—'}</td>
                        <td>${l.longitude || '—'}</td>
                        <td>${l.radius} m</td>
                    </tr>`).join('');

                this.page.main.find('#ess-locations-table').html(`
                    <table class="table table-bordered table-sm">
                        <thead style="background:#f5f5f5;">
                            <tr>
                                <th>Name (EN)</th><th>Name (AR)</th>
                                <th>Latitude</th><th>Longitude</th><th>Radius</th>
                            </tr>
                        </thead>
                        <tbody>${rows || '<tr><td colspan="5" style="text-align:center;color:#888">No locations configured</td></tr>'}</tbody>
                    </table>
                `);
            }
        });
    }

    load_checkins() {
        frappe.call({
            method: `${this.METHOD}.get_recent_checkins`,
            args: { limit: 50 },
            callback: (r) => {
                if (!r.message) return;
                const checkins = r.message;
                const rows = checkins.map(c => {
                    const outside = c.custom_outside_zone
                        ? '<span style="color:#e65100;font-weight:bold;">⚠ Outside Zone</span>'
                        : '';
                    const typeColor = c.log_type === 'IN' ? 'green' : 'red';
                    return `
                        <tr>
                            <td>${c.employee_name || c.employee}</td>
                            <td><span style="color:${typeColor};font-weight:bold;">${c.log_type}</span></td>
                            <td>${frappe.datetime.str_to_user(c.time)}</td>
                            <td>${outside}</td>
                            <td>${c.latitude ? `${parseFloat(c.latitude).toFixed(5)}, ${parseFloat(c.longitude).toFixed(5)}` : '—'}</td>
                            <td><a href="/app/employee-checkin/${c.name}" style="font-size:11px;">View</a></td>
                        </tr>`;
                }).join('');

                this.page.main.find('#ess-checkins-table').html(`
                    <div style="overflow-x: auto;">
                    <table class="table table-bordered table-sm">
                        <thead style="background:#f5f5f5;">
                            <tr>
                                <th>Employee</th><th>Type</th><th>Time</th>
                                <th>Flag</th><th>Coordinates</th><th></th>
                            </tr>
                        </thead>
                        <tbody>${rows || '<tr><td colspan="6" style="text-align:center;color:#888">No check-ins found</td></tr>'}</tbody>
                    </table>
                    </div>
                `);
            }
        });
    }

    load_error_log() {
        frappe.call({
            method: `${this.METHOD}.get_notification_log`,
            args: { limit: 20 },
            callback: (r) => {
                if (!r.message) return;
                const logs = r.message;
                if (!logs.length) {
                    this.page.main.find('#ess-error-log').html(
                        '<p style="color:green;">✓ No FCM errors found.</p>'
                    );
                    return;
                }
                const rows = logs.map(l => `
                    <tr>
                        <td><small>${frappe.datetime.str_to_user(l.creation)}</small></td>
                        <td><small>${l.method || '—'}</small></td>
                        <td><small style="color:#c00;">${(l.error || '').substring(0, 200)}</small></td>
                    </tr>`).join('');

                this.page.main.find('#ess-error-log').html(`
                    <table class="table table-bordered table-sm">
                        <thead style="background:#fff3e0;">
                            <tr><th>Time</th><th>Method</th><th>Error</th></tr>
                        </thead>
                        <tbody>${rows}</tbody>
                    </table>
                `);
            }
        });
    }
}
