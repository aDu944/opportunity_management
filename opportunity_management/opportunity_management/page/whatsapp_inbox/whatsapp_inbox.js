/**
 * The three-pane Desk inbox was retired: the Team Inbox is now a web app at
 * `/inbox` (hooks.py `website_redirects` → public/inbox/). This page keeps its
 * name and roles so existing links, the workspace shortcut and the "Open in
 * Inbox" buttons on CRM / Conversation forms still land somewhere, and just
 * forwards to the new screen. Styles live in public/css/whatsapp_crm_form.css.
 */

frappe.pages["whatsapp-inbox"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Team Inbox"),
		single_column: true,
	});

	const $card = $(`
		<div class="wa-moved">
			<div class="wa-moved-card">
				<h3>${__("Team Inbox")}</h3>
				<p>${__("The inbox has moved to its own screen.")}</p>
				<button class="btn btn-primary btn-open-inbox">${__("Open the Team Inbox")}</button>
				<div class="wa-moved-url"></div>
			</div>
		</div>
	`);
	$(wrapper).find(".layout-main-section").append($card);
	$card.find(".btn-open-inbox").on("click", () => {
		window.open(wrapper.inbox_target || "/inbox", "_blank");
	});
	update_target(wrapper, false);
};

frappe.pages["whatsapp-inbox"].on_page_show = function (wrapper) {
	// The CRM form button (`whatsapp_crm_form.js`) and the Conversation form
	// button set `frappe.route_options.conversation` before routing here;
	// carry it over as the web app's hash deep link.
	update_target(wrapper, true);
};

function update_target(wrapper, consume) {
	const options = frappe.route_options || {};
	const conversation = options.conversation;
	wrapper.inbox_target = conversation
		? `/inbox#/chats/${encodeURIComponent(conversation)}`
		: "/inbox";
	if (conversation && consume) {
		delete frappe.route_options.conversation;
	}
	$(wrapper)
		.find(".wa-moved-url")
		.text(window.location.origin + wrapper.inbox_target);
}
