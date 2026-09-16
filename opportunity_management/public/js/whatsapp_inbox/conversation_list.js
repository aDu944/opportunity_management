/**
 * Left pane — the conversation queue.
 *
 * Owns the Mine / Unassigned / All / Resolved segmented control, the debounced
 * search box, the tag filter and the infinite scroll pager. Rows are patched
 * in place by the realtime handler in `inbox.js` (`upsert`), never re-fetched
 * wholesale, so an incoming message does not reset the reader's scroll.
 */

import * as api from "./api.js";
import { relative_time } from "./time.js";

const SCOPES = ["mine", "unassigned", "all", "resolved"];
const SCOPE_LABELS = {
	mine: "Mine",
	unassigned: "Unassigned",
	all: "All",
	resolved: "Resolved",
};
const PAGE_LENGTH = 30;
const SEARCH_DEBOUNCE_MS = 300;

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function initials(row) {
	const source = (row.display_name || row.phone || "?").trim();
	const words = source.split(/\s+/).filter(Boolean);
	if (!words.length) {
		return "?";
	}
	if (words.length === 1) {
		return words[0].substr(0, 2).toUpperCase();
	}
	return (words[0][0] + words[1][0]).toUpperCase();
}

export class ConversationList {
	constructor(opts) {
		this.$container = opts.container;
		this.inbox = opts.inbox;
		this.scope = "mine";
		this.search = "";
		this.tags = [];
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
						placeholder="${esc(__("Search name, phone or message"))}" dir="auto">
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
		const assignee = row.assigned_to
			? `<span class="wa-chip">${esc(row.assigned_to_name || row.assigned_to)}</span>`
			: `<span class="wa-chip wa-chip-muted">${esc(__("Unassigned"))}</span>`;
		return `
			<div class="wa-row ${row.name === this.active ? "active" : ""} ${
			row.unread_count > 0 ? "unread" : ""
		}" data-name="${esc(row.name)}">
				<div class="wa-avatar">${esc(initials(row))}</div>
				<div class="wa-row-main">
					<div class="wa-row-top">
						<span class="wa-row-name" dir="auto">${esc(row.display_name || row.phone)}</span>
						<span class="wa-row-time">${esc(relative_time(row.last_message_at))}</span>
					</div>
					<div class="wa-row-sub">
						<span class="wa-row-phone">${esc(row.phone)}</span>
						${dots}
					</div>
					<div class="wa-row-bottom">
						<span class="wa-row-preview" dir="auto">
							<span class="wa-dir">${arrow}</span> ${esc(row.last_message_preview || "")}
						</span>
						${unread}
					</div>
					<div class="wa-row-foot">${assignee}</div>
				</div>
			</div>`;
	}

	/** Realtime upsert: patch in place, or move to the top if it is new/newer. */
	upsert(row, opts) {
		if (!row || !row.name) {
			return;
		}
		const options = opts || {};
		const index = this.rows.findIndex((r) => r.name === row.name);
		if (index !== -1) {
			if (options.keep_unread) {
				row = Object.assign({}, row, { unread_count: this.rows[index].unread_count });
			}
			this.rows.splice(index, 1);
			this.$body.find(`.wa-row[data-name="${row.name}"]`).remove();
		} else if (!this.belongs_here(row)) {
			return;
		}
		this.rows.unshift(row);
		this.$body.find(".wa-empty").remove();
		this.$body.prepend(this.row_html(row));
		this.render_scopes();
	}

	belongs_here(row) {
		if (this.search || this.tags.length) {
			return false;
		}
		if (this.scope === "mine") {
			return row.assigned_to === this.inbox.meta.me && row.status !== "Resolved";
		}
		if (this.scope === "unassigned") {
			return !row.assigned_to && row.status !== "Resolved";
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
