/**
 * Message info: clicking the time / ticks of an outgoing message opens a
 * small popover with who sent it and its Sent / Delivered / Read times (12-hour clock via
 * `time.js`) and, for a failed message, Meta's reason.
 *
 * The times are recorded from round 3 on (`sent_at` / `delivered_at` /
 * `read_at` on the ThreadItem, refreshed by the realtime `status` event);
 * older messages show "—".
 */

import { day_label, hhmm } from "./time.js";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function when(value) {
	return value ? `${day_label(value)}, ${hhmm(value)}` : "—";
}

/** Who sent an outgoing item: "Auto-reply" for the welcome / out-of-hours
 *  replies, "System" for a row ERPNext sent outside the inbox (no
 *  `sender_user`), "You" for the session user, else the sender's full name. */
export function sender_label(item) {
	if (item.is_auto) {
		return { text: __("Auto-reply"), me: false };
	}
	if (!item.sender_user) {
		return { text: __("System"), me: false };
	}
	if (item.sender_user === frappe.session.user) {
		return { text: __("You"), me: true };
	}
	return { text: item.sender_name || item.sender_user, me: false };
}

export class MessageInfo {
	constructor(opts) {
		this.thread = opts.thread;
		this.$messages = opts.$messages;
		this.$pop = null;
		this.$messages.on("click", ".wa-bubble.wa-out .wa-meta", (e) => {
			e.stopPropagation();
			const id = $(e.currentTarget).closest(".wa-bubble").attr("data-id");
			this.toggle(id, $(e.currentTarget));
		});
		this.on_doc_click = () => this.close();
	}

	toggle(id, $anchor) {
		const open_for = this.$pop && this.$pop.attr("data-for");
		this.close();
		if (open_for === id) {
			return;
		}
		const item = (this.thread.items || []).find((i) => String(i.id) === String(id));
		if (!item || item.kind === "note") {
			return;
		}
		const error = (item.status || "").toLowerCase() === "failed"
			? `<div class="wa-info-error" dir="auto">${esc(item.error || __("Failed"))}</div>`
			: "";
		this.$pop = $(`<div class="wa-info-pop" data-for="${esc(id)}">
				<div class="wa-kv"><span>${esc(__("Sent by"))}</span><span dir="auto">${esc(
			sender_label(item).text
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Sent"))}</span><span>${esc(when(item.sent_at))}</span></div>
				<div class="wa-kv"><span>${esc(__("Delivered"))}</span><span>${esc(
			when(item.delivered_at)
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Read"))}</span><span>${esc(when(item.read_at))}</span></div>
				${error}
			</div>`);
		$anchor.closest(".wa-bubble").append(this.$pop);
		$(document).on("click", this.on_doc_click);
	}

	close() {
		if (this.$pop) {
			this.$pop.remove();
			this.$pop = null;
		}
		$(document).off("click", this.on_doc_click);
	}
}
