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
import { avatar_html } from "./avatar.js";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export class ThreadHeader {
	constructor(opts) {
		this.thread = opts.thread;
		this.inbox = opts.thread.inbox;
		this.$header = opts.container;
		// What the strip was last drawn from, and whether a repaint is owed
		// because the user was typing in it when one came in.
		this.signature = null;
		this.pending_render = false;
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

	/** Everything the strip actually draws, as one comparable string.
	 *
	 *  Realtime hands us a whole ConvRow for a delivery tick too, and rebuilding
	 *  the controls for those threw away whatever the user was typing — and, in
	 *  the Autocomplete's case, fired an empty `change` that read as an
	 *  unassign. Comparing the drawn state makes every such event a no-op.
	 */
	header_signature(conv) {
		return JSON.stringify([
			conv.name || "",
			conv.status || "",
			conv.assigned_to || "",
			(conv.tags || []).map((t) => t.tag),
			conv.display_name || "",
			conv.phone || "",
			conv.avatar_url || "",
		]);
	}

	/** True while the cursor is in the status / assignee / tag controls. The
	 *  tag Autocomplete lives in `.wa-head-tags`, not in the controls strip. */
	focus_in_controls() {
		const active = document.activeElement;
		return !!active && $(active).closest(".wa-head-controls, .wa-head-tags").length > 0;
	}

	render_header() {
		const conv = this.conversation;
		if (!conv) {
			return;
		}
		// `thread.clear()` empties the strip behind our back.
		if (!this.$header.children().length) {
			this.signature = null;
		}
		const signature = this.header_signature(conv);
		if (signature === this.signature) {
			return;
		}
		if (this.focus_in_controls()) {
			// Tearing a control out from under the cursor is how the unassign
			// storm started. Owe the repaint instead and pay it on blur.
			this.pending_render = true;
			return;
		}
		this.signature = signature;
		this.pending_render = false;

		this.$header.html(`
			<div class="wa-head-main">
				${avatar_html(conv)}
				<div class="wa-head-who">
					<div class="wa-head-name" dir="auto">${esc(conv.display_name || conv.phone)}</div>
					<div class="wa-head-phone">${esc(conv.phone)}</div>
				</div>
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

		// `focusout` fires before focus lands, so let it settle first.
		this.$header.find(".wa-head-controls, .wa-head-tags").on("focusout", () => {
			setTimeout(() => {
				if (this.pending_render && !this.focus_in_controls()) {
					this.render_header();
				}
			}, 0);
		});
	}

	/** One small button, wired. */
	button($parent, label, variant, handler) {
		return $(`<button class="btn btn-xs ${variant}">${esc(label)}</button>`)
			.on("click", handler)
			.appendTo($parent);
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

	/** Pickup is everyone's job, and ownership is explicit:
	 *
	 *    unassigned      → Claim (managers get the picker as well)
	 *    assigned to me  → "You" + Release
	 *    assigned to X   → X, and for a manager the picker + Take over
	 */
	make_assignee_control() {
		const $parent = this.$header.find(".wa-assignee-control");
		const conv = this.conversation;
		const me = this.inbox.meta.me;
		const assigned = conv.assigned_to || "";
		const is_manager = !!this.inbox.meta.is_manager;

		if (!assigned) {
			// Managers used to get only the picker, which meant answering a
			// free thread left it unowned.
			this.button($parent, __("Claim"), "btn-primary", () => this.claim());
		} else if (assigned === me) {
			$(`<span class="wa-chip">${esc(__("You"))}</span>`).appendTo($parent);
			// The only way to unassign. Never a control that reads back empty.
			this.button($parent, __("Release"), "btn-default", () => this.unassign());
		} else {
			$(`<span class="wa-chip">${esc(conv.assigned_to_name || assigned)}</span>`).appendTo(
				$parent
			);
			if (is_manager) {
				this.button($parent, __("Take over"), "btn-default", () => this.assign(me));
			}
		}
		if (!is_manager) {
			return;
		}
		// Autocomplete, not a Link on User: a WhatsApp Manager who is not a
		// System Manager has no read permission on User, so a Link control's
		// search would come back empty (and 403 in the console). `get_inbox_meta`
		// already sent the agent roster the server is willing to disclose.
		const $pick = $(`<div class="wa-assignee-pick"></div>`).appendTo($parent);
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
					const user = this.assignee_control.get_value() || "";
					const current = this.conversation.assigned_to || "";
					// The control fires `change` **asynchronously**, after the
					// guard above is gone, with an empty value every time it is
					// rebuilt. Treating that as an unassign is what wrote ~10,000
					// "returned to the queue" notes.
					if (!user || user === current) {
						return;
					}
					this.assign(user);
				},
			},
			parent: $pick,
			render_input: true,
			only_input: true,
		});
		if (assigned) {
			this._setting_assignee = true;
			this.assignee_control.set_value(assigned);
			this._setting_assignee = false;
		}
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
			.then((tags) => this.apply_tags(tags))
			.catch((err) => this.inbox.report(err));
	}

	remove_tag(tag) {
		api.remove_tag(this.conversation.name, tag)
			.then((tags) => this.apply_tags(tags))
			.catch((err) => this.inbox.report(err));
	}

	/** Tags repaint on their own — keep the signature level with what is drawn
	 *  so the next realtime event does not rebuild the whole strip for them. */
	apply_tags(tags) {
		this.conversation.tags = tags;
		this.render_tags();
		this.signature = this.header_signature(this.conversation);
	}
}
