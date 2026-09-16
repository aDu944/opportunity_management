/**
 * Bottom of the centre pane — free-text composer, note mode, attachments,
 * the `/` quick-reply popover and the template picker.
 *
 * The picker is not a separate screen: when the 24h window is closed the same
 * host swaps its contents, because "what can I send right now" is one piece of
 * state, not two surfaces.
 */

import * as api from "./api.js";

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
		this.templates = null;
		this.quick_replies = null;
		this.make();
	}

	make() {
		this.$container.html(`
			<div class="wa-composer" hidden>
				<div class="wa-quick-popover" hidden></div>
				<div class="wa-composer-bar">
					<button class="btn btn-xs btn-default wa-attach" title="${esc(__("Attach"))}">📎</button>
					<button class="btn btn-xs btn-default wa-note-toggle">${esc(__("Note"))}</button>
					<textarea class="form-control wa-input" rows="1" dir="auto"
						placeholder="${esc(__("Type a message"))}"></textarea>
					<button class="btn btn-xs btn-primary wa-send">${esc(__("Send"))}</button>
				</div>
			</div>
			<div class="wa-template-picker" hidden></div>
		`);
		this.$composer = this.$container.find(".wa-composer");
		this.$input = this.$container.find(".wa-input");
		this.$popover = this.$container.find(".wa-quick-popover");
		this.$picker = this.$container.find(".wa-template-picker");

		this.$container.find(".wa-send").on("click", () => this.send());
		this.$container.find(".wa-attach").on("click", () => this.attach());
		this.$container.find(".wa-note-toggle").on("click", () => this.toggle_note());

		this.$input.on("keydown", (e) => {
			if (e.key === "Escape") {
				this.hide_popover();
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
		});
	}

	autosize() {
		const el = this.$input[0];
		el.style.height = "auto";
		el.style.height = Math.min(el.scrollHeight, 160) + "px";
	}

	set_conversation(conv) {
		this.conversation = conv;
		this.$input.val("");
		this.autosize();
		this.hide_popover();
		this.set_window(conv ? !!conv.window_open : true);
	}

	/** Window open → free text; closed → the template picker takes the slot. */
	set_window(is_open) {
		this.window_open = !!is_open;
		if (!this.conversation) {
			this.$composer.attr("hidden", true);
			this.$picker.attr("hidden", true);
			return;
		}
		if (this.window_open || this.note_mode) {
			this.$composer.removeAttr("hidden");
			this.$picker.attr("hidden", true);
		} else {
			this.$composer.attr("hidden", true);
			this.render_template_picker();
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

	// ── sending ──────────────────────────────────────────────────────────

	send() {
		const text = (this.$input.val() || "").trim();
		if (!text || !this.conversation) {
			return;
		}
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

	// ── template picker ──────────────────────────────────────────────────

	render_template_picker() {
		this.$picker.removeAttr("hidden");
		if (!this.templates) {
			this.$picker.html(`<div class="wa-empty">${esc(__("Loading templates…"))}</div>`);
			api.get_templates()
				.then((rows) => {
					this.templates = rows || [];
					this.render_template_picker();
				})
				.catch((err) => {
					this.$picker.html(`<div class="wa-empty">${esc(err.message)}</div>`);
				});
			return;
		}
		if (!this.templates.length) {
			this.$picker.html(
				`<div class="wa-empty">${esc(
					__("No approved template is available. Submit one to Meta first.")
				)}</div>`
			);
			return;
		}

		this.$picker.html(`
			<div class="wa-picker-head">${esc(__("The 24h window is closed — send an approved template"))}</div>
			<div class="wa-picker-select"></div>
			<div class="wa-picker-params"></div>
			<div class="wa-picker-preview" dir="auto"></div>
			<div class="wa-picker-actions">
				<button class="btn btn-xs btn-primary wa-send-template">${esc(__("Send template"))}</button>
			</div>
		`);

		const options = this.templates.map((t) => ({
			value: t.name,
			label: t.template_name + (t.language_code ? " (" + t.language_code + ")" : ""),
		}));
		this.template_control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Select",
				fieldname: "wa_template",
				options: options,
				change: () => this.render_template_params(),
			},
			parent: this.$picker.find(".wa-picker-select"),
			render_input: true,
			only_input: true,
		});
		this.template_control.set_value(options[0].value);
		this.render_template_params();
		this.$picker.find(".wa-send-template").on("click", () => this.send_template());
	}

	current_template() {
		const name = this.template_control && this.template_control.get_value();
		return (this.templates || []).find((t) => t.name === name);
	}

	render_template_params() {
		const template = this.current_template();
		const $params = this.$picker.find(".wa-picker-params").empty();
		this.param_controls = [];
		if (!template) {
			return;
		}
		for (let i = 0; i < (template.param_count || 0); i++) {
			const control = frappe.ui.form.make_control({
				df: {
					fieldtype: "Data",
					fieldname: "wa_param_" + i,
					placeholder: __("Parameter {0}", [i + 1]),
					change: () => this.render_template_preview(),
				},
				parent: $(`<div class="wa-param"></div>`).appendTo($params),
				render_input: true,
				only_input: true,
			});
			this.param_controls.push(control);
		}
		this.render_template_preview();
	}

	render_template_preview() {
		const template = this.current_template();
		if (!template) {
			return;
		}
		let body = template.body || "";
		(this.param_controls || []).forEach((control, index) => {
			const value = control.get_value() || "{{" + (index + 1) + "}}";
			body = body.split("{{" + (index + 1) + "}}").join(value);
		});
		this.$picker.find(".wa-picker-preview").text(body);
	}

	send_template() {
		const template = this.current_template();
		if (!template || !this.conversation) {
			return;
		}
		const conversation = this.conversation.name;
		const params = (this.param_controls || []).map((c) => c.get_value() || "");
		api.send_template({ conversation, template: template.name, params: JSON.stringify(params) })
			.then((item) => this.inbox.on_item_sent(conversation, item))
			.catch((err) => this.handle_send_error(err));
	}
}
