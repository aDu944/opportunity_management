/**
 * WhatsApp section on the Contact / Lead / Customer forms (`doctype_js`).
 *
 * One file serves three doctypes, so each handler is registered explicitly —
 * `frappe.ui.form.on(cur_frm.doctype, …)` is not usable here because the file
 * is loaded once per form and `cur_frm` is not yet the record we want when
 * the handlers are registered.
 *
 * Two things happen on refresh: the dashboard section lists the conversations
 * already linked to the record, and — for users the server confirms have inbox
 * access — a "Start conversation" button opens a first outbound thread.
 *
 * That button always sends a **template**. Free text is impossible before the
 * customer has written to us (Meta's 24h customer-service window), so offering
 * a message box here would only produce a rejected send. The conversation row
 * itself is created server-side by `get_or_create_conversation`, never
 * client-side — an Outgoing `WhatsApp Message` without a conversation is
 * exactly what the server hook exists to prevent.
 */

frappe.provide("opportunity_management.whatsapp_crm");

const API = "opportunity_management.opportunity_management.whatsapp_api.";

// Where each doctype keeps the number WhatsApp is likely to be on. Contact is
// special-cased: its numbers live in the `phone_nos` child table.
const PHONE_FIELDS = {
	Lead: ["mobile_no", "phone", "whatsapp_no"],
	Customer: ["mobile_no", "phone"],
};

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

/** Promise wrapper over one whitelisted inbox endpoint. Frappe has already
 *  rendered `_server_messages` by the time we reject, so callers must not
 *  msgprint the error a second time. */
function call(method, args) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: API + method,
			args: args || {},
			callback: (r) => resolve(r ? r.message : null),
			error: (r) => reject(r),
		});
	});
}

/** Route into the Desk inbox with a conversation pre-selected. */
function open_in_inbox(conversation) {
	frappe.route_options = { conversation: conversation };
	frappe.set_route("whatsapp-inbox");
}

opportunity_management.whatsapp_crm.open_in_inbox = open_in_inbox;

// ── starting a conversation ──────────────────────────────────────────────────

/** Every number on the record, best candidate first. */
function candidate_phones(frm) {
	const out = [];
	const push = (value) => {
		const text = (value == null ? "" : String(value)).trim();
		if (text && out.indexOf(text) === -1) {
			out.push(text);
		}
	};
	if (frm.doctype === "Contact") {
		// A Contact can carry a landline and three mobiles; the one flagged
		// primary mobile is the one WhatsApp is actually registered against.
		const rows = (frm.doc.phone_nos || []).slice();
		rows.sort(
			(a, b) => (b.is_primary_mobile_no ? 1 : 0) - (a.is_primary_mobile_no ? 1 : 0)
		);
		rows.forEach((row) => push(row.phone));
		push(frm.doc.mobile_no);
		push(frm.doc.phone);
	} else {
		(PHONE_FIELDS[frm.doctype] || []).forEach((field) => push(frm.doc[field]));
	}
	return out;
}

/** Name to seed the conversation with when it is brand new. */
function display_name_of(frm) {
	const doc = frm.doc;
	if (frm.doctype === "Lead") {
		return doc.lead_name || doc.company_name || doc.name;
	}
	if (frm.doctype === "Customer") {
		return doc.customer_name || doc.name;
	}
	return [doc.first_name, doc.last_name].filter(Boolean).join(" ") || doc.name;
}

function start_dialog(frm, templates) {
	const phones = candidate_phones(frm);
	const by_name = {};
	templates.forEach((t) => {
		by_name[t.name] = t;
	});
	const max_params = templates.reduce((m, t) => Math.max(m, t.param_count || 0), 0);

	const fields = [
		{
			fieldtype: "Autocomplete",
			fieldname: "phone",
			label: __("WhatsApp number"),
			reqd: 1,
			options: phones,
			default: phones[0] || "",
			description: __("Local or +country format — the server normalises it."),
		},
	];

	if (templates.length) {
		fields.push({
			fieldtype: "Select",
			fieldname: "template",
			label: __("Template"),
			reqd: 1,
			options: templates.map((t) => ({ label: t.template_name, value: t.name })),
			default: templates[0].name,
			// `sync_template` is a hoisted declaration below; it runs on change,
			// long after this object is built.
			change: () => sync_template(),
		});
		fields.push({ fieldtype: "HTML", fieldname: "preview" });
		for (let i = 1; i <= max_params; i++) {
			fields.push({
				fieldtype: "Data",
				fieldname: "param_" + i,
				label: __("Parameter {0}", [i]),
				hidden: 1,
			});
		}
	} else {
		fields.push({
			fieldtype: "HTML",
			fieldname: "no_templates",
			options: `<div class="text-muted" dir="auto">${esc(
				__("No approved template is available. Submit one to Meta first.")
			)}</div>`,
		});
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Start conversation"),
		fields: fields,
		primary_action_label: templates.length ? __("Send") : __("Open in Inbox"),
		primary_action: (values) => submit(values),
	});

	function sync_template() {
		const template = by_name[dialog.get_value("template")] || {};
		const count = template.param_count || 0;
		for (let i = 1; i <= max_params; i++) {
			dialog.set_df_property("param_" + i, "hidden", i > count ? 1 : 0);
			// Hidden params must not be mandatory or the dialog can never submit.
			dialog.set_df_property("param_" + i, "reqd", i <= count ? 1 : 0);
		}
		dialog.fields_dict.preview.$wrapper.html(
			`<div class="text-muted small" dir="auto" style="white-space:pre-wrap">${esc(
				template.body || ""
			)}</div>`
		);
	}

	function submit(values) {
		const phone = (values.phone || "").trim();
		if (!phone) {
			frappe.msgprint(__("Enter a WhatsApp number"));
			return;
		}
		dialog.disable_primary_action();
		call("get_or_create_conversation", {
			phone: phone,
			display_name: display_name_of(frm),
		})
			.then((conv) => {
				if (!templates.length || !conv) {
					return conv;
				}
				const template = by_name[values.template] || {};
				const params = [];
				for (let i = 1; i <= (template.param_count || 0); i++) {
					params.push(values["param_" + i] || "");
				}
				return call("send_template", {
					conversation: conv.name,
					template: values.template,
					params: JSON.stringify(params),
				}).then(() => conv);
			})
			.then((conv) => {
				dialog.hide();
				open_in_inbox(conv.name);
			})
			.catch(() => {
				// Frappe already showed the server message; let the agent retry.
				dialog.enable_primary_action();
			});
	}

	if (templates.length) {
		sync_template();
	}
	dialog.show();
}

function open_start_dialog(frm) {
	call("get_templates")
		.then((templates) => start_dialog(frm, (templates || []).filter(Boolean)))
		// The error is already on screen; not being able to read the template
		// list is not the same as there being none, so we do not fake an empty one.
		.catch(() => {});
}

// ── dashboard section ────────────────────────────────────────────────────────

function render_section(frm, rows) {
	if (!rows || !rows.length) {
		return;
	}
	const html = $(`<div class="wa-crm-section"></div>`);
	rows.forEach((row) => {
		const unread = row.unread_count
			? `<span class="wa-unread-pill">${esc(row.unread_count)}</span>`
			: "";
		const $row = $(`
			<div class="wa-crm-conv">
				<div>
					<div dir="auto"><b>${esc(row.display_name || row.phone)}</b>
						<span class="text-muted">${esc(row.phone)}</span></div>
					<div class="text-muted small" dir="auto">${esc(row.last_message_preview || "")}</div>
				</div>
				<div>
					<span class="wa-chip">${esc(__(row.status || "Open"))}</span>
					${unread}
					<a class="wa-link" role="button">${esc(__("Open in Inbox"))}</a>
				</div>
			</div>
		`);
		$row.find("a").on("click", () => open_in_inbox(row.name));
		html.append($row);
	});
	frm.dashboard.add_section(html, __("WhatsApp"));
}

function load_conversations(frm) {
	if (frm.is_new()) {
		return;
	}
	frappe.call({
		method: API + "list_conversations_for_crm",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback: (r) => {
			render_section(frm, r && r.message);
			// The call succeeding *is* the access check — the endpoint calls
			// `_require_inbox_access()` first — so the button appears only for
			// users who could actually use it.
			frm.add_custom_button(
				__("Start conversation"),
				() => open_start_dialog(frm),
				__("WhatsApp")
			);
		},
		// A user without inbox access simply gets no section and no button; the
		// permission error is not worth a dialog on every Contact they open.
		error: () => {},
	});
}

opportunity_management.whatsapp_crm.refresh = load_conversations;

frappe.ui.form.on("Contact", { refresh: load_conversations });
frappe.ui.form.on("Lead", { refresh: load_conversations });
frappe.ui.form.on("Customer", { refresh: load_conversations });
