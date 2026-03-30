frappe.pages['opportunity-calendar'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Opportunity Calendar',
		single_column: true
	});

	// Check if FullCalendar is available (loaded via app_include_js)
	if (typeof FullCalendar !== 'undefined') {
		new OpportunityCalendar(page);
	} else {
		// Fallback: load from CDN if not available
		console.warn('FullCalendar not loaded via app includes, loading from CDN...');

		// Load FullCalendar CSS from CDN
		$('<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/main.min.css">').appendTo('head');

		// Load FullCalendar core and plugins from CDN using script tags instead of $.getScript
		let scripts = [
			'https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/main.min.js',
			'https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/daygrid/main.min.js',
			'https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/timegrid/main.min.js',
			'https://cdn.jsdelivr.net/npm/fullcalendar@5.11.5/list/main.min.js'
		];

		let loadedScripts = 0;
		function loadScript(url) {
			let script = document.createElement('script');
			script.src = url;
			script.onload = function() {
				loadedScripts++;
				console.log(`Loaded script ${loadedScripts}/${scripts.length}: ${url}`);
				if (loadedScripts === scripts.length) {
					console.log('All FullCalendar scripts loaded from CDN');
					new OpportunityCalendar(page);
				}
			};
			script.onerror = function() {
				console.error('Failed to load FullCalendar script:', url);
				frappe.msgprint(__('Failed to load calendar library. Please refresh the page.'));
			};
			document.head.appendChild(script);
		}

		scripts.forEach(loadScript);
	}
}

class OpportunityCalendar {
	constructor(page) {
		this.page = page;
		this.filters = {};
		this.setup_page();
		this.setup_filters();
		this.init_calendar();
	}

	setup_page() {
		this.page.set_title_sub(__('View opportunities by closing date'));

		// Add refresh button
		this.page.add_button(__('Refresh'), () => {
			this.calendar.refetchEvents();
		}, {
			icon: 'refresh'
		});

		// Add "Create Opportunity" button
		this.page.add_button(__('New Opportunity'), () => {
			frappe.new_doc('Opportunity');
		}, {
			icon: 'add',
			primary: true
		});

		// Create calendar container
		this.$calendar_wrapper = $('<div class="calendar-wrapper" style="margin-top: 20px;">').appendTo(this.page.main);
	}

	setup_filters() {
		// Get filter options from backend
		frappe.call({
			method: 'opportunity_management.opportunity_management.page.opportunity_calendar.opportunity_calendar.get_filter_options',
			callback: (r) => {
				if (r.message) {
					this.filter_options = r.message;
					this.create_filters();
				}
			}
		});
	}

	create_filters() {
		// Status filter
		this.page.add_field({
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: ['', ...this.filter_options.statuses],
			change: () => {
				this.filters.status = this.page.fields_dict.status.get_value();
				this.calendar.refetchEvents();
			}
		});

		// Urgency filter
		this.page.add_field({
			fieldname: 'urgency_level',
			label: __('Urgency'),
			fieldtype: 'Select',
			options: ['', ...this.filter_options.urgency_levels],
			change: () => {
				this.filters.urgency_level = this.page.fields_dict.urgency_level.get_value();
				this.calendar.refetchEvents();
			}
		});

		// Owner filter
		this.page.add_field({
			fieldname: 'opportunity_owner',
			label: __('Owner'),
			fieldtype: 'Autocomplete',
			options: this.filter_options.owners,
			change: () => {
				this.filters.opportunity_owner = this.page.fields_dict.opportunity_owner.get_value();
				this.calendar.refetchEvents();
			}
		});

		// Responsible Engineer filter
		this.page.add_field({
			fieldname: 'custom_resp_eng',
			label: __('Responsible Engineer'),
			fieldtype: 'Autocomplete',
			options: this.filter_options.resp_engs,
			change: () => {
				this.filters.custom_resp_eng = this.page.fields_dict.custom_resp_eng.get_value();
				this.calendar.refetchEvents();
			}
		});
	}

	init_calendar() {
		const calendarEl = this.$calendar_wrapper[0];

		this.calendar = new FullCalendar.Calendar(calendarEl, {
			initialView: 'dayGridMonth',
			headerToolbar: {
				left: 'prev,next today',
				center: 'title',
				right: 'dayGridMonth,timeGridWeek,listWeek'
			},
			buttonText: {
				today: __('Today'),
				month: __('Month'),
				week: __('Week'),
				list: __('List')
			},
			height: 'auto',
			events: (info, successCallback, failureCallback) => {
				this.fetch_events(info.startStr, info.endStr, successCallback, failureCallback);
			},
			eventClick: (info) => {
				this.handle_event_click(info);
			},
			eventDidMount: (info) => {
				// Add tooltip with details
				const props = info.event.extendedProps;
				const tooltip = `
					<b>${info.event.title}</b><br>
					Status: ${props.status}<br>
					Urgency: ${props.urgency || 'N/A'}<br>
					Owner: ${props.owner || 'N/A'}<br>
					${props.resp_eng ? 'Engineer: ' + props.resp_eng + '<br>' : ''}
					${props.closing_date ? 'Closing: ' + frappe.datetime.str_to_user(props.closing_date) : ''}
				`;
				$(info.el).tooltip({
					title: tooltip,
					html: true,
					placement: 'top',
					container: 'body'
				});
			}
		});

		this.calendar.render();
	}

	fetch_events(start, end, successCallback, failureCallback) {
		frappe.call({
			method: 'opportunity_management.opportunity_management.page.opportunity_calendar.opportunity_calendar.get_calendar_events',
			args: {
				start: start,
				end: end,
				filters: JSON.stringify(this.filters)
			},
			callback: (r) => {
				if (r.message) {
					successCallback(r.message);
				} else {
					failureCallback();
				}
			},
			error: () => {
				failureCallback();
			}
		});
	}

	handle_event_click(info) {
		const opportunity_name = info.event.extendedProps.opportunity_name;

		// Open opportunity in a dialog or navigate to it
		const dialog = new frappe.ui.Dialog({
			title: __('Opportunity: {0}', [opportunity_name]),
			fields: [
				{
					fieldtype: 'HTML',
					options: this.get_opportunity_html(info.event)
				}
			],
			primary_action_label: __('Open Opportunity'),
			primary_action: () => {
				frappe.set_route('Form', 'Opportunity', opportunity_name);
				dialog.hide();
			},
			secondary_action_label: __('Close')
		});

		dialog.show();
	}

	get_opportunity_html(event) {
		const props = event.extendedProps;
		return `
			<div class="opportunity-details">
				<table class="table table-bordered">
					<tr>
						<th style="width: 40%">${__('Party')}</th>
						<td>${props.party || '-'}</td>
					</tr>
					<tr>
						<th>${__('Amount')}</th>
						<td>${frappe.format(props.amount, {fieldtype: 'Currency'})}</td>
					</tr>
					<tr>
						<th>${__('Status')}</th>
						<td><span class="badge badge-info">${props.status}</span></td>
					</tr>
					<tr>
						<th>${__('Urgency')}</th>
						<td><span class="badge" style="background-color: ${event.backgroundColor}">${props.urgency || 'N/A'}</span></td>
					</tr>
					<tr>
						<th>${__('Owner')}</th>
						<td>${props.owner || '-'}</td>
					</tr>
					<tr>
						<th>${__('Responsible Engineer')}</th>
						<td>${props.resp_eng || '-'}</td>
					</tr>
					<tr>
						<th>${__('Closing Date')}</th>
						<td>${props.closing_date ? frappe.datetime.str_to_user(props.closing_date) : '-'}</td>
					</tr>
				</table>
			</div>
		`;
	}
}
