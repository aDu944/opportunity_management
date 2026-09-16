/**
 * The conversation header strip: status select, assignee control, Claim and
 * Resolve/Reopen buttons, and the tag chips.
 *
 * Split out of `thread.js` purely for size — that file owns the message list,
 * the media bubbles and the 24h countdown, and the two together pushed past
 * the 500-line limit. Behaviour is unchanged: this class renders into the
 * same `.wa-thread-header` element, reads the live conversation off the Thread
 * (so there is still exactly one copy of it) and routes every mutation back
 * through `thread.apply_conversation`, which repaints the header and banner.
 */

import * as api from "./api.js";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export class ThreadHeader {
	constructor(opts) {
		this.thread = opts.thread;
		this.inbox = opts.thread.inbox;
		this.$header = opts.container;
	}

	/** The Thread owns the conversation object; this is a view onto it. */
	get conversation() {
		return this.thread.conversation;
	}

	/** Every server round trip lands here — the Thread repaints header + banner. */
	apply_conversation(row) {
		this.thread.apply_conversation(row);
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
		// Autocomplete, not a Link on User: a WhatsApp Manager who is not a
		// System Manager has no read permission on User, so a Link control's
		// search would come back empty (and 403 in the console). `get_inbox_meta`
		// already sent the agent roster the server is willing to disclose.
		this.assignee_control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Autocomplete",
				fieldname: "wa_assignee",
				options: (this.inbox.meta.agents || []).map((a) => ({
					label: a.full_name || a.user,
					value: a.user,
				})),
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
}
