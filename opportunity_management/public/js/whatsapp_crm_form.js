/**
 * WhatsApp section on the Contact / Lead / Customer forms (`doctype_js`).
 *
 * One file serves three doctypes, so each handler is registered explicitly —
 * `frappe.ui.form.on(cur_frm.doctype, …)` is not usable here because the file
 * is loaded once per form and `cur_frm` is not yet the record we want when
 * the handlers are registered.
 *
 * The section is read-only on purpose: it lists the conversations already
 * linked to the record and routes into `/app/whatsapp-inbox`. Starting a NEW
 * conversation from a CRM record is deliberately absent — the inbox API has no
 * "create a conversation for this phone number" endpoint (see the W3 report),
 * and faking one client-side would insert an Outgoing `WhatsApp Message`
 * without a conversation row, which is exactly what the server hook exists to
 * prevent.
 */

frappe.provide("opportunity_management.whatsapp_crm");

const API = "opportunity_management.opportunity_management.whatsapp_api.";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

/** Route into the Desk inbox with a conversation pre-selected. */
function open_in_inbox(conversation) {
	frappe.route_options = { conversation: conversation };
	frappe.set_route("whatsapp-inbox");
}

opportunity_management.whatsapp_crm.open_in_inbox = open_in_inbox;

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
		callback: (r) => render_section(frm, r && r.message),
		// A user without inbox access simply gets no section; the permission
		// error is not worth a dialog on every Contact they open.
		error: () => {},
	});
}

opportunity_management.whatsapp_crm.refresh = load_conversations;

frappe.ui.form.on("Contact", { refresh: load_conversations });
frappe.ui.form.on("Lead", { refresh: load_conversations });
frappe.ui.form.on("Customer", { refresh: load_conversations });
