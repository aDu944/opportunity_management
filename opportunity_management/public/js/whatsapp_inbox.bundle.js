/**
 * Bundle entry for the Desk WhatsApp inbox (plan §2).
 *
 * `page/whatsapp_inbox/whatsapp_inbox.js` pulls this in with
 * `frappe.require("whatsapp_inbox.bundle.js")`, so the seven modules below
 * ship as one asset that is only fetched when the page is actually opened —
 * unlike `app_include_js`, which would load them on every Desk boot.
 */

import * as api from "./whatsapp_inbox/api.js";
import * as time from "./whatsapp_inbox/time.js";
import { WhatsAppInbox } from "./whatsapp_inbox/inbox.js";
import { ConversationList } from "./whatsapp_inbox/conversation_list.js";
import { Thread } from "./whatsapp_inbox/thread.js";
import { Composer } from "./whatsapp_inbox/composer.js";
import { SidePanel } from "./whatsapp_inbox/side_panel.js";

frappe.provide("opportunity_management");

opportunity_management.WhatsAppInbox = WhatsAppInbox;

// The pieces are exposed too, so a console session (or a later mobile-parity
// experiment) can reach one pane without re-importing the bundle.
opportunity_management.whatsapp = {
	api: api,
	time: time,
	WhatsAppInbox: WhatsAppInbox,
	ConversationList: ConversationList,
	Thread: Thread,
	Composer: Composer,
	SidePanel: SidePanel,
};
