/**
 * Emoji reactions in the Desk thread.
 *
 * Each message bubble shows its `reactions` as chips (ours tinted), and a
 * small ☺ button that opens a quick bar — 👍 ❤️ 😂 😮 😢 🙏 plus "more",
 * which reuses the composer's `EmojiPopover`. Picking our current emoji
 * again (or clicking our own chip) removes it (`emoji: ""`).
 *
 * Reacting is a free-form send, so the ☺ button only exists while the
 * window is open and the composer is not locked for this user: the thread
 * carries `.wa-can-react` and CSS shows the buttons only under it.
 */

import * as api from "./api.js";
import { EmojiPopover } from "./emoji.js";

const QUICK = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function own_emoji(item) {
	const ours = (item.reactions || []).find((r) => r.direction === "out");
	return ours ? ours.emoji : "";
}

/** Chips under a bubble; always present (possibly empty) so patching can
 *  replace it in place. */
export function reactions_html(item) {
	const chips = (item.reactions || [])
		.map((r) => {
			const out = r.direction === "out";
			const who = out ? r.by_name || r.by || __("You") : __("Customer");
			return `<span class="wa-reaction-chip${out ? " wa-reaction-out" : ""}"
				data-direction="${esc(r.direction)}" title="${esc(who)}">${esc(r.emoji)}</span>`;
		})
		.join("");
	return `<div class="wa-reactions">${chips}</div>`;
}

export function react_button_html(item) {
	if (item.kind !== "message" || !item.message_id) {
		return "";
	}
	return `<button type="button" class="wa-react-btn" title="${esc(__("React"))}">☺</button>`;
}

export class Reactions {
	constructor(opts) {
		this.thread = opts.thread;
		this.$messages = opts.$messages;
		this.$host = opts.$host;
		this.$bar = null;
		this.target = null;
		this.more = new EmojiPopover({
			$host: this.$host,
			$button: $("<span></span>"),
			on_pick: (emoji) => {
				this.more.close();
				this.send(this.target, emoji);
			},
		});
		this.more.$el.addClass("wa-react-popover");

		this.$messages.on("click", ".wa-react-btn", (e) => {
			e.stopPropagation();
			this.open_bar($(e.currentTarget).closest(".wa-bubble"));
		});
		this.$messages.on("click", ".wa-react-bar .wa-react-pick", (e) => {
			e.stopPropagation();
			const emoji = $(e.currentTarget).attr("data-emoji");
			const item = this.item(this.target);
			this.close_bar();
			// Our current emoji again → remove it.
			this.send(this.target, item && own_emoji(item) === emoji ? "" : emoji);
		});
		this.$messages.on("click", ".wa-react-bar .wa-react-more", (e) => {
			e.stopPropagation();
			this.open_more($(e.currentTarget));
		});
		// Clicking our own chip removes our reaction.
		this.$messages.on("click", ".wa-reaction-out", (e) => {
			if (!this.$messages.hasClass("wa-can-react")) {
				return;
			}
			const id = $(e.currentTarget).closest(".wa-bubble").attr("data-message-id");
			if (id) {
				this.send(id, "");
			}
		});
		this._outside = (e) => {
			if (this.$bar && !this.$bar[0].contains(e.target)) {
				this.close_bar();
			}
		};
	}

	item(message_id) {
		return (this.thread.items || []).find((i) => i.message_id === message_id);
	}

	open_bar($bubble) {
		this.close_bar();
		this.target = $bubble.attr("data-message-id");
		const item = this.item(this.target);
		if (!this.target || !item) {
			return;
		}
		const mine = own_emoji(item);
		this.$bar = $(`<div class="wa-react-bar">${QUICK.map(
			(e) =>
				`<button type="button" class="wa-react-pick${e === mine ? " active" : ""}" data-emoji="${esc(
					e
				)}">${esc(e)}</button>`
		).join("")}<button type="button" class="wa-react-pick wa-react-more" title="${esc(
			__("More")
		)}">＋</button></div>`).appendTo($bubble);
		document.addEventListener("mousedown", this._outside, true);
	}

	close_bar() {
		if (this.$bar) {
			this.$bar.remove();
			this.$bar = null;
		}
		document.removeEventListener("mousedown", this._outside, true);
	}

	/** The full picker, positioned at the bubble inside the thread pane. */
	open_more($button) {
		const host = this.$host[0].getBoundingClientRect();
		const rect = $button[0].getBoundingClientRect();
		const height = 260;
		let top = rect.bottom - host.top + 4;
		if (top + height > host.height) {
			top = Math.max(0, rect.top - host.top - height - 4);
		}
		this.close_bar();
		this.more.$button = $button;
		this.more.$el.css({ top: top + "px" });
		this.more.open();
	}

	send(message_id, emoji) {
		const conv = this.thread.conversation;
		if (!conv || !message_id) {
			return;
		}
		api.react({ conversation: conv.name, message_id, emoji: emoji || "" })
			.then((res) => {
				if (res) {
					this.thread.patch_reactions(res.message_id, res.reactions);
				}
			})
			.catch((err) => {
				const composer = this.thread.inbox.composer;
				if (composer && (err.exc_type === api.WINDOW_CLOSED || err.exc_type === api.META_SEND_ERROR)) {
					composer.handle_send_error(err);
					return;
				}
				this.thread.inbox.report(err);
			});
	}

	reset() {
		this.close_bar();
		this.more.close();
	}
}
