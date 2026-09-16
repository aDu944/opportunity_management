/**
 * Right pane — who this number is, what it is linked to, and (for managers)
 * the inbox analytics tab.
 *
 * CRM linking goes through `link_crm` / `search_crm` rather than a Link
 * control: agents are not granted read on Contact / Lead / Customer, and the
 * server endpoint is the thing that is allowed to look them up.
 */

import * as api from "./api.js";
import { day_label, duration_label } from "./time.js";

const CRM_DOCTYPES = ["Contact", "Lead", "Customer", "Opportunity"];

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

export class SidePanel {
	constructor(opts) {
		this.$container = opts.container;
		this.inbox = opts.inbox;
		this.conversation = null;
		this.tab = "details";
		this.make();
	}

	make() {
		this.$container.html(`
			<div class="wa-side-tabs"></div>
			<div class="wa-side-body">
				<div class="wa-empty">${esc(__("Pick a conversation"))}</div>
			</div>
		`);
		this.$tabs = this.$container.find(".wa-side-tabs");
		this.$body = this.$container.find(".wa-side-body");
		this.render_tabs();
	}

	render_tabs() {
		this.$tabs.empty();
		const tabs = [["details", __("Details")]];
		if (this.inbox.meta.is_manager) {
			tabs.push(["analytics", __("Analytics")]);
		}
		tabs.forEach(([key, label]) => {
			$(`<button type="button" class="wa-side-tab ${
				this.tab === key ? "active" : ""
			}">${esc(label)}</button>`)
				.on("click", () => {
					this.tab = key;
					this.render_tabs();
					this.render();
				})
				.appendTo(this.$tabs);
		});
	}

	set_conversation(conv) {
		this.conversation = conv;
		this.render();
	}

	render() {
		if (this.tab === "analytics") {
			this.render_analytics();
			return;
		}
		this.render_details();
	}

	// ── details ──────────────────────────────────────────────────────────

	render_details() {
		const conv = this.conversation;
		if (!conv) {
			this.$body.html(`<div class="wa-empty">${esc(__("Pick a conversation"))}</div>`);
			return;
		}
		const language = conv.customer_language
			? conv.customer_language.toUpperCase()
			: __("Unknown");

		this.$body.html(`
			<div class="wa-card">
				<div class="wa-card-title" dir="auto">${esc(conv.display_name || conv.phone)}</div>
				<div class="wa-kv"><span>${esc(__("Phone"))}</span><span>${esc(conv.phone)}</span></div>
				<div class="wa-kv"><span>${esc(__("Account"))}</span><span>${esc(
			conv.whatsapp_account || "—"
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Language"))}</span><span>${esc(language)}</span></div>
				<div class="wa-kv"><span>${esc(__("Status"))}</span><span>${esc(
			__(conv.status || "Open")
		)}</span></div>
			</div>
			<div class="wa-card wa-crm"></div>
			<div class="wa-card wa-opps"></div>
			<div class="wa-card wa-meta-card">
				<div class="wa-card-title">${esc(__("Meta"))}</div>
				<div class="wa-kv"><span>${esc(__("First contact"))}</span><span>${esc(
			conv.first_contact_at ? day_label(conv.first_contact_at) : "—"
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Assigned"))}</span><span>${esc(
			conv.assigned_at ? day_label(conv.assigned_at) : "—"
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Resolved"))}</span><span>${esc(
			conv.resolved_at ? day_label(conv.resolved_at) : "—"
		)}</span></div>
				<div class="wa-kv"><span>${esc(__("Notes"))}</span><span>${esc(
			conv.notes_count || 0
		)}</span></div>
			</div>
		`);
		this.render_crm();
		this.render_opportunities();
	}

	render_crm() {
		const conv = this.conversation;
		const $crm = this.$body.find(".wa-crm");
		$crm.html(`<div class="wa-card-title">${esc(__("CRM"))}</div>`);

		CRM_DOCTYPES.forEach((doctype) => {
			const key = doctype.toLowerCase();
			const value = conv[key];
			const label = conv[key + "_name"] || value;
			const $row = $(`<div class="wa-kv wa-crm-row">
					<span>${esc(__(doctype))}</span>
					<span class="wa-crm-value" dir="auto">${esc(label || "—")}</span>
					<span class="wa-crm-actions"></span>
				</div>`).appendTo($crm);
			const $actions = $row.find(".wa-crm-actions");
			if (value) {
				$(`<a href="/app/${esc(frappe.router.slug(doctype))}/${encodeURIComponent(
					value
				)}" class="wa-link">${esc(__("Open"))}</a>`).appendTo($actions);
				$(`<button class="btn btn-xs btn-default">${esc(__("Unlink"))}</button>`)
					.on("click", () => this.unlink(doctype))
					.appendTo($actions);
			} else if (doctype !== "Opportunity") {
				$(`<button class="btn btn-xs btn-default">${esc(__("Link"))}</button>`)
					.on("click", () => this.link_dialog(doctype))
					.appendTo($actions);
			}
		});

		if (!conv.lead) {
			$(`<button class="btn btn-xs btn-default wa-create-lead">${esc(
				__("Create Lead")
			)}</button>`)
				.on("click", () => this.create_lead_dialog())
				.appendTo($crm);
		}
	}

	link_dialog(doctype) {
		const conv = this.conversation;
		const dialog = new frappe.ui.Dialog({
			title: __("Link {0}", [__(doctype)]),
			fields: [
				{ fieldtype: "Data", fieldname: "query", label: __("Search"), reqd: 1 },
				{ fieldtype: "HTML", fieldname: "hits" },
			],
			primary_action_label: __("Search"),
			primary_action: (values) => {
				api.search_crm(values.query)
					.then((hits) => {
						const rows = (hits || []).filter((h) => h.doctype === doctype);
						const $wrap = dialog.fields_dict.hits.$wrapper.empty();
						if (!rows.length) {
							$wrap.html(`<div class="wa-empty">${esc(__("No matches"))}</div>`);
							return;
						}
						rows.forEach((hit) => {
							$(`<div class="wa-hit" dir="auto">${esc(hit.label)}<span class="wa-hit-id">${esc(
								hit.name
							)}</span></div>`)
								.on("click", () => {
									api.link_crm(conv.name, doctype, hit.name)
										.then((row) => {
											dialog.hide();
											this.inbox.on_conversation_changed(row, true);
										})
										.catch((err) => this.inbox.report(err));
								})
								.appendTo($wrap);
						});
					})
					.catch((err) => this.inbox.report(err));
			},
		});
		dialog.show();
	}

	unlink(doctype) {
		api.unlink_crm(this.conversation.name, doctype)
			.then((row) => this.inbox.on_conversation_changed(row, true))
			.catch((err) => this.inbox.report(err));
	}

	create_lead_dialog() {
		const conv = this.conversation;
		const dialog = new frappe.ui.Dialog({
			title: __("Create Lead"),
			fields: [
				{
					fieldtype: "Data",
					fieldname: "lead_name",
					label: __("Lead Name"),
					reqd: 1,
					default: conv.display_name || conv.phone,
				},
				{ fieldtype: "Data", fieldname: "company_name", label: __("Company") },
				{ fieldtype: "Data", fieldname: "email_id", label: __("Email"), options: "Email" },
				{ fieldtype: "Link", fieldname: "source", label: __("Source"), options: "Lead Source" },
			],
			primary_action_label: __("Create"),
			primary_action: (values) => {
				api.create_lead_from_conversation(
					Object.assign({ conversation: conv.name }, values)
				)
					.then((res) => {
						dialog.hide();
						frappe.show_alert({
							message: __("Lead {0} created", [res.lead]),
							indicator: "green",
						});
						this.inbox.on_conversation_changed(res.conversation, true);
					})
					.catch((err) => this.inbox.report(err));
			},
		});
		dialog.show();
	}

	/** Open Opportunities for the linked party — read straight off the doctype
	 *  so no new endpoint is needed; users without Opportunity read see none. */
	render_opportunities() {
		const conv = this.conversation;
		const $opps = this.$body.find(".wa-opps");
		const party = conv.customer || conv.lead;
		$opps.html(`<div class="wa-card-title">${esc(__("Open Opportunities"))}</div>`);
		if (!party) {
			$opps.append(`<div class="wa-muted">${esc(__("No linked customer or lead"))}</div>`);
			return;
		}
		frappe.db
			.get_list("Opportunity", {
				filters: { party_name: party, status: ["not in", ["Lost", "Closed", "Converted"]] },
				fields: ["name", "title", "status", "opportunity_amount"],
				limit: 10,
				order_by: "modified desc",
			})
			.then((rows) => {
				if (!rows || !rows.length) {
					$opps.append(`<div class="wa-muted">${esc(__("None"))}</div>`);
					return;
				}
				rows.forEach((row) => {
					$opps.append(
						`<div class="wa-kv"><a class="wa-link" href="/app/opportunity/${encodeURIComponent(
							row.name
						)}" dir="auto">${esc(row.title || row.name)}</a><span>${esc(
							__(row.status)
						)}</span></div>`
					);
				});
			})
			.catch(() => {
				$opps.append(`<div class="wa-muted">${esc(__("Not permitted"))}</div>`);
			});
	}

	// ── analytics (managers) ─────────────────────────────────────────────

	render_analytics() {
		this.$body.html(`
			<div class="wa-card">
				<div class="wa-card-title">${esc(__("Inbox Analytics"))}</div>
				<div class="wa-range"></div>
			</div>
			<div class="wa-stats"></div>
		`);
		const $range = this.$body.find(".wa-range");
		this.from_control = frappe.ui.form.make_control({
			df: { fieldtype: "Date", fieldname: "from_date", label: __("From") },
			parent: $(`<div></div>`).appendTo($range),
			render_input: true,
		});
		this.to_control = frappe.ui.form.make_control({
			df: { fieldtype: "Date", fieldname: "to_date", label: __("To") },
			parent: $(`<div></div>`).appendTo($range),
			render_input: true,
		});
		this.from_control.set_value(frappe.datetime.add_days(frappe.datetime.get_today(), -29));
		this.to_control.set_value(frappe.datetime.get_today());
		$(`<button class="btn btn-xs btn-primary">${esc(__("Refresh"))}</button>`)
			.on("click", () => this.load_stats())
			.appendTo($range);
		this.load_stats();
	}

	load_stats() {
		const $stats = this.$body.find(".wa-stats");
		$stats.html(`<div class="wa-empty">${esc(__("Loading…"))}</div>`);
		api.get_inbox_stats(this.from_control.get_value(), this.to_control.get_value())
			.then((stats) => this.paint_stats($stats, stats))
			.catch((err) => $stats.html(`<div class="wa-empty">${esc(err.message)}</div>`));
	}

	paint_stats($stats, stats) {
		if (!stats) {
			$stats.empty();
			return;
		}
		const summary = [
			[__("Opened"), stats.opened],
			[__("Resolved"), stats.resolved],
			[__("Reopened"), stats.reopened],
			[__("Unassigned backlog"), stats.unassigned_backlog],
			[__("Open total"), stats.open_total],
			[__("Median first response"), duration_label(stats.median_first_response_seconds)],
			[__("P90 first response"), duration_label(stats.p90_first_response_seconds)],
		];
		const table = (title, head, rows) => `
			<div class="wa-card">
				<div class="wa-card-title">${esc(title)}</div>
				<table class="wa-table">
					<thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
					<tbody>${
						rows.length
							? rows
									.map(
										(r) =>
											`<tr>${r
												.map((c) => `<td>${esc(c)}</td>`)
												.join("")}</tr>`
									)
									.join("")
							: `<tr><td colspan="${head.length}">${esc(__("No data"))}</td></tr>`
					}</tbody>
				</table>
			</div>`;

		$stats.html(
			table(__("Summary"), [__("Metric"), __("Value")], summary) +
				table(
					__("Per agent"),
					[__("Agent"), __("Sent"), __("Resolved")],
					(stats.per_agent || []).map((a) => [a.full_name || a.user, a.sent, a.resolved])
				) +
				table(
					__("By day"),
					[__("Day"), __("Opened")],
					(stats.by_day || []).map((d) => [d.day, d.opened])
				) +
				table(
					__("By tag"),
					[__("Tag"), __("Conversations")],
					(stats.by_tag || []).map((t) => [t.tag, t.conversations])
				)
		);
	}
}
