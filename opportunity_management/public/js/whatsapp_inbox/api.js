/**
 * Thin typed wrapper over the whitelisted inbox contract (plan §1.7).
 *
 * Every call goes to `whatsapp_api.<name>` — the facade — never to the
 * `whatsapp_api_inbox` / `_messages` / `_crm` implementation modules, so the
 * endpoint paths stay stable if a function moves between files.
 *
 * The server raises typed errors (`WindowClosedError`, `MetaSendError`,
 * `NotAssigneeError`); Frappe surfaces the class name as `exc_type`. We
 * normalise that onto the rejected Error so callers can branch on
 * `err.exc_type` instead of matching translated message text.
 */

const BASE = "opportunity_management.opportunity_management.whatsapp_api.";

function first_server_message(server_messages) {
	if (!server_messages) {
		return "";
	}
	try {
		const list = JSON.parse(server_messages);
		if (!list || !list.length) {
			return "";
		}
		const first = typeof list[0] === "string" ? JSON.parse(list[0]) : list[0];
		return (first && (first.message || first.title)) || "";
	} catch (e) {
		return "";
	}
}

function strip(text) {
	if (!text) {
		return "";
	}
	if (frappe.utils && frappe.utils.strip_html) {
		return frappe.utils.strip_html(String(text));
	}
	return String(text).replace(/<[^>]*>/g, "");
}

export function normalize_error(raw) {
	const res = (raw && raw.responseJSON) || raw || {};
	const last = (frappe.last_response || {});
	const server_messages = res._server_messages || last._server_messages;
	const err = new Error(
		strip(res._error_message || res.message || first_server_message(server_messages)) ||
			__("The request failed")
	);
	err.exc_type = res.exc_type || last.exc_type || "";
	// Frappe's own request layer already rendered `_server_messages` in a
	// msgprint, so callers must not show it a second time.
	err.already_shown = !!server_messages;
	err.raw = res;
	return err;
}

/**
 * @param {string} method  bare endpoint name, e.g. "list_conversations"
 * @param {object} args
 * @param {object} [opts]  {freeze, freeze_message}
 * @returns {Promise<any>} resolves with `r.message`
 */
export function call(method, args, opts) {
	const options = opts || {};
	return new Promise((resolve, reject) => {
		frappe.call({
			method: BASE + method,
			args: args || {},
			freeze: !!options.freeze,
			freeze_message: options.freeze_message,
			callback: (r) => resolve(r ? r.message : null),
			error: (r) => reject(normalize_error(r)),
		});
	});
}

// Named helpers for the endpoints the Desk surface actually uses. They exist
// so a typo in a method name is a missing export, not a 404 at runtime.
export const get_inbox_meta = () => call("get_inbox_meta");
export const list_conversations = (args) => call("list_conversations", args);
export const get_conversation = (name) => call("get_conversation", { name });
export const get_unread_count = () => call("get_unread_count");
export const get_messages = (args) => call("get_messages", args);
export const send_message = (args) => call("send_message", args);
export const send_template = (args) => call("send_template", args);
export const add_note = (args) => call("add_note", args);
export const mark_read = (conversation) => call("mark_read", { conversation });
export const claim = (conversation) => call("claim", { conversation });
export const unassign = (conversation) => call("unassign", { conversation });
export const assign = (conversation, user) => call("assign", { conversation, user });
export const set_status = (conversation, status) => call("set_status", { conversation, status });
export const add_tag = (conversation, tag) => call("add_tag", { conversation, tag });
export const remove_tag = (conversation, tag) => call("remove_tag", { conversation, tag });
export const get_quick_replies = () => call("get_quick_replies");
export const render_quick_reply = (name, conversation) =>
	call("render_quick_reply", { name, conversation });
export const get_templates = () => call("get_templates");
export const link_crm = (conversation, doctype, name) =>
	call("link_crm", { conversation, doctype, name });
export const unlink_crm = (conversation, doctype) => call("unlink_crm", { conversation, doctype });
export const search_crm = (query) => call("search_crm", { query });
export const create_lead_from_conversation = (args) => call("create_lead_from_conversation", args);
export const get_inbox_stats = (from_date, to_date) =>
	call("get_inbox_stats", { from_date, to_date });

export const WINDOW_CLOSED = "WindowClosedError";
export const META_SEND_ERROR = "MetaSendError";
export const NOT_ASSIGNEE = "NotAssigneeError";
