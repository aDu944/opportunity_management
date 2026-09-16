/**
 * Date formatting for the inbox: list timestamps, thread day separators and
 * the 24h window countdown.
 *
 * All labels go through `__()` so Arabic Desk users get Arabic weekday and
 * month names from the app's translation files — `toLocaleDateString` would
 * bypass Frappe's translation layer and disagree with the mobile app, which
 * uses hand-written Arabic tables for exactly these strings.
 */

const WEEKDAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

const MONTHS = [
	"Jan",
	"Feb",
	"Mar",
	"Apr",
	"May",
	"Jun",
	"Jul",
	"Aug",
	"Sep",
	"Oct",
	"Nov",
	"Dec",
];

/** Server datetimes arrive as "YYYY-MM-DD HH:mm:ss" in system time. */
export function to_date(value) {
	if (!value) {
		return null;
	}
	if (value instanceof Date) {
		return value;
	}
	try {
		const local = frappe.datetime.convert_to_user_tz(value);
		const parsed = frappe.datetime.str_to_obj(local);
		if (parsed && !isNaN(parsed.getTime())) {
			return parsed;
		}
	} catch (e) {
		// fall through to the plain parse below
	}
	const fallback = new Date(String(value).replace(" ", "T"));
	return isNaN(fallback.getTime()) ? null : fallback;
}

function pad(n) {
	return n < 10 ? "0" + n : String(n);
}

export function hhmm(value) {
	const date = to_date(value);
	if (!date) {
		return "";
	}
	return pad(date.getHours()) + ":" + pad(date.getMinutes());
}

function start_of_day(date) {
	return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Whole days between `date` and today — 0 today, 1 yesterday, … */
export function days_ago(value) {
	const date = to_date(value);
	if (!date) {
		return null;
	}
	const diff = start_of_day(new Date()) - start_of_day(date);
	return Math.round(diff / 86400000);
}

export function same_day(a, b) {
	const da = to_date(a);
	const db = to_date(b);
	if (!da || !db) {
		return false;
	}
	return start_of_day(da) === start_of_day(db);
}

/** Conversation-row timestamp: today HH:mm / Yesterday / weekday / d MMM. */
export function relative_time(value) {
	const date = to_date(value);
	if (!date) {
		return "";
	}
	const days = days_ago(date);
	if (days === 0) {
		return hhmm(date);
	}
	if (days === 1) {
		return __("Yesterday");
	}
	if (days > 1 && days < 7) {
		return __(WEEKDAYS[date.getDay()]);
	}
	return date.getDate() + " " + __(MONTHS[date.getMonth()]);
}

/** Thread day separator: Today / Yesterday / weekday, d MMM yyyy. */
export function day_label(value) {
	const date = to_date(value);
	if (!date) {
		return "";
	}
	const days = days_ago(date);
	if (days === 0) {
		return __("Today");
	}
	if (days === 1) {
		return __("Yesterday");
	}
	const label = date.getDate() + " " + __(MONTHS[date.getMonth()]);
	if (date.getFullYear() !== new Date().getFullYear()) {
		return __(WEEKDAYS[date.getDay()]) + ", " + label + " " + date.getFullYear();
	}
	return __(WEEKDAYS[date.getDay()]) + ", " + label;
}

/** "3h 12m" / "12m" — the free-text window countdown. */
export function duration_label(seconds) {
	const total = Math.max(0, Math.floor(Number(seconds) || 0));
	const hours = Math.floor(total / 3600);
	const minutes = Math.floor((total % 3600) / 60);
	if (hours > 0) {
		return __("{0}h {1}m", [hours, minutes]);
	}
	if (minutes > 0) {
		return __("{0}m", [minutes]);
	}
	return __("{0}s", [total]);
}

/** Wall-clock time the window closes, given the seconds the server reported. */
export function window_closes_at(seconds) {
	const at = new Date(Date.now() + Math.max(0, Number(seconds) || 0) * 1000);
	return pad(at.getHours()) + ":" + pad(at.getMinutes());
}
