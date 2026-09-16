/**
 * Centre pane — conversation header, 24h window banner and message thread.
 *
 * Bubbles are pinned by class (`.wa-in` left, `.wa-out` right) rather than by
 * flex direction, so an Arabic Desk (`dir="rtl"` on the app root) does not
 * mirror inbound and outbound. Each text node carries `dir="auto"`.
 */

import * as api from "./api.js";
import { day_label, duration_label, hhmm, same_day, window_closes_at } from "./time.js";

const THREAD_LIMIT = 40;

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

/** sent ✓ · delivered ✓✓ · read ✓✓ blue · failed ⚠ */
function tick_html(status) {
	const value = (status || "").toLowerCase();
	if (value === "failed") {
		return `<span class="wa-tick wa-tick-failed" title="${esc(__("Failed"))}">⚠</span>`;
	}
	if (value === "read") {
		return `<span class="wa-tick wa-tick-read" title="${esc(__("Read"))}">✓✓</span>`;
	}
	if (value === "delivered") {
		return `<span class="wa-tick" title="${esc(__("Delivered"))}">✓✓</span>`;
	}
	if (value === "sent") {
		return `<span class="wa-tick" title="${esc(__("Sent"))}">✓</span>`;
	}
	return "";
}

function media_html(item) {
	if (!item.media_url) {
		return "";
	}
	const url = esc(item.media_url);
	const mime = (item.media_mime || "").toLowerCase();
	const kind = (item.content_type || "").toLowerCase();
	if (mime.startsWith("image/") || kind === "image" || kind === "sticker") {
		return `<a href="${url}" target="_blank" rel="noopener"><img class="wa-media" src="${url}" alt="${esc(
			__("Image")
		)}"></a>`;
	}
	if (mime.startsWith("video/") || kind === "video") {
		return `<video class="wa-media" controls preload="metadata" src="${url}"></video>`;
	}
	if (mime.startsWith("audio/") || kind === "audio") {
		return `<audio class="wa-audio" controls preload="none" src="${url}"></audio>`;
	}
	const filename = decodeURIComponent(String(item.media_url).split("/").pop() || "");
	return `<a class="wa-doc" href="${url}" target="_blank" rel="noopener"><span class="wa-doc-icon">📎</span><span class="wa-doc-name" dir="auto">${esc(
		filename
	)}</span></a>`;
}

export class Thread {
	constructor(opts) {
		this.$container = opts.container;
		this.inbox = opts.inbox;
		this.conversation = null;
		this.items = [];
		this.has_more = false;
		this.loading = false;
		this.countdown_timer = null;
		this.make();
	}

	make() {
		this.$container.html(`
			<div class="wa-thread-header"></div>
			<div class="wa-banner" hidden></div>
			<div class="wa-messages">
				<div class="wa-empty">${esc(__("Pick a conversation"))}</div>
			</div>
			<div class="wa-composer-host"></div>
		`);
		this.$header = this.$container.find(".wa-thread-header");
		this.$banner = this.$container.find(".wa-banner");
		this.$messages = this.$container.find(".wa-messages");
		this.$composer_host = this.$container.find(".wa-composer-host");

		this.$messages.on("click", ".wa-load-older", () => this.load_older());
	}

	clear() {
		this.conversation = null;
		this.items = [];
		this.$header.empty();
		this.$banner.attr("hidden", true);
		this.$messages.html(`<div class="wa-empty">${esc(__("Pick a conversation"))}</div>`);
		this.stop_countdown();
	}

	set_conversation(conv) {
		this.conversation = conv;
		this.render_header();
		this.render_banner();
		return this.load_messages();
	}

	// ── header ───────────────────────────────────────────────────────────

	render_header() {
		const conv = this.conversation;
		if (!conv) {
			return;
		}
		this.$header.html(`
			<div class="wa-head-main">
				<div class="wa-head-name" dir="auto">${esc(conv.display_name || conv.phone)}</div>
				<div class="wa-head-phone">${esc(conv.phone)}</div>
			</div>
			<div class="wa-head-controls">
				<div class="wa-status-control"></div>
				<div class="wa-assignee-control"></div>
				<div class="wa-head-actions"></div>
			</div>
			<div class="wa-head-tags"></div>
		`);

		this.make_status_control();
		this.make_assignee_control();
		this.render_tags();

		const $actions = this.$header.find(".wa-head-actions");
		const resolved = conv.status === "Resolved";
		$(`<button class="btn btn-xs ${resolved ? "btn-default" : "btn-primary"}">${esc(
			resolved ? __("Reopen") : __("Resolve")
		)}</button>`)
			.on("click", () => this.set_status(resolved ? "Open" : "Resolved"))
			.appendTo($actions);
	}

	make_status_control() {
		const $parent = this.$header.find(".wa-status-control");
		this.status_control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Select",
				fieldname: "wa_status",
				options: ["Open", "Pending", "Resolved"],
				placeholder: __("Status"),
				change: () => {
					if (this._setting_status) {
						return;
					}
					const value = this.status_control.get_value();
					if (value && value !== this.conversation.status) {
						this.set_status(value);
					}
				},
			},
			parent: $parent,
			render_input: true,
			only_input: true,
		});
		this._setting_status = true;
		this.status_control.set_value(this.conversation.status || "Open");
		this._setting_status = false;
	}

	make_assignee_control() {
		const $parent = this.$header.find(".wa-assignee-control");
		const conv = this.conversation;
		if (!this.inbox.meta.is_manager) {
			// Agents claim what is free and see who owns the rest.
			if (!conv.assigned_to) {
				$(`<button class="btn btn-xs btn-primary">${esc(__("Claim"))}</button>`)
					.on("click", () => this.claim())
					.appendTo($parent);
			} else {
				$parent.html(
					`<span class="wa-chip">${esc(conv.assigned_to_name || conv.assigned_to)}</span>`
				);
			}
			return;
		}
		this.assignee_control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "wa_assignee",
				options: "User",
				placeholder: __("Assign to…"),
				change: () => {
					if (this._setting_assignee) {
						return;
					}
					const user = this.assignee_control.get_value();
					if (!user) {
						this.unassign();
					} else if (user !== this.conversation.assigned_to) {
						this.assign(user);
					}
				},
			},
			parent: $parent,
			render_input: true,
			only_input: true,
		});
		this._setting_assignee = true;
		this.assignee_control.set_value(conv.assigned_to || "");
		this._setting_assignee = false;
	}

	render_tags() {
		const $tags = this.$header.find(".wa-head-tags");
		$tags.empty();
		(this.conversation.tags || []).forEach((tag) => {
			const dot = esc(tag.color || "var(--text-muted)");
			const $chip = $(
				`<span class="wa-chip wa-chip-tag"><span class="wa-tag-dot" style="background:${dot}"></span>${esc(
					tag.tag
				)}<span class="wa-chip-x" role="button">×</span></span>`
			);
			$chip.find(".wa-chip-x").on("click", () => this.remove_tag(tag.tag));
			$chip.appendTo($tags);
		});
		const $add = $(`<span class="wa-tag-add"></span>`).appendTo($tags);
		// Autocomplete, not a Link: `get_inbox_meta` already sent the tag list
		// (filtered to is_active=1, which a Link field would not be).
		this.tag_control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Autocomplete",
				fieldname: "wa_tag",
				placeholder: __("Add tag"),
				options: (this.inbox.meta.tags || []).map((t) => t.tag),
				change: () => {
					const tag = this.tag_control.get_value();
					if (tag) {
						this.tag_control.set_value("");
						this.add_tag(tag);
					}
				},
			},
			parent: $add,
			render_input: true,
			only_input: true,
		});
	}

	// ── header actions ───────────────────────────────────────────────────

	apply_conversation(row) {
		Object.assign(this.conversation, row);
		this.inbox.on_conversation_changed(this.conversation);
		this.render_header();
		this.render_banner();
	}

	set_status(status) {
		api.set_status(this.conversation.name, status)
			.then((row) => this.apply_conversation(row))
			.catch((err) => this.inbox.report(err));
	}

	claim() {
		api.claim(this.conversation.name)
			.then((row) => this.apply_conversation(row))
			.catch((err) => this.inbox.report(err));
	}

	assign(user) {
		api.assign(this.conversation.name, user)
			.then((row) => this.apply_conversation(row))
			.catch((err) => this.inbox.report(err));
	}

	unassign() {
		api.unassign(this.conversation.name)
			.then((row) => this.apply_conversation(row))
			.catch((err) => this.inbox.report(err));
	}

	add_tag(tag) {
		api.add_tag(this.conversation.name, tag)
			.then((tags) => {
				this.conversation.tags = tags;
				this.render_tags();
			})
			.catch((err) => this.inbox.report(err));
	}

	remove_tag(tag) {
		api.remove_tag(this.conversation.name, tag)
			.then((tags) => {
				this.conversation.tags = tags;
				this.render_tags();
			})
			.catch((err) => this.inbox.report(err));
	}

	// ── 24h window banner ────────────────────────────────────────────────

	render_banner() {
		const conv = this.conversation;
		if (!conv) {
			return;
		}
		this.stop_countdown();
		if (conv.window_open) {
			this.remaining = Number(conv.window_seconds_remaining) || 0;
			this.paint_open_banner();
			// A minute tick is enough for an hours-long countdown; the
			// authoritative value comes back with every reload.
			this.countdown_timer = setInterval(() => {
				this.remaining = Math.max(0, this.remaining - 60);
				if (this.remaining <= 0) {
					this.conversation.window_open = false;
					this.render_banner();
					this.inbox.composer.set_window(false);
					return;
				}
				this.paint_open_banner();
			}, 60000);
		} else {
			this.$banner
				.removeAttr("hidden")
				.attr("class", "wa-banner wa-banner-closed")
				.text(__("24h window closed — send a template"));
		}
		if (this.inbox.composer) {
			this.inbox.composer.set_window(!!conv.window_open);
		}
	}

	paint_open_banner() {
		this.$banner
			.removeAttr("hidden")
			.attr("class", "wa-banner wa-banner-open")
			.text(
				__("Free-text until {0} ({1})", [
					window_closes_at(this.remaining),
					duration_label(this.remaining),
				])
			);
	}

	stop_countdown() {
		if (this.countdown_timer) {
			clearInterval(this.countdown_timer);
			this.countdown_timer = null;
		}
	}

	// ── messages ─────────────────────────────────────────────────────────

	load_messages() {
		this.items = [];
		this.$messages.html(`<div class="wa-empty">${esc(__("Loading…"))}</div>`);
		return api
			.get_messages({ conversation: this.conversation.name, limit: THREAD_LIMIT })
			.then((res) => {
				this.items = (res && res.items) || [];
				this.has_more = !!(res && res.has_more);
				this.render_all();
				this.scroll_to_bottom();
			})
			.catch((err) => {
				this.$messages.html(`<div class="wa-empty">${esc(err.message)}</div>`);
			});
	}

	load_older() {
		if (this.loading || !this.items.length) {
			return;
		}
		this.loading = true;
		const before = this.items[0].creation;
		api.get_messages({
			conversation: this.conversation.name,
			before: before,
			limit: THREAD_LIMIT,
		})
			.then((res) => {
				this.loading = false;
				const older = (res && res.items) || [];
				this.has_more = !!(res && res.has_more);
				if (!older.length) {
					this.has_more = false;
				}
				this.items = older.concat(this.items);
				const height_before = this.$messages[0].scrollHeight;
				this.render_all();
				this.$messages[0].scrollTop = this.$messages[0].scrollHeight - height_before;
			})
			.catch((err) => {
				this.loading = false;
				this.inbox.report(err);
			});
	}

	render_all() {
		const parts = [];
		if (this.has_more) {
			const label = esc(__("Load older messages"));
			parts.push(
				`<div class="wa-older"><button class="btn btn-xs btn-default wa-load-older">${label}</button></div>`
			);
		}
		let previous = null;
		this.items.forEach((item) => {
			if (!previous || !same_day(previous.creation, item.creation)) {
				parts.push(`<div class="wa-day">${esc(day_label(item.creation))}</div>`);
			}
			parts.push(this.item_html(item));
			previous = item;
		});
		if (!this.items.length) {
			parts.push(`<div class="wa-empty">${esc(__("No messages yet"))}</div>`);
		}
		this.$messages.html(parts.join(""));
	}

	append_item(item) {
		if (!item || this.items.some((i) => i.id === item.id)) {
			return;
		}
		const previous = this.items[this.items.length - 1];
		this.items.push(item);
		this.$messages.find(".wa-empty").remove();
		if (!previous || !same_day(previous.creation, item.creation)) {
			this.$messages.append(`<div class="wa-day">${esc(day_label(item.creation))}</div>`);
		}
		this.$messages.append(this.item_html(item));
		this.scroll_to_bottom();
	}

	item_html(item) {
		if (item.kind === "note") {
			return `
				<div class="wa-bubble wa-note" data-id="${esc(item.id)}">
					<div class="wa-note-head">
						<span>${esc(item.author_name || item.author || __("System"))}</span>
						<span class="wa-note-type">${esc(__(item.note_type || "Note"))}</span>
					</div>
					<div class="wa-text" dir="auto">${esc(item.text)}</div>
					${media_html(item)}
					<div class="wa-meta"><span class="wa-time">${esc(hhmm(item.creation))}</span></div>
				</div>`;
		}

		const side = item.direction === "in" ? "wa-in" : "wa-out";
		const quote = item.reply_to_message_id
			? `<div class="wa-quote" dir="auto">${esc(item.reply_to_text || __("Replied message"))}</div>`
			: "";
		let caption = "";
		if (item.is_auto) {
			caption = `<div class="wa-auto">${esc(__("Automatic reply"))}</div>`;
		} else if (item.is_template) {
			caption = `<div class="wa-auto">${esc(
				__("Template: {0}", [item.template_name || ""])
			)}</div>`;
		} else if (item.sender_name) {
			caption = `<div class="wa-auto">${esc(item.sender_name)}</div>`;
		}
		const ticks = item.direction === "out" ? tick_html(item.status) : "";

		return `
			<div class="wa-bubble ${side}" data-id="${esc(item.id)}" data-message-id="${esc(
			item.message_id || ""
		)}">
				${caption}
				${quote}
				${media_html(item)}
				<div class="wa-text" dir="auto">${esc(item.text || item.caption || "")}</div>
				<div class="wa-meta">
					<span class="wa-time">${esc(hhmm(item.creation))}</span>
					<span class="wa-ticks">${ticks}</span>
				</div>
			</div>`;
	}

	/** Realtime `status` event — repaint one bubble's tick. */
	patch_status(message_id, status) {
		if (!message_id) {
			return;
		}
		const item = this.items.find((i) => i.message_id === message_id);
		if (item) {
			item.status = status;
		}
		this.$messages
			.find(`.wa-bubble[data-message-id="${message_id}"] .wa-ticks`)
			.html(tick_html(status));
	}

	scroll_to_bottom() {
		const el = this.$messages[0];
		if (el) {
			el.scrollTop = el.scrollHeight;
		}
	}
}
