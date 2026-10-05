// Messenger Settings: shows the webhook callback URL to paste into the Meta
// app (Messenger → Webhooks) and a "Test connection" button (GET /me with
// the Page token, manager-only on the server).

const MESSENGER_WEBHOOK_PATH =
	"/api/method/opportunity_management.opportunity_management.messenger_webhook.webhook";

frappe.ui.form.on("Messenger Settings", {
	refresh(frm) {
		const url = frappe.urllib.get_base_url() + MESSENGER_WEBHOOK_PATH;
		frm.set_intro(
			__("Callback URL for the Meta app's Messenger webhook: {0}", [
				`<code>${frappe.utils.escape_html(url)}</code>`,
			]) +
				"<br>" +
				__("Subscribe the Page to: messages, message_echoes, message_deliveries, message_reads, message_reactions, messaging_postbacks, messaging_referrals."),
			"blue"
		);
		frm.add_custom_button(__("Subscribe Page to webhook"), () => {
			frappe.call({
				method: "opportunity_management.opportunity_management.doctype.messenger_settings.messenger_settings.subscribe_page",
				freeze: true,
				callback(r) {
					const res = r.message || {};
					frappe.msgprint({
						title: __("Messenger"),
						message: res.ok
							? __("The Page is subscribed to: {0}", [
									frappe.utils.escape_html((res.fields || []).join(", ") || "—"),
							  ])
							: frappe.utils.escape_html(res.error || __("Unknown error")),
						indicator: res.ok ? "green" : "red",
					});
				},
			});
		});
		frm.add_custom_button(__("Test connection"), () => {
			frappe.call({
				method: "opportunity_management.opportunity_management.doctype.messenger_settings.messenger_settings.test_connection",
				freeze: true,
				callback(r) {
					const res = r.message || {};
					if (res.ok) {
						let msg = __("Connected to Page {0} ({1})", [
							frappe.utils.escape_html(res.name || ""),
							frappe.utils.escape_html(res.id || ""),
						]);
						if (res.warning) msg += "<br>" + frappe.utils.escape_html(res.warning);
						frappe.msgprint({ title: __("Messenger"), message: msg, indicator: res.warning ? "orange" : "green" });
						frm.reload_doc();
					} else {
						frappe.msgprint({
							title: __("Messenger"),
							message: frappe.utils.escape_html(res.error || __("Unknown error")),
							indicator: "red",
						});
					}
				},
			});
		});
	},
});
