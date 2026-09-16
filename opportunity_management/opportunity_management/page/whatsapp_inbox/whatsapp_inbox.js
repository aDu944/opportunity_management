frappe.provide("opportunity_management");

frappe.pages["whatsapp-inbox"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Inbox"),
		single_column: true,
	});

	// The app lives in a bundle so the seven ES modules ship as one asset and
	// are only fetched when somebody actually opens the inbox.
	frappe.require("whatsapp_inbox.bundle.js").then(() => {
		wrapper.whatsapp_inbox = new opportunity_management.WhatsAppInbox(page, wrapper);
		open_routed_conversation(wrapper);
	});
};

frappe.pages["whatsapp-inbox"].on_page_show = function (wrapper) {
	// Re-read on every show: the CRM form button (`whatsapp_crm_form.js`) and
	// the Conversation form button both set `frappe.route_options` and then
	// route here, which does not re-run `on_page_load` for a page already
	// built.
	open_routed_conversation(wrapper);
	if (wrapper.whatsapp_inbox) {
		wrapper.whatsapp_inbox.on_show();
	}
};

frappe.pages["whatsapp-inbox"].on_page_hide = function (wrapper) {
	if (wrapper.whatsapp_inbox) {
		wrapper.whatsapp_inbox.on_hide();
	}
};

function open_routed_conversation(wrapper) {
	const options = frappe.route_options || {};
	const conversation = options.conversation;
	if (!conversation) {
		return;
	}
	delete frappe.route_options.conversation;
	if (wrapper.whatsapp_inbox) {
		wrapper.whatsapp_inbox.open_conversation(conversation, { scroll_into_view: true });
	} else {
		// The bundle has not resolved yet; stash it for the constructor.
		wrapper.whatsapp_pending_conversation = conversation;
	}
}
