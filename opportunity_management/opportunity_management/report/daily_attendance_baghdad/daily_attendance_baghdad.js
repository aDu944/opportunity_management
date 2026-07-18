frappe.query_reports["Daily Attendance Baghdad"] = {
	filters: [
		{
			fieldname: "date",
			label: __("Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
	],
	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "status" && data && data.status) {
			let color = "#1a1a2e";
			const s = data.status;
			if (s.indexOf("Absent") !== -1) color = "#C62828";
			else if (s.indexOf("Late") !== -1 || s.indexOf("Outside Zone") !== -1)
				color = "#E65100";
			else if (s.indexOf("On Time") !== -1) color = "#2E7D32";
			else if (s.indexOf("On Leave") !== -1) color = "#1565C0";
			value = `<span style="font-weight:600;color:${color}">${value}</span>`;
		}
		return value;
	},
};
