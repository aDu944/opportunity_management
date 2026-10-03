/**
 * Closed-window template picker — takes the composer's slot once the 24h
 * window has closed (see `Composer.set_window`).
 *
 * `get_templates(conversation)` returns the rows with the best template for
 * the customer's language flagged `default` and sorted first; the picker
 * preselects it and offers a language switch (hidden when every approved
 * template is in one language) that filters the list.
 */

import * as api from "./api.js";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export function language_label(code) {
	if (code === "ar") {
		return "العربية";
	}
	if (code === "en") {
		return "English";
	}
	return code || "—";
}

export class TemplatePicker {
	constructor(opts) {
		this.composer = opts.composer;
		this.$picker = opts.$picker;
		// Per conversation: the default and the order depend on the customer.
		this.cache = {};
		this.language = null;
		this.$picker.on("click", ".wa-lang-chip", (e) => {
			this.set_language($(e.currentTarget).attr("data-lang"));
		});
	}

	get conversation() {
		return this.composer.conversation;
	}

	get templates() {
		return (this.conversation && this.cache[this.conversation.name]) || null;
	}

	render() {
		this.$picker.removeAttr("hidden");
		const conv = this.conversation;
		if (!conv) {
			return;
		}
		if (!this.templates) {
			const name = conv.name;
			this.$picker.html(`<div class="wa-empty">${esc(__("Loading templates…"))}</div>`);
			api.get_templates(name)
				.then((rows) => {
					this.cache[name] = rows || [];
					if (this.conversation && this.conversation.name === name) {
						this.language = null;
						this.render();
					}
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

		const languages = [];
		this.templates.forEach((t) => {
			if (languages.indexOf(t.language || "") === -1) {
				languages.push(t.language || "");
			}
		});
		const preselected = this.templates.find((t) => t.default) || this.templates[0];
		if (this.language === null || languages.indexOf(this.language) === -1) {
			this.language = preselected.language || "";
		}

		const chips =
			languages.length > 1
				? `<div class="wa-lang-switch">${languages
						.map(
							(code) =>
								`<button type="button" class="wa-lang-chip${
									code === this.language ? " active" : ""
								}" data-lang="${esc(code)}">${esc(language_label(code))}</button>`
						)
						.join("")}</div>`
				: "";

		this.$picker.html(`
			<div class="wa-picker-head">${esc(__("The 24h window is closed — send an approved template"))}</div>
			${chips}
			<div class="wa-picker-select"></div>
			<div class="wa-picker-params"></div>
			<div class="wa-picker-preview" dir="auto"></div>
			<div class="wa-picker-actions">
				<button class="btn btn-xs btn-primary wa-send-template">${esc(__("Send template"))}</button>
			</div>
		`);

		const rows = this.templates.filter((t) => (t.language || "") === this.language);
		const options = rows.map((t) => ({
			value: t.name,
			label: t.template_name + (t.language_code ? " (" + t.language_code + ")" : ""),
		}));
		this.control = frappe.ui.form.make_control({
			df: {
				fieldtype: "Select",
				fieldname: "wa_template",
				options: options,
				change: () => this.render_params(),
			},
			parent: this.$picker.find(".wa-picker-select"),
			render_input: true,
			only_input: true,
		});
		const initial = rows.find((t) => t.name === preselected.name) || rows[0];
		this.control.set_value(initial.name);
		this.render_params();
		this.$picker.find(".wa-send-template").on("click", () => this.send());
	}

	/** Switching language selects the first row of that language. */
	set_language(code) {
		if (code === this.language) {
			return;
		}
		this.language = code || "";
		this.render();
		const first = (this.templates || []).find((t) => (t.language || "") === this.language);
		if (first && this.control) {
			this.control.set_value(first.name);
			this.render_params();
		}
	}

	current() {
		const name = this.control && this.control.get_value();
		return (this.templates || []).find((t) => t.name === name);
	}

	render_params() {
		const template = this.current();
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
					change: () => this.render_preview(),
				},
				parent: $(`<div class="wa-param"></div>`).appendTo($params),
				render_input: true,
				only_input: true,
			});
			this.param_controls.push(control);
		}
		this.render_preview();
	}

	render_preview() {
		const template = this.current();
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

	send() {
		const template = this.current();
		if (!template || !this.conversation) {
			return;
		}
		const conversation = this.conversation.name;
		const params = (this.param_controls || []).map((c) => c.get_value() || "");
		api.send_template({ conversation, template: template.name, params: JSON.stringify(params) })
			.then((item) => this.composer.inbox.on_item_sent(conversation, item))
			.catch((err) => this.composer.handle_send_error(err));
	}
}
