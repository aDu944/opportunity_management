frappe.pages['employee-team-assignment'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Employee Team Assignment',
		single_column: false
	});

	new EmployeeTeamAssignment(page);
}

class EmployeeTeamAssignment {
	constructor(page) {
		this.page = page;
		this.employees = [];
		this.departments = [];
		this.selected_assignments = {};

		this.setup_page();
		this.load_data();
	}

	setup_page() {
		this.page.set_title_sub(__('Manage employee department assignments'));

		// Add buttons
		this.page.add_button(__('Refresh'), () => {
			this.load_data();
		}, {
			icon: 'refresh'
		});

		this.page.add_button(__('Create Department'), () => {
			this.create_department_dialog();
		}, {
			icon: 'add'
		});

		this.page.add_button(__('Save All Changes'), () => {
			this.bulk_save_assignments();
		}, {
			icon: 'save',
			primary: true
		});

		// Create layout
		this.page.main.html(`
			<div class="employee-team-assignment">
				<div class="row">
					<div class="col-md-12">
						<div class="stats-section" style="margin-bottom: 20px;"></div>
					</div>
				</div>
				<div class="row">
					<div class="col-md-3">
						<div class="filters-section card" style="padding: 15px;">
							<h5>Filters</h5>
							<div class="filter-controls"></div>
						</div>
					</div>
					<div class="col-md-9">
						<div class="employees-section card" style="padding: 15px;"></div>
					</div>
				</div>
			</div>
		`);
	}

	load_data() {
		// Load employees
		frappe.call({
			method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.get_employees_with_teams',
			callback: (r) => {
				if (r.message) {
					this.employees = r.message;
					this.render_employees();
				}
			}
		});

		// Load departments
		frappe.call({
			method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.get_all_departments',
			callback: (r) => {
				if (r.message) {
					this.departments = r.message;
					this.render_filters();
				}
			}
		});

		// Load stats
		frappe.call({
			method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.get_employee_stats',
			callback: (r) => {
				if (r.message) {
					this.render_stats(r.message);
				}
			}
		});
	}

	render_stats(data) {
		const stats = data.stats || {};
		const breakdown = data.department_breakdown || [];

		let html = `
			<div class="row">
				<div class="col-md-3">
					<div class="card" style="background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
						<h3 style="margin: 0; color: #333;">${stats.total_employees || 0}</h3>
						<p style="margin: 0; color: #666;">Total Employees</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="background: #28a745; color: white; padding: 15px; border-radius: 8px;">
						<h3 style="margin: 0;">${stats.assigned || 0}</h3>
						<p style="margin: 0;">Assigned to Teams</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="background: #ffc107; padding: 15px; border-radius: 8px;">
						<h3 style="margin: 0;">${stats.unassigned || 0}</h3>
						<p style="margin: 0;">Unassigned</p>
					</div>
				</div>
				<div class="col-md-3">
					<div class="card" style="background: #17a2b8; color: white; padding: 15px; border-radius: 8px;">
						<h3 style="margin: 0;">${stats.linked_to_user || 0}</h3>
						<p style="margin: 0;">Linked to Users</p>
					</div>
				</div>
			</div>
		`;

		this.page.main.find('.stats-section').html(html);
	}

	render_filters() {
		const $filters = this.page.main.find('.filter-controls');

		// Department filter
		let dept_options = '<option value="">All Departments</option>';
		this.departments.forEach(dept => {
			dept_options += `<option value="${dept.name}">${dept.department_name || dept.name}</option>`;
		});

		const filterHtml = `
			<div class="form-group">
				<label>Department</label>
				<select class="form-control dept-filter">
					${dept_options}
				</select>
			</div>
			<div class="form-group">
				<label>Status</label>
				<select class="form-control status-filter">
					<option value="">All</option>
					<option value="assigned">Assigned</option>
					<option value="unassigned">Unassigned</option>
					<option value="linked">Linked to User</option>
				</select>
			</div>
			<div class="form-group">
				<label>Search</label>
				<input type="text" class="form-control search-filter" placeholder="Search employees...">
			</div>
		`;

		$filters.html(filterHtml);

		// Attach event listeners
		$filters.find('.dept-filter, .status-filter, .search-filter').on('change keyup', () => {
			this.render_employees();
		});
	}

	render_employees() {
		const $section = this.page.main.find('.employees-section');

		// Get filter values
		const deptFilter = this.page.main.find('.dept-filter').val();
		const statusFilter = this.page.main.find('.status-filter').val();
		const searchFilter = this.page.main.find('.search-filter').val().toLowerCase();

		// Filter employees
		let filtered = this.employees.filter(emp => {
			// Department filter
			if (deptFilter && emp.department !== deptFilter) return false;

			// Status filter
			if (statusFilter === 'assigned' && !emp.department) return false;
			if (statusFilter === 'unassigned' && emp.department) return false;
			if (statusFilter === 'linked' && !emp.user_id) return false;

			// Search filter
			if (searchFilter) {
				const searchText = `${emp.employee_name} ${emp.user_full_name || ''} ${emp.designation || ''}`.toLowerCase();
				if (!searchText.includes(searchFilter)) return false;
			}

			return true;
		});

		if (!filtered.length) {
			$section.html(`
				<div style="text-align: center; padding: 40px; color: #666;">
					<h4>No employees found</h4>
					<p>Try adjusting your filters</p>
				</div>
			`);
			return;
		}

		// Build department options for dropdowns
		let dept_options = '<option value="">-- Select Department --</option>';
		this.departments.forEach(dept => {
			dept_options += `<option value="${dept.name}">${dept.department_name || dept.name}</option>`;
		});

		let html = `
			<h5>Employees (${filtered.length})</h5>
			<table class="table table-bordered" style="background: white; font-size: 13px;">
				<thead style="background: #f5f5f5;">
					<tr>
						<th style="width: 25%">Employee</th>
						<th style="width: 20%">User</th>
						<th style="width: 15%">Designation</th>
						<th style="width: 20%">Current Team</th>
						<th style="width: 20%">Assign to Team</th>
					</tr>
				</thead>
				<tbody>
		`;

		filtered.forEach(emp => {
			const currentDept = emp.department || '<span style="color: #999;">Not assigned</span>';
			const userBadge = emp.user_id
				? `<span class="badge badge-success" title="${emp.user_id}">✓ ${emp.user_full_name || emp.user_id}</span>`
				: '<span class="badge badge-secondary">No user</span>';

			html += `
				<tr data-employee="${emp.name}">
					<td>
						<strong>${emp.employee_name}</strong><br>
						<small style="color: #666;">${emp.name}</small>
					</td>
					<td>${userBadge}</td>
					<td>${emp.designation || '-'}</td>
					<td>${currentDept}</td>
					<td>
						<select class="form-control form-control-sm dept-select" data-employee="${emp.name}">
							${dept_options}
						</select>
					</td>
				</tr>
			`;
		});

		html += '</tbody></table>';
		$section.html(html);

		// Set current department values
		filtered.forEach(emp => {
			if (emp.department) {
				$section.find(`select[data-employee="${emp.name}"]`).val(emp.department);
			}
		});

		// Track changes
		$section.find('.dept-select').on('change', (e) => {
			const employee = $(e.target).data('employee');
			const department = $(e.target).val();

			if (department) {
				this.selected_assignments[employee] = department;
				$(e.target).closest('tr').addClass('table-warning');
			} else {
				delete this.selected_assignments[employee];
				$(e.target).closest('tr').removeClass('table-warning');
			}
		});
	}

	bulk_save_assignments() {
		const assignments = Object.keys(this.selected_assignments).map(emp => ({
			employee: emp,
			department: this.selected_assignments[emp]
		}));

		if (!assignments.length) {
			frappe.msgprint(__('No changes to save'));
			return;
		}

		frappe.confirm(
			`Are you sure you want to assign ${assignments.length} employee(s) to their selected teams?`,
			() => {
				frappe.call({
					method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.bulk_assign_employees',
					args: {
						assignments: JSON.stringify(assignments)
					},
					freeze: true,
					freeze_message: __('Saving assignments...'),
					callback: (r) => {
						if (r.message) {
							frappe.msgprint({
								title: __('Assignment Complete'),
								message: r.message.message,
								indicator: r.message.status === 'success' ? 'green' : 'orange'
							});

							// Reset selections
							this.selected_assignments = {};

							// Reload data
							this.load_data();
						}
					}
				});
			}
		);
	}

	create_department_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __('Create New Department'),
			fields: [
				{
					fieldname: 'department_name',
					label: __('Department Name'),
					fieldtype: 'Data',
					reqd: 1
				}
			],
			primary_action_label: __('Create'),
			primary_action: (values) => {
				frappe.call({
					method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.create_department',
					args: {
						department_name: values.department_name
					},
					callback: (r) => {
						if (r.message) {
							frappe.msgprint({
								title: __('Department Created'),
								message: r.message.message,
								indicator: r.message.status === 'success' ? 'green' : 'red'
							});

							if (r.message.status === 'success') {
								dialog.hide();
								this.load_data();
							}
						}
					}
				});
			}
		});

		dialog.show();
	}
}
