/**
 * The one avatar renderer, shared by the list row, the thread header and the
 * side panel card.
 *
 * Meta's Cloud API does not expose the customer's own WhatsApp profile photo,
 * so `conv_row.avatar_url` carries the `image` of the linked Contact / Lead /
 * Customer instead. When nothing is linked (or the record has no image) we
 * fall back to initials, which is what the list always drew.
 *
 * Split out rather than copied three times: the fallback rule is one decision,
 * and three copies of it would drift the first time it changes.
 */

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export function initials(row) {
	const source = ((row && (row.display_name || row.phone)) || "?").trim();
	const words = source.split(/\s+/).filter(Boolean);
	if (!words.length) {
		return "?";
	}
	if (words.length === 1) {
		return words[0].substr(0, 2).toUpperCase();
	}
	return (words[0][0] + words[1][0]).toUpperCase();
}

/** Private file URLs are fine here: same origin, and the reader is logged in. */
export function avatar_html(row) {
	if (row && row.avatar_url) {
		return `<img class="wa-avatar-img" src="${esc(row.avatar_url)}" alt="" dir="ltr">`;
	}
	return `<div class="wa-avatar">${esc(initials(row || {}))}</div>`;
}
