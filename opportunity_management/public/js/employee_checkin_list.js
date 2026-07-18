// Custom list-view indicators for Employee Checkin.
// Default HRMS only shows "Off-Shift" — we use a single shift so that's
// useless. Replace with statuses that actually help HR:
//   • Outside Zone  (orange) — employee punched from outside an approved area
//   • Late          (orange) — IN after 09:15
//   • On Time       (green)  — IN at/before 09:15
//   • Check Out     (blue)   — any OUT record
//   • Off-Shift     (yellow) — fallback if HRMS flagged it

(function () {
  const LATE_CUTOFF_HOUR = 9;
  const LATE_CUTOFF_MIN = 15;

  function isLate(timeStr) {
    if (!timeStr) return false;
    // timeStr format: "YYYY-MM-DD HH:MM:SS" or ISO
    const parts = timeStr.split(/[ T]/);
    if (parts.length < 2) return false;
    const [h, m] = parts[1].split(':').map((x) => parseInt(x, 10));
    if (isNaN(h) || isNaN(m)) return false;
    if (h > LATE_CUTOFF_HOUR) return true;
    if (h < LATE_CUTOFF_HOUR) return false;
    return m > LATE_CUTOFF_MIN;
  }

  frappe.listview_settings['Employee Checkin'] = {
    add_fields: ['offshift', 'custom_outside_zone', 'log_type', 'time'],
    get_indicator: function (doc) {
      if (cint(doc.custom_outside_zone)) {
        return [__('Outside Zone'), 'orange', 'custom_outside_zone,=,1'];
      }
      if (doc.log_type === 'OUT') {
        return [__('Check Out'), 'blue', 'log_type,=,OUT'];
      }
      if (doc.log_type === 'IN') {
        if (isLate(doc.time)) {
          return [__('Late'), 'orange', 'log_type,=,IN'];
        }
        return [__('On Time'), 'green', 'log_type,=,IN'];
      }
      if (cint(doc.offshift)) {
        return [__('Off-Shift'), 'yellow', 'offshift,=,1'];
      }
    },
    onload: function (listview) {
      listview.page.add_action_item(__('Fetch Shifts'), () => {
        const checkins = listview
          .get_checked_items()
          .map((checkin) => checkin.name);
        frappe.call({
          method:
            'hrms.hr.doctype.employee_checkin.employee_checkin.bulk_fetch_shift',
          freeze: true,
          args: { checkins },
        });
      });
      // Quick-jump to today's printable summary.
      listview.page.add_inner_button(
        __('Daily Attendance Report'),
        () => {
          frappe.set_route('query-report', 'Daily Attendance Baghdad', {
            date: frappe.datetime.get_today(),
          });
        }
      );
    },
  };
})();
