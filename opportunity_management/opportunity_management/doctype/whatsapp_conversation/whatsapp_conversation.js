/**
 * The Conversation form is the raw record; day-to-day work happens in the
 * Desk inbox, so the only thing this adds is the way back to it.
 */

frappe.ui.form.on("WhatsApp Conversation", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Open in Inbox"), () => {
			frappe.route_options = { conversation: frm.doc.name };
			frappe.set_route("whatsapp-inbox");
		}).addClass("btn-primary");
	},
});
