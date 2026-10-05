/**
 * Centre pane — conversation header, 24h window banner and message thread.
 *
 * Bubbles are pinned by class (`.wa-in` left, `.wa-out` right) rather than by
 * flex direction, so an Arabic Desk (`dir="rtl"` on the app root) does not
 * mirror inbound and outbound. Each text node carries `dir="auto"`.
 *
 * Stickers render as a bare image (no bubble surface); reactions live in
 * `reactions.js` and are patched into a bubble in place by `data-message-id`.
 */

import * as api from "./api.js";
import { day_label, duration_label, hhmm, same_day, window_closes_at } from "./time.js";
import { ThreadHeader } from "./thread_header.js";
import { Reactions, react_button_html, reactions_html } from "./reactions.js";
import { card_html } from "./cards.js";
import { MessageInfo, sender_label } from "./message_info.js";
import { linkify_html } from "./linkify.js";

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

const OGG_RE = /\.(ogg|oga|opus)(;|\?|$)/i;

/** Voice notes: the server's AAC copy (`audio_url`) plays everywhere; the
 *  Ogg/Opus original does not on Safari, so say a copy is on its way. */
function audio_html(item) {
	const src = item.audio_url || item.media_url;
	const pending =
		!item.audio_url && OGG_RE.test(String(item.media_url || ""))
			? `<div class="wa-audio-note">${esc(__("Preparing a playable copy…"))}</div>`
			: "";
	return `<audio class="wa-audio" controls preload="none" src="${esc(src)}"></audio>${pending}`;
}

function media_html(item) {
	if (!item.media_url) {
		return "";
	}
	const url = esc(item.media_url);
	const mime = (item.media_mime || "").toLowerCase();
	const kind = (item.content_type || "").toLowerCase();
	if (kind === "audio" || (mime.startsWith("audio/") && kind !== "document")) {
		return audio_html(item);
	}
	if (mime.startsWith("image/") || kind === "image" || kind === "sticker") {
		return `<a href="${url}" target="_blank" rel="noopener"><img class="wa-media" src="${url}" alt="${esc(
			__("Image")
		)}"></a>`;
	}
	if (mime.startsWith("video/") || kind === "video") {
		return `<video class="wa-media" controls preload="metadata" src="${url}"></video>`;
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
		this.header = new ThreadHeader({ container: this.$header, thread: this });
		this.reactions = new Reactions({
			thread: this,
			$messages: this.$messages,
			$host: this.$container,
		});

		this.info = new MessageInfo({ thread: this, $messages: this.$messages });

		this.$messages.on("click", ".wa-load-older", () => this.load_older());
	}

	clear() {
		this.conversation = null;
		this.items = [];
		this.$header.empty();
		this.reactions.reset();
		this.info.close();
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

	/** Delegated to `ThreadHeader`; kept as a method because `inbox.js` calls
	 *  `thread.render_header()` from three realtime handlers. */
	render_header() {
		if (this.conversation) {
			this.header.render_header();
		}
	}

	apply_conversation(row) {
		Object.assign(this.conversation, row);
		this.inbox.on_conversation_changed(this.conversation);
		this.render_header();
		this.render_banner();
	}

	// ── 24h window banner ────────────────────────────────────────────────

	render_banner() {
		const conv = this.conversation;
		if (!conv) {
			return;
		}
		this.stop_countdown();
		if (conv.is_blocked) {
			// The composer disables itself (composer.apply_lock).
			this.$banner
				.removeAttr("hidden")
				.attr("class", "wa-banner wa-banner-closed")
				.text(__("This contact is blocked — nothing can be sent until a manager unblocks them"));
		} else if (conv.window_open) {
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

	/** Called by the composer whenever the window or the lock changes. */
	set_can_react(flag) {
		this.$messages.toggleClass("wa-can-react", !!flag);
		if (!flag) {
			this.reactions.reset();
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
				this.apply_reaction_updates(res);
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
		if (!item) {
			return;
		}
		const index = this.items.findIndex((i) => i.id === item.id);
		if (index !== -1) {
			// A `message` event for an item we already show is an update
			// (e.g. its media just landed) — replace it in place.
			this.items[index] = item;
			const $old = this.$messages.find(`.wa-bubble[data-id="${CSS.escape(String(item.id))}"]`);
			if ($old.length) {
				$old.replaceWith(this.item_html(item));
			}
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
					<div class="wa-text" dir="auto">${linkify_html(item.text, esc)}</div>
					${media_html(item)}
					<div class="wa-meta"><span class="wa-time">${esc(hhmm(item.creation))}</span></div>
				</div>`;
		}

		const side = item.direction === "in" ? "wa-in" : "wa-out";
		const quote = item.reply_to_message_id
			? `<div class="wa-quote" dir="auto">${esc(item.reply_to_text || __("Replied message"))}</div>`
			: "";
		// Outgoing: who sent it (You / name / Auto-reply / System), plus the
		// template marker when it was one — `message_info.sender_label`.
		let caption = "";
		if (item.direction !== "in") {
			const who = sender_label(item);
			const parts = [who.text];
			if (item.is_template) {
				parts.push(__("Template: {0}", [item.template_name || ""]));
			}
			const cls = who.me ? "wa-auto wa-sender-me" : "wa-auto";
			caption = `<div class="${cls}" dir="auto">${esc(parts.join(" · "))}</div>`;
		}
		const ticks = item.direction === "out" ? tick_html(item.status) : "";
		const attrs = `data-id="${esc(item.id)}" data-message-id="${esc(item.message_id || "")}"`;
		const meta = `<div class="wa-meta">
					<span class="wa-time">${esc(hhmm(item.creation))}</span>
					<span class="wa-ticks">${ticks}</span>
				</div>`;

		if (item.is_sticker && item.media_url) {
			const url = esc(item.media_url);
			return `
			<div class="wa-bubble wa-sticker ${side}" ${attrs}>
				${react_button_html(item)}
				<a href="${url}" target="_blank" rel="noopener"><img class="wa-sticker-img" src="${url}" alt="${esc(
				__("Sticker")
			)}"></a>
				${reactions_html(item)}
				${meta}
			</div>`;
		}

		// Location / contact cards replace the fallback text; option pills
		// sit under it. Message bodies, captions and option bodies get
		// clickable links (`linkify.js`); quotes and the list preview stay plain.
		const card = card_html(item);
		const text = card.replaces_text
			? ""
			: `<div class="wa-text" dir="auto">${linkify_html(
					item.text || item.caption || "",
					esc
			  )}</div>`;
		return `
			<div class="wa-bubble ${side}" ${attrs}>
				${react_button_html(item)}
				${caption}
				${quote}
				${media_html(item)}
				${card.html}
				${text}
				${reactions_html(item)}
				${meta}
			</div>`;
	}

	/** Realtime `reaction` event / `reaction_updates` — repaint one bubble's chips. */
	patch_reactions(message_id, reactions) {
		if (!message_id) {
			return;
		}
		const item = this.items.find((i) => i.message_id === message_id);
		if (item) {
			item.reactions = reactions || [];
			item.reaction = item.reactions.length ? item.reactions[0].emoji : "";
		}
		this.$messages
			.find(`.wa-bubble[data-message-id="${CSS.escape(message_id)}"] .wa-reactions`)
			.replaceWith(reactions_html({ reactions: reactions || [] }));
	}

	apply_reaction_updates(res) {
		((res && res.reaction_updates) || []).forEach((u) =>
			this.patch_reactions(u.message_id, u.reactions)
		);
	}

	/** Realtime `status` event — repaint one bubble's tick. `extra` carries
	 *  the message-info keys the server stamped (sent_at, …, error). */
	patch_status(message_id, status, extra) {
		if (!message_id) {
			return;
		}
		const item = this.items.find((i) => i.message_id === message_id);
		if (item) {
			item.status = status;
			["sent_at", "delivered_at", "read_at", "error"].forEach((key) => {
				if (extra && extra[key]) {
					item[key] = extra[key];
				}
			});
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
