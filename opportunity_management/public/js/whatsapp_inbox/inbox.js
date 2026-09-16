/**
 * The three-pane Desk inbox (plan §2).
 *
 * Owns the layout, the `get_inbox_meta` bootstrap, the realtime subscription
 * and the wiring between the four panes. Everything that touches the server
 * goes through `api.js`; everything that renders lives in the pane classes.
 */

import * as api from "./api.js";
import { ConversationList } from "./conversation_list.js";
import { Thread } from "./thread.js";
import { Composer } from "./composer.js";
import { SidePanel } from "./side_panel.js";

const REALTIME_EVENT = "whatsapp_inbox";

export class WhatsAppInbox {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.meta = { is_manager: false, me: frappe.session.user, agents: [], tags: [] };
		this.current = null;
		this.visible = true;
		this.make_layout();
		this.bootstrap();
	}

	make_layout() {
		this.page.set_title_sub(__("Shared WhatsApp team inbox"));
		this.page.add_button(__("Refresh"), () => this.refresh_all(), { icon: "refresh" });

		this.$root = $(`
			<div class="wa-inbox">
				<div class="wa-pane wa-pane-list"></div>
				<div class="wa-pane wa-pane-thread"></div>
				<div class="wa-pane wa-pane-side"></div>
			</div>
		`).appendTo(this.page.main);

		// Arabic Desk flips the page, but bubble sides are pinned by class, so
		// inbound stays left and outbound stays right (plan §2).
		if (frappe.boot && frappe.boot.lang === "ar") {
			this.$root.attr("dir", "rtl");
		}

		this.list = new ConversationList({
			container: this.$root.find(".wa-pane-list"),
			inbox: this,
		});
		this.thread = new Thread({ container: this.$root.find(".wa-pane-thread"), inbox: this });
		this.composer = new Composer({ container: this.thread.$composer_host, inbox: this });
		this.side = new SidePanel({ container: this.$root.find(".wa-pane-side"), inbox: this });
	}

	bootstrap() {
		api.get_inbox_meta()
			.then((meta) => {
				this.meta = Object.assign(this.meta, meta || {});
				this.list.render_tag_filter(this.meta.tags);
				this.side.render_tabs();
				return this.list.refresh();
			})
			.then(() => this.refresh_counts())
			.then(() => {
				const pending = this.wrapper && this.wrapper.whatsapp_pending_conversation;
				if (pending) {
					delete this.wrapper.whatsapp_pending_conversation;
					this.open_conversation(pending);
				}
			})
			.catch((err) => this.report(err));
		this.subscribe();
	}

	refresh_all() {
		this.list.refresh();
		this.refresh_counts();
		if (this.current) {
			this.open_conversation(this.current.name);
		}
	}

	refresh_counts() {
		return api
			.get_unread_count()
			.then((counts) => this.list.set_counts(counts))
			.catch(() => {});
	}

	// ── opening a conversation ───────────────────────────────────────────

	open_conversation(name, opts) {
		if (!name) {
			return Promise.resolve();
		}
		return api
			.get_conversation(name)
			.then((conv) => {
				this.current = conv;
				this.list.set_active(name);
				this.composer.set_conversation(conv);
				this.side.set_conversation(conv);
				const loaded = this.thread.set_conversation(conv);
				if (opts && opts.scroll_into_view) {
					const $row = this.list.$body.find(`.wa-row[data-name="${name}"]`);
					if ($row.length && $row[0].scrollIntoView) {
						$row[0].scrollIntoView({ block: "nearest" });
					}
				}
				if (conv.unread_count) {
					this.mark_read(conv.name);
				}
				return loaded;
			})
			.catch((err) => this.report(err));
	}

	mark_read(name) {
		api.mark_read(name)
			.then(() => {
				this.list.patch_unread(name, 0);
				if (this.current && this.current.name === name) {
					this.current.unread_count = 0;
				}
				this.refresh_counts();
			})
			.catch(() => {});
	}

	/** A pane changed the conversation (status, assignment, tags, CRM). */
	on_conversation_changed(row, repaint_panes) {
		if (!row) {
			return;
		}
		this.list.upsert(row, { keep_unread: true });
		this.list.set_active(row.name);
		if (this.current && this.current.name === row.name) {
			Object.assign(this.current, row);
			if (repaint_panes) {
				this.side.set_conversation(this.current);
				this.thread.render_header();
			}
		}
		this.refresh_counts();
	}

	/** The composer sent something — show it immediately, no round trip. */
	on_item_sent(conversation, item) {
		if (this.current && this.current.name === conversation && item) {
			this.thread.append_item(item);
		}
		api.get_conversation(conversation)
			.then((conv) => {
				if (this.current && this.current.name === conversation) {
					Object.assign(this.current, conv);
					this.thread.conversation = this.current;
					this.thread.render_header();
					this.thread.render_banner();
				}
				this.list.upsert(conv, { keep_unread: true });
			})
			.catch(() => {});
	}

	report(err) {
		if (!err) {
			return;
		}
		// Frappe already rendered `_server_messages`; a second dialog would be
		// the same text twice.
		if (err.already_shown) {
			return;
		}
		frappe.msgprint({
			title: __("WhatsApp Inbox"),
			message: err.message || String(err),
			indicator: "red",
		});
	}

	// ── realtime (plan §1.8) ─────────────────────────────────────────────

	subscribe() {
		if (this.handler) {
			return;
		}
		this.handler = (payload) => this.on_realtime(payload);
		frappe.realtime.on(REALTIME_EVENT, this.handler);
	}

	unsubscribe() {
		if (!this.handler) {
			return;
		}
		frappe.realtime.off(REALTIME_EVENT, this.handler);
		this.handler = null;
	}

	on_realtime(payload) {
		if (!payload || !payload.conversation) {
			return;
		}
		const conv = payload.conversation;
		const is_open = this.current && this.current.name === conv.name;

		if (payload.event === "message") {
			if (is_open) {
				// Reading it right now: append and clear the badge rather than
				// letting an unread count appear behind the cursor.
				this.thread.append_item(payload.item);
				this.list.upsert(Object.assign({}, conv, { unread_count: 0 }));
				this.mark_read(conv.name);
			} else {
				this.list.upsert(conv);
				this.refresh_counts();
			}
			return;
		}

		if (payload.event === "status") {
			if (is_open) {
				this.thread.patch_status(payload.message_id, payload.status);
			}
			this.list.upsert(conv, { keep_unread: true });
			return;
		}

		if (payload.event === "conversation") {
			this.list.upsert(conv, { keep_unread: true });
			if (is_open) {
				Object.assign(this.current, conv);
				this.thread.render_header();
				this.side.set_conversation(this.current);
			}
			return;
		}

		if (payload.event === "read") {
			this.list.patch_unread(conv.name, 0);
			this.refresh_counts();
		}
	}

	// ── page lifecycle ───────────────────────────────────────────────────

	on_show() {
		this.visible = true;
		this.subscribe();
		this.refresh_counts();
	}

	on_hide() {
		this.visible = false;
		this.unsubscribe();
		this.thread.stop_countdown();
	}
}
