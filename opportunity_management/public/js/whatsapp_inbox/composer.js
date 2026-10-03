/**
 * Bottom of the centre pane — free-text composer, note mode, attachments,
 * the emoji picker (`emoji.js`), the `/` quick-reply popover and the template
 * picker (`template_picker.js`).
 *
 * The picker is not a separate screen: when the 24h window is closed the same
 * host swaps its contents, because "what can I send right now" is one piece of
 * state, not two surfaces.
 */

import * as api from "./api.js";
import { EmojiPopover } from "./emoji.js";
import { TemplatePicker } from "./template_picker.js";

// Matches `.wa-input { min-height }` in whatsapp_inbox.css — one row of text
// plus the control's own padding.
const MIN_INPUT_HEIGHT = 38;
// The server throttles too (20 s per conversation); Meta shows the indicator
// for up to 25 s or until we reply.
const TYPING_INTERVAL_MS = 20000;

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export class Composer {
	constructor(opts) {
		this.$container = opts.container;
		this.inbox = opts.inbox;
		this.conversation = null;
		this.note_mode = false;
		this.window_open = true;
		// True when the thread belongs to someone else and we are not a
		// manager — the server would refuse the send anyway.
		this.locked = false;
		this.quick_replies = null;
		this.make();
	}

	make() {
		this.$container.html(`
			<div class="wa-composer-locked" hidden></div>
			<div class="wa-composer" hidden>
				<div class="wa-quick-popover" hidden></div>
				<div class="wa-composer-bar">
					<button class="btn btn-xs btn-default wa-attach" title="${esc(__("Attach"))}">📎</button>
					<button class="btn btn-xs btn-default wa-emoji-toggle" title="${esc(__("Emoji"))}">😊</button>
					<button class="btn btn-xs btn-default wa-note-toggle">${esc(__("Note"))}</button>
					<textarea class="form-control wa-input" rows="1" dir="auto"
						placeholder="${esc(__("Type a message"))}"></textarea>
					<button class="btn btn-xs btn-primary wa-send">${esc(__("Send"))}</button>
				</div>
			</div>
			<div class="wa-template-picker" hidden></div>
		`);
		this.$composer = this.$container.find(".wa-composer");
		this.$locked = this.$container.find(".wa-composer-locked");
		this.$input = this.$container.find(".wa-input");
		this.$popover = this.$container.find(".wa-quick-popover");
		this.$picker = this.$container.find(".wa-template-picker");
		this.picker = new TemplatePicker({ composer: this, $picker: this.$picker });

		this.$container.find(".wa-send").on("click", () => this.send());
		this.$container.find(".wa-attach").on("click", () => this.attach());
		this.$container.find(".wa-note-toggle").on("click", () => this.toggle_note());

		// Lives inside `.wa-composer`, so it is hidden with it whenever the
		// thread is locked or the template picker has the slot.
		const $emoji_btn = this.$container.find(".wa-emoji-toggle");
		this.emoji = new EmojiPopover({
			$host: this.$composer,
			$button: $emoji_btn,
			on_pick: (emoji) => this.insert_at_caret(emoji),
		});
		$emoji_btn.on("click", () => this.emoji.toggle());

		this.$input.on("keydown", (e) => {
			if (e.key === "Escape") {
				this.hide_popover();
				this.emoji.close();
				return;
			}
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$input.on("input", () => {
			this.autosize();
			this.maybe_popover();
			this.maybe_typing();
		});
	}

	autosize() {
		const el = this.$input[0];
		// A hidden textarea reports `scrollHeight` 0, which pinned the box to
		// `height: 0px` until the first keystroke.
		if (!el || el.offsetParent === null) {
			return;
		}
		el.style.height = "auto";
		el.style.height = Math.min(Math.max(el.scrollHeight, MIN_INPUT_HEIGHT), 160) + "px";
	}

	/** Replace the selection with `text` and leave the caret after it. */
	insert_at_caret(text) {
		const el = this.$input[0];
		if (!el || el.disabled) {
			return;
		}
		const value = el.value || "";
		const start = typeof el.selectionStart === "number" ? el.selectionStart : value.length;
		const end = typeof el.selectionEnd === "number" ? el.selectionEnd : start;
		el.value = value.slice(0, start) + text + value.slice(end);
		const caret = start + text.length;
		el.focus();
		el.setSelectionRange(caret, caret);
		// Same path as typing: autosize + the `/` quick-reply check.
		this.$input.trigger("input");
	}

	set_conversation(conv) {
		const same = !!(conv && this.conversation && conv.name === this.conversation.name);
		this.conversation = conv;
		if (!same) {
			// Switching threads clears the draft. A repaint of the *same*
			// thread — a claim, a status change — must not cost the agent what
			// they typed, and the inbox now repaints on every conversation
			// event so the lock can appear live.
			this.$input.val("");
			this.hide_popover();
			this.emoji.close();
		}
		this.apply_lock();
		this.set_window(conv ? !!conv.window_open : true);
	}

	/** Who may type here. The server enforces this (`_require_assignee` /
	 *  `_auto_claim` in `whatsapp_api_messages`); the box must not pretend
	 *  otherwise and let an agent write a message that will be refused. */
	apply_lock() {
		const conv = this.conversation;
		if (conv && conv.is_blocked) {
			// Nothing reaches a blocked contact; the thread shows the banner.
			this.locked = true;
			this.$locked.text(__("This contact is blocked")).removeAttr("hidden");
			return;
		}
		const assigned = (conv && conv.assigned_to) || "";
		const claimed_by_other = !!assigned && assigned !== this.inbox.meta.me;
		this.locked = claimed_by_other && !this.inbox.meta.is_manager;
		if (!claimed_by_other) {
			this.$locked.attr("hidden", true).empty();
			return;
		}
		// Managers keep the composer, but see the same line: replying here
		// takes the thread off its owner's desk.
		this.$locked
			.text(
				__("Claimed by {0} — only they can reply", [
					conv.assigned_to_name || assigned,
				])
			)
			.removeAttr("hidden");
	}

	/** Window open → free text; closed → the template picker takes the slot. */
	set_window(is_open) {
		this.window_open = !!is_open;
		// Reactions are free-form sends: same window + lock rules as typing.
		if (this.inbox.thread) {
			this.inbox.thread.set_can_react(!!this.conversation && this.window_open && !this.locked);
		}
		if (!this.conversation || this.locked || !(this.window_open || this.note_mode)) {
			// Every branch below except the free-text one hides the composer;
			// an open picker must not keep its document listeners behind it.
			this.emoji.close();
		}
		if (!this.conversation) {
			this.$composer.attr("hidden", true);
			this.$picker.attr("hidden", true);
			return;
		}
		if (this.locked) {
			// The notice sits outside the composer, so it is all that is left —
			// notes included: an agent who cannot reply has no business writing
			// on someone else's thread from here either.
			this.$composer.attr("hidden", true);
			this.$picker.attr("hidden", true);
			return;
		}
		if (this.window_open || this.note_mode) {
			this.$composer.removeAttr("hidden");
			this.$picker.attr("hidden", true);
			// Only now is the textarea measurable.
			this.autosize();
		} else {
			this.$composer.attr("hidden", true);
			this.picker.render();
		}
	}

	toggle_note() {
		this.note_mode = !this.note_mode;
		this.$container.find(".wa-note-toggle").toggleClass("active", this.note_mode);
		this.$composer.toggleClass("wa-note-mode", this.note_mode);
		this.$input.attr(
			"placeholder",
			this.note_mode ? __("Internal note — not sent to the customer") : __("Type a message")
		);
		// A note is always allowed: it never reaches Meta, so the closed window
		// must not lock the agent out of writing one.
		this.set_window(this.window_open);
	}

	/** "typing…" for the customer (when the setting is on): at most once per
	 *  TYPING_INTERVAL_MS while a non-empty reply is being written. */
	maybe_typing() {
		const settings = (this.inbox.meta && this.inbox.meta.settings) || {};
		const conv = this.conversation;
		if (!settings.typing_indicator || !conv || this.note_mode || !this.window_open) {
			return;
		}
		if (!(this.$input.val() || "").trim()) {
			return;
		}
		const now = Date.now();
		if (this.typing_at && this.typing_conv === conv.name && now - this.typing_at < TYPING_INTERVAL_MS) {
			return;
		}
		this.typing_at = now;
		this.typing_conv = conv.name;
		api.typing(conv.name).catch(() => {});
	}

	// ── sending ──────────────────────────────────────────────────────────

	send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.conversation) {
			return;
		}
		this.emoji.close();
		const conversation = this.conversation.name;
		const request = this.note_mode
			? api.add_note({ conversation, text })
			: api.send_message({ conversation, text });

		this.$input.prop("disabled", true);
		request
			.then((item) => {
				this.$input.prop("disabled", false).val("");
				this.autosize();
				this.inbox.on_item_sent(conversation, item);
			})
			.catch((err) => {
				// The draft stays in the box on every failure — a rejected send
				// must not cost the agent what they typed.
				this.$input.prop("disabled", false).focus();
				this.handle_send_error(err);
			});
	}

	handle_send_error(err) {
		if (err.exc_type === api.WINDOW_CLOSED) {
			if (this.conversation) {
				this.conversation.window_open = false;
			}
			this.inbox.thread.render_banner();
			this.set_window(false);
			return;
		}
		if (err.exc_type === api.META_SEND_ERROR) {
			if (!err.already_shown) {
				frappe.msgprint({
					title: __("WhatsApp rejected the message"),
					message: err.message,
					indicator: "red",
				});
			}
			return;
		}
		this.inbox.report(err);
	}

	attach() {
		if (!this.conversation) {
			return;
		}
		const conversation = this.conversation.name;
		new frappe.ui.FileUploader({
			doctype: "WhatsApp Conversation",
			docname: conversation,
			// Outbound media must be public at send time: frappe_whatsapp hands
			// Meta a URL to fetch (plan §1.6). The cron privatises it later.
			make_attachments_public: true,
			on_success: (file) => {
				const text = (this.$input.val() || "").trim();
				api.send_message({ conversation, text, attachment: file.file_url })
					.then((item) => {
						this.$input.val("");
						this.autosize();
						this.inbox.on_item_sent(conversation, item);
					})
					.catch((err) => this.handle_send_error(err));
			},
		});
	}

	// ── quick replies ────────────────────────────────────────────────────

	maybe_popover() {
		const value = this.$input.val() || "";
		const match = /(^|\s)\/([\w-]*)$/.exec(value);
		if (!match) {
			this.hide_popover();
			return;
		}
		this.show_popover(match[2] || "");
	}

	show_popover(query) {
		const render = () => {
			const needle = (query || "").toLowerCase();
			const hits = (this.quick_replies || []).filter((qr) => {
				if (!needle) {
					return true;
				}
				return (
					(qr.shortcut || "").toLowerCase().indexOf(needle) !== -1 ||
					(qr.title || "").toLowerCase().indexOf(needle) !== -1
				);
			});
			if (!hits.length) {
				this.hide_popover();
				return;
			}
			this.$popover
				.html(
					hits
						.map(
							(qr) =>
								`<div class="wa-quick-item" data-name="${esc(qr.name)}">
									<span class="wa-quick-shortcut">${esc(qr.shortcut || "")}</span>
									<span class="wa-quick-title" dir="auto">${esc(qr.title || "")}</span>
								</div>`
						)
						.join("")
				)
				.removeAttr("hidden");
			this.$popover.find(".wa-quick-item").on("click", (e) => {
				this.pick_quick_reply($(e.currentTarget).data("name"));
			});
		};

		if (this.quick_replies) {
			render();
			return;
		}
		api.get_quick_replies()
			.then((rows) => {
				this.quick_replies = rows || [];
				render();
			})
			.catch((err) => this.inbox.report(err));
	}

	hide_popover() {
		this.$popover.attr("hidden", true).empty();
	}

	pick_quick_reply(name) {
		const conversation = this.conversation ? this.conversation.name : undefined;
		// Placeholders are substituted server-side so Desk and mobile can never
		// render `{{customer}}` differently.
		api.render_quick_reply(name, conversation)
			.then((res) => {
				const value = (this.$input.val() || "").replace(/(^|\s)\/([\w-]*)$/, "$1");
				this.$input.val(value + ((res && res.text) || "")).focus();
				this.autosize();
				this.hide_popover();
			})
			.catch((err) => this.inbox.report(err));
	}
}
