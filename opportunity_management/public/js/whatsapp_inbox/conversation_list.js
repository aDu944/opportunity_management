/**
 * Left pane — the conversation queue.
 *
 * Owns the All / Mine / Unassigned / Expired / Resolved segmented control, the debounced
 * search box, the tag filter and the infinite scroll pager. Rows are patched
 * in place by the realtime handler in `inbox.js` (`upsert`), never re-fetched
 * wholesale, so an incoming message does not reset the reader's scroll.
 */

import * as api from "./api.js";
import { avatar_html } from "./avatar.js";
import { badge_html, channel_of } from "./channels.js";
import { relative_time } from "./time.js";
import { ad_chip_html } from "./referral.js";

// "expired" = not Resolved and the 24h customer-service window has closed
// (only a template reaches the customer) — server scope of the same name.
const SCOPES = ["all", "mine", "unassigned", "expired", "resolved"];
const SCOPE_LABELS = {
	all: "All",
	mine: "Mine",
	unassigned: "Unassigned",
	expired: "Expired",
	resolved: "Resolved",
};
const PAGE_LENGTH = 30;
const SEARCH_DEBOUNCE_MS = 300;

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

/** Lexicographic on the serializer's "YYYY-MM-DD HH:MM:SS" is a real
 *  comparison — no Date parsing needed, and a missing value never wins. */
function is_newer(candidate, current) {
	if (!candidate) {
		return false;
	}
	if (!current) {
		return true;
	}
	return String(candidate) > String(current);
}

export class ConversationList {
	constructor(opts) {
		this.$container = opts.container;
		this.inbox = opts.inbox;
		// Open on the whole queue: with a small team most threads are
		// unassigned, and an empty "Mine" tab looked like a dead inbox.
		this.scope = "all";
		this.search = "";
		this.tags = [];
		// "" = every channel the user has (channels.mount_filter sets it).
		this.channel = "";
		this.rows = [];
		this.has_more = false;
		this.loading = false;
		this.active = null;
		this.counts = { mine: 0, unassigned: 0 };
		this.make();
	}

	make() {
		this.$container.html(`
			<div class="wa-list-head">
				<div class="wa-scopes" role="tablist"></div>
				<div class="wa-list-filters">
					<input type="search" class="form-control input-xs wa-search"
						placeholder="${esc(__("Search name, phone, username or message"))}" dir="auto">
					<div class="wa-tag-filter"></div>
				</div>
			</div>
			<div class="wa-list-body"></div>
		`);

		this.$scopes = this.$container.find(".wa-scopes");
		this.$body = this.$container.find(".wa-list-body");
		this.$search = this.$container.find(".wa-search");
		this.$tag_filter = this.$container.find(".wa-tag-filter");

		SCOPES.forEach((scope) => {
			$(`<button type="button" class="wa-scope" data-scope="${scope}">
					<span class="wa-scope-label">${esc(__(SCOPE_LABELS[scope]))}</span>
					<span class="wa-scope-count"></span>
				</button>`).appendTo(this.$scopes);
		});

		this.$scopes.on("click", ".wa-scope", (e) => {
			this.set_scope($(e.currentTarget).data("scope"));
		});

		let timer = null;
		this.$search.on("input", () => {
			clearTimeout(timer);
			timer = setTimeout(() => {
				this.search = (this.$search.val() || "").trim();
				this.refresh();
			}, SEARCH_DEBOUNCE_MS);
		});

		this.$body.on("scroll", () => {
			const el = this.$body[0];
			if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
				this.load_more();
			}
		});

		this.$body.on("click", ".wa-row", (e) => {
			const name = $(e.currentTarget).data("name");
			this.inbox.open_conversation(name);
		});

		// Per-user pin / mute (set_chat_state). Pinning re-sorts server-side,
		// so the list is refetched; muting only repaints the row.
		this.$body.on("click", ".wa-row-toggle", (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			const row = this.get_row($btn.closest(".wa-row").data("name"));
			if (!row) {
				return;
			}
			const action = $btn.data("action");
			const args = { conversation: row.name };
			args[action === "pin" ? "pinned" : "muted"] = row[action === "pin" ? "pinned" : "muted"] ? 0 : 1;
			api.set_chat_state(args)
				.then((fresh) => {
					if (action === "pin") {
						this.refresh();
					} else {
						this.upsert(fresh, { keep_unread: true });
					}
				})
				.catch((err) => this.inbox.report(err));
		});

		this.render_scopes();
	}

	/** Tag chips come from `get_inbox_meta().tags`. Picking several narrows:
	 *  the server's `tags` filter is an AND, so a row must carry all of them. */
	render_tag_filter(tags) {
		this.$tag_filter.empty();
		(tags || []).forEach((tag) => {
			const $chip = $(`<button type="button" class="wa-tag-chip" data-tag="${esc(tag.tag)}">
					<span class="wa-tag-dot" style="background:${esc(tag.color || "var(--text-muted)")}"></span>
					<span>${esc(tag.tag)}</span>
				</button>`);
			$chip.on("click", () => {
				const name = tag.tag;
				if (this.tags.indexOf(name) === -1) {
					this.tags.push(name);
				} else {
					this.tags = this.tags.filter((t) => t !== name);
				}
				$chip.toggleClass("active", this.tags.indexOf(name) !== -1);
				this.refresh();
			});
			$chip.appendTo(this.$tag_filter);
		});
	}

	set_scope(scope) {
		if (!scope || this.scope === scope) {
			return;
		}
		this.scope = scope;
		this.render_scopes();
		this.refresh();
	}

	render_scopes() {
		this.$scopes.find(".wa-scope").each((_, el) => {
			const $el = $(el);
			const scope = $el.data("scope");
			$el.toggleClass("active", scope === this.scope);
			let count = "";
			if (scope === "mine" || scope === "unassigned") {
				count = this.counts[scope] ? String(this.counts[scope]) : "";
			} else if (scope === this.scope) {
				count = this.rows.length + (this.has_more ? "+" : "");
			}
			$el.find(".wa-scope-count").text(count);
		});
	}

	set_counts(counts) {
		this.counts = {
			mine: (counts && counts.mine) || 0,
			unassigned: (counts && counts.unassigned) || 0,
		};
		this.render_scopes();
	}

	refresh() {
		this.rows = [];
		this.has_more = false;
		this.$body.empty();
		return this.load({ limit_start: 0 });
	}

	load_more() {
		if (!this.has_more || this.loading) {
			return Promise.resolve();
		}
		return this.load({ limit_start: this.rows.length });
	}

	load(opts) {
		if (this.loading) {
			return Promise.resolve();
		}
		this.loading = true;
		const start = (opts && opts.limit_start) || 0;
		if (!start) {
			this.$body.html(`<div class="wa-empty">${esc(__("Loading…"))}</div>`);
		}
		return api
			.list_conversations({
				scope: this.scope,
				search: this.search || undefined,
				// `tags` is the AND filter; the server does the narrowing so the
				// pager stays honest (client-side filtering would drop rows out
				// of a page and break `has_more`).
				tags: this.tags.length ? JSON.stringify(this.tags) : undefined,
				channel: this.channel || undefined,
				limit_start: start,
				limit_page_length: PAGE_LENGTH,
			})
			.then((res) => {
				this.loading = false;
				if (!start) {
					this.$body.empty();
					this.rows = [];
				}
				const rows = (res && res.rows) || [];
				this.has_more = !!(res && res.has_more);
				rows.forEach((row) => this.append(row));
				if (!this.rows.length) {
					this.$body.html(`<div class="wa-empty">${esc(__("No conversations"))}</div>`);
				}
				this.render_scopes();
			})
			.catch((err) => {
				this.loading = false;
				this.$body.html(`<div class="wa-empty">${esc(err.message)}</div>`);
			});
	}

	append(row) {
		this.rows.push(row);
		this.$body.append(this.row_html(row));
	}

	row_html(row) {
		const arrow = row.last_message_direction === "In" ? "↙" : "↗";
		const unread = row.unread_count > 0
			? `<span class="wa-unread-pill">${esc(row.unread_count)}</span>`
			: "";
		const dots = (row.tags || [])
			.map(
				(t) =>
					`<span class="wa-tag-dot" title="${esc(t.tag)}" style="background:${esc(
						t.color || "var(--text-muted)"
					)}"></span>`
			)
			.join("");
		const toggles = `<span class="wa-row-toggles">
				<button type="button" class="wa-row-toggle ${row.pinned ? "active" : ""}" data-action="pin"
					title="${esc(row.pinned ? __("Unpin") : __("Pin"))}">📌</button>
				<button type="button" class="wa-row-toggle ${row.muted ? "active" : ""}" data-action="mute"
					title="${esc(row.muted ? __("Unmute notifications") : __("Mute notifications"))}">${
			row.muted ? "🔕" : "🔔"
		}</button>
			</span>`;
		const blocked = row.is_blocked
			? `<span class="wa-chip wa-chip-muted">${esc(__("Blocked"))}</span>`
			: "";
		const assignee = row.assigned_to
			? `<span class="wa-chip">${esc(row.assigned_to_name || row.assigned_to)}</span>`
			: `<span class="wa-chip wa-chip-muted">${esc(__("Unassigned"))}</span>`;
		return `
			<div class="wa-row ${row.name === this.active ? "active" : ""} ${
			row.unread_count > 0 ? "unread" : ""
		} ${row.pinned ? "pinned" : ""}" data-name="${esc(row.name)}">
				${avatar_html(row)}
				<div class="wa-row-main">
					<div class="wa-row-top">
						${badge_html(this.inbox.meta, row)}
						<span class="wa-row-name" dir="auto">${esc(row.display_name || row.handle || "")}</span>
						${toggles}
						<span class="wa-row-time">${esc(relative_time(row.last_message_at))}</span>
					</div>
					<div class="wa-row-sub">
						<span class="wa-row-phone" dir="ltr">${esc(row.handle || "")}</span>
						${dots}
					</div>
					<div class="wa-row-bottom">
						<span class="wa-row-preview" dir="auto">
							<span class="wa-dir">${arrow}</span> ${esc(row.last_message_preview || "")}
						</span>
						${unread}
					</div>
					<div class="wa-row-foot">${assignee} ${blocked} ${ad_chip_html(row)}</div>
				</div>
			</div>`;
	}

	/** Realtime upsert.
	 *
	 *  Only a strictly newer `last_message_at` earns the top slot. Everything
	 *  else — a delivery tick, a claim, a status change — carries the *same*
	 *  timestamp, and re-prepending on those made rows race each other to the
	 *  top and jump out from under the reader's cursor.
	 */
	upsert(row, opts) {
		if (!row || !row.name) {
			return;
		}
		const options = opts || {};
		const index = this.rows.findIndex((r) => r.name === row.name);
		if (index === -1) {
			if (!this.belongs_here(row)) {
				return;
			}
			this.prepend(row);
			return;
		}

		const existing = this.rows[index];
		if (this.scope === "expired" && (row.status === "Resolved" || row.window_open)) {
			// The customer wrote back (window reopened) or it was resolved —
			// an expired-only list must let it go rather than repaint it.
			this.rows.splice(index, 1);
			this.$body.find(`.wa-row[data-name="${row.name}"]`).remove();
			this.render_scopes();
			return;
		}
		if (options.keep_unread) {
			row = Object.assign({}, row, { unread_count: existing.unread_count });
		}
		const $existing = this.$body.find(`.wa-row[data-name="${row.name}"]`);
		if (is_newer(row.last_message_at, existing.last_message_at)) {
			this.rows.splice(index, 1);
			$existing.remove();
			this.prepend(row);
			return;
		}

		// Same message, new metadata: repaint where it stands.
		this.rows[index] = row;
		if (!$existing.length) {
			return;
		}
		const $fresh = $(this.row_html(row));
		if ($existing.hasClass("active")) {
			$fresh.addClass("active");
		}
		$existing.replaceWith($fresh);
		this.render_scopes();
	}

	/** Newest activity goes to the top — of the unpinned rows, unless the
	 *  row itself is pinned (the server sorts the caller's pins first). */
	prepend(row) {
		const after = row.pinned ? 0 : this.rows.filter((r) => r.pinned).length;
		this.rows.splice(after, 0, row);
		this.$body.find(".wa-empty").remove();
		const $rows = this.$body.children(".wa-row");
		if (after && $rows.length >= after) {
			$rows.eq(after - 1).after(this.row_html(row));
		} else {
			this.$body.prepend(this.row_html(row));
		}
		this.render_scopes();
	}

	belongs_here(row) {
		if (this.search || this.tags.length) {
			return false;
		}
		if (this.channel && channel_of(row) !== this.channel) {
			return false;
		}
		if (this.scope === "mine") {
			return row.assigned_to === this.inbox.meta.me && row.status !== "Resolved";
		}
		if (this.scope === "unassigned") {
			return !row.assigned_to && row.status !== "Resolved";
		}
		if (this.scope === "expired") {
			return row.status !== "Resolved" && !row.window_open;
		}
		if (this.scope === "resolved") {
			return row.status === "Resolved";
		}
		return row.status !== "Resolved";
	}

	patch_unread(name, unread_count) {
		const row = this.rows.find((r) => r.name === name);
		if (!row) {
			return;
		}
		row.unread_count = unread_count;
		const $row = this.$body.find(`.wa-row[data-name="${name}"]`);
		$row.toggleClass("unread", unread_count > 0);
		$row.find(".wa-unread-pill").remove();
		if (unread_count > 0) {
			$row.find(".wa-row-bottom").append(
				`<span class="wa-unread-pill">${esc(unread_count)}</span>`
			);
		}
	}

	set_active(name) {
		this.active = name;
		this.$body.find(".wa-row").removeClass("active");
		this.$body.find(`.wa-row[data-name="${name}"]`).addClass("active");
	}

	get_row(name) {
		return this.rows.find((r) => r.name === name);
	}
}
