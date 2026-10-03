/**
 * Round-3 thread item bodies: location and contact cards, and the option
 * pills of an interactive (buttons / list) message we sent.
 *
 * `card_html(item)` returns "" for every other item, so `thread.js` can call
 * it unconditionally. When it returns a card, the thread skips the plain
 * `text` (which for these kinds is only the server's readable fallback).
 */

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function location_html(loc) {
	const has_point = loc.latitude != null && loc.longitude != null;
	const maps = has_point
		? `https://maps.google.com/?q=${encodeURIComponent(loc.latitude)},${encodeURIComponent(
				loc.longitude
		  )}`
		: "";
	const title = loc.name || __("Location");
	return `<div class="wa-card-msg wa-location">
			<div class="wa-card-msg-head"><span class="wa-card-icon">📍</span>
				<span class="wa-card-msg-title" dir="auto">${esc(title)}</span></div>
			${loc.address ? `<div class="wa-card-msg-sub" dir="auto">${esc(loc.address)}</div>` : ""}
			${
				maps
					? `<a class="wa-link" href="${esc(maps)}" target="_blank" rel="noopener">${esc(
							__("Open in Maps")
					  )}</a>`
					: ""
			}
		</div>`;
}

function contacts_html(contacts) {
	return contacts
		.map(
			(c) => `<div class="wa-card-msg wa-contact">
				<div class="wa-card-msg-head"><span class="wa-card-icon">👤</span>
					<span class="wa-card-msg-title" dir="auto">${esc(c.name || __("Contact"))}</span></div>
				${(c.phones || [])
					.map((p) => `<div class="wa-card-msg-sub" dir="ltr">${esc(p)}</div>`)
					.join("")}
				${c.org ? `<div class="wa-card-msg-sub" dir="auto">${esc(c.org)}</div>` : ""}
			</div>`
		)
		.join("");
}

function options_html(options) {
	return `<div class="wa-options">${options
		.map((o) => `<span class="wa-option-pill" dir="auto">${esc(o)}</span>`)
		.join("")}</div>`;
}

/** {html, replaces_text} — `replaces_text` hides the fallback text. */
export function card_html(item) {
	const kind = (item.content_type || "").toLowerCase();
	if (kind === "location" && item.location) {
		return { html: location_html(item.location), replaces_text: true };
	}
	if (kind === "contact" && item.contacts && item.contacts.length) {
		return { html: contacts_html(item.contacts), replaces_text: true };
	}
	if (kind === "interactive" && item.options && item.options.length) {
		// The body text stays; the pills sit under it, like WhatsApp's buttons.
		return { html: options_html(item.options), replaces_text: false };
	}
	return { html: "", replaces_text: false };
}
