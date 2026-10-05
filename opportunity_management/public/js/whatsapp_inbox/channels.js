/**
 * Channels of the team inbox (WhatsApp, Messenger) for the Desk panes.
 *
 * The server decides everything (inbox_channels.py): `get_inbox_meta()`
 * carries `channels` / `manager_channels` and per-agent `channels`, and each
 * ConvRow carries `channel`, `window_mode` and `caps`. The panes ask this
 * module instead of comparing channel names, so the UI follows `caps`.
 */

export const WHATSAPP = "WhatsApp";
export const MESSENGER = "Messenger";

// Inline glyphs (no icon font for either brand in Desk); `currentColor` lets
// the badge class pick the colour.
const GLYPHS = {
	WhatsApp: `<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5c-.2 0-.4.1-.6.3-.2.2-.8.8-.8 2s.8 2.3.9 2.5c.1.2 1.6 2.5 4 3.5 1.5.6 2.1.7 2.8.6.5-.1 1.5-.6 1.7-1.2.2-.6.2-1.1.2-1.2-.1-.1-.2-.2-.4-.3z"/></svg>`,
	Messenger: `<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M12 2C6.4 2 2 6.1 2 11.7c0 2.9 1.2 5.5 3.2 7.3v3.5l3.1-1.7c1.1.3 2.3.5 3.7.5 5.6 0 10-4.1 10-9.7S17.6 2 12 2zm1 13-2.5-2.7-5 2.7 5.5-5.8 2.6 2.7 4.9-2.7L13 15z"/></svg>`,
};

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export function channel_of(row) {
	return (row && row.channel) || WHATSAPP;
}

export function many_channels(meta) {
	return ((meta && meta.channels) || []).length > 1;
}

/** `caps` from the server; a row from an older server has none → WhatsApp. */
export function caps(row) {
	return Object.assign(
		{
			templates: true, reactions: true, voice: true, video: true, documents: true,
			location: true, contact: true, options: true, block: true, typing: true, forward: true,
		},
		(row && row.caps) || {}
	);
}

/** Manager of THIS conversation's channel (falls back to `is_manager`). */
export function is_manager_of(meta, row) {
	if (meta && Array.isArray(meta.manager_channels)) {
		return meta.manager_channels.indexOf(channel_of(row)) !== -1;
	}
	return !!(meta && meta.is_manager);
}

/** Agents who can work this conversation's channel (assign / transfer). */
export function agents_for(meta, row) {
	const channel = channel_of(row);
	return ((meta && meta.agents) || []).filter(
		(a) => !Array.isArray(a.channels) || a.channels.indexOf(channel) !== -1
	);
}

/** The small badge on a row / in the header — only when it tells something. */
export function badge_html(meta, row) {
	if (!many_channels(meta)) {
		return "";
	}
	const channel = channel_of(row);
	const cls = channel === MESSENGER ? "wa-channel-messenger" : "wa-channel-whatsapp";
	return `<span class="wa-channel-badge ${cls}" title="${esc(__(channel))}">${
		GLYPHS[channel] || ""
	}</span>`;
}

/** Banner text for a closed window, by channel. */
export function closed_text(row) {
	return channel_of(row) === MESSENGER
		? __("This customer must message you again before you can reply")
		: __("24h window closed — send a template");
}

export function human_agent_text() {
	return __("Replying as a human agent — allowed for 7 days after their last message");
}

/** Channel filter next to the scope tabs; hidden with a single channel. */
export function mount_filter(list, meta) {
	if (!many_channels(meta) || list.$channel_filter) {
		return;
	}
	const options = [["", __("All channels")]].concat(meta.channels.map((c) => [c, __(c)]));
	list.$channel_filter = $(`<div class="wa-channel-filter" role="tablist"></div>`);
	options.forEach(([value, label]) => {
		const glyph = value ? GLYPHS[value] || "" : "";
		$(`<button type="button" class="wa-scope wa-channel-option" data-channel="${esc(value)}">
				${glyph}<span class="wa-scope-label">${esc(label)}</span>
			</button>`).appendTo(list.$channel_filter);
	});
	list.$channel_filter.insertAfter(list.$scopes);
	const paint = () =>
		list.$channel_filter
			.find(".wa-channel-option")
			.each((_, el) => $(el).toggleClass("active", ($(el).data("channel") || "") === (list.channel || "")));
	list.$channel_filter.on("click", ".wa-channel-option", (e) => {
		list.channel = $(e.currentTarget).data("channel") || "";
		paint();
		list.refresh();
	});
	paint();
}
