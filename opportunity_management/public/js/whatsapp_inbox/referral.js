/**
 * Ad referrals (ad_referral_contract.md): which advertisement, post or link
 * a customer came from.
 *
 * - `referral_card_html(item)` — the compact card at the top of an incoming
 *   bubble (or a System note) whose ThreadItem carries `referral`.
 * - `ad_chip_html(row)` — the small "Ad" chip on a conversation-list row.
 * - `came_from_html(conv)` — the side panel's "Came from" card (ConvRow `ad`).
 *
 * Everything is escaped; a link is only rendered for an http(s) URL and an
 * image only for a stored file path (or http(s)).
 */

import { day_label, hhmm } from "./time.js";

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

/** The URL when it is http(s), else "" (no javascript:, data:, …). */
function safe_href(value) {
	const url = String(value || "").trim();
	return /^https?:\/\/[^\s]+$/i.test(url) ? url : "";
}

/** A stored file path (/files/…, /private/files/…) or an http(s) URL. */
function safe_src(value) {
	const src = String(value || "").trim();
	if (/^\/(?!\/)[^\s]*$/.test(src)) {
		return src;
	}
	return safe_href(src);
}

export function source_label(ref) {
	const source = (ref && ref.source) || "";
	if (source === "ad") {
		return __("Ad");
	}
	if (source === "post") {
		return __("Post");
	}
	return __("Link");
}

/** Card for a ThreadItem's `referral`; "" when there is none. */
export function referral_card_html(item) {
	const ref = item && item.referral;
	if (!ref || typeof ref !== "object") {
		return "";
	}
	const href = safe_href(ref.url);
	const src = safe_src(ref.image_url);
	const inner = `
		<span class="wa-ref-label">${esc(source_label(ref))}</span>
		${src ? `<img class="wa-ref-img" src="${esc(src)}" alt="" loading="lazy">` : ""}
		${ref.headline ? `<div class="wa-ref-headline" dir="auto">${esc(ref.headline)}</div>` : ""}
		${ref.body ? `<div class="wa-ref-body" dir="auto">${esc(ref.body)}</div>` : ""}`;
	if (href) {
		return `<a class="wa-ref-card wa-ref-link" href="${esc(
			href
		)}" target="_blank" rel="noopener noreferrer" title="${esc(href)}">${inner}</a>`;
	}
	return `<div class="wa-ref-card">${inner}</div>`;
}

/** Conversation-list chip; "" without an `ad`. */
export function ad_chip_html(row) {
	const ad = row && row.ad;
	if (!ad || typeof ad !== "object") {
		return "";
	}
	const title = ad.headline ? `${source_label(ad)}: ${ad.headline}` : source_label(ad);
	return `<span class="wa-chip wa-chip-ad" title="${esc(title)}" dir="auto">${esc(
		source_label(ad)
	)}</span>`;
}

/** Side-panel "Came from" card; "" without an `ad`. */
export function came_from_html(conv) {
	const ad = conv && conv.ad;
	if (!ad || typeof ad !== "object") {
		return "";
	}
	const href = safe_href(ad.url);
	const src = safe_src(ad.image_url);
	const when = ad.at ? `${day_label(ad.at)} · ${hhmm(ad.at)}` : "";
	return `
		<div class="wa-card wa-came-from">
			<div class="wa-card-title">${esc(__("Came from"))}</div>
			<div class="wa-kv"><span>${esc(__("Source"))}</span><span>${esc(source_label(ad))}</span></div>
			${src ? `<img class="wa-ref-img" src="${esc(src)}" alt="" loading="lazy">` : ""}
			${ad.headline ? `<div class="wa-ref-headline" dir="auto">${esc(ad.headline)}</div>` : ""}
			${ad.body ? `<div class="wa-ref-body" dir="auto">${esc(ad.body)}</div>` : ""}
			${
				when
					? `<div class="wa-kv"><span>${esc(__("When"))}</span><span>${esc(when)}</span></div>`
					: ""
			}
			${
				href
					? `<a class="wa-link" href="${esc(
							href
					  )}" target="_blank" rel="noopener noreferrer">${esc(__("Open"))}</a>`
					: ""
			}
		</div>`;
}

/** True when a realtime ConvRow brings a different `ad` than the open one. */
export function ad_changed(current, incoming) {
	return JSON.stringify((current && current.ad) || null) !== JSON.stringify((incoming && incoming.ad) || null);
}
