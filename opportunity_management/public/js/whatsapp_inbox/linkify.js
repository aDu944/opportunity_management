/**
 * Clickable links in a bubble's text — web addresses, e-mail addresses and
 * phone numbers. Mirrors `whatsapp_linkify.dart` in the mobile app (same
 * rules, same TLD allow-list; keep the two in step).
 *
 * Conservative on purpose: a sentence that is NOT a link must never turn
 * into one. A URL is `http(s)://…`, `www.…`, or a bare domain whose last
 * label is in TLDS (`alkhora.com/catalog` yes; `ok.thanks`, `3.5kg`,
 * `v1.2.0` no). URL characters are ASCII only, so Arabic written straight
 * after a link is never swallowed. Trailing `. , ; : ! ? ) ] } " ' »` and the
 * Arabic `، ؛ ؟` are left out, except a `)` / `]` closing one opened inside
 * the URL. A phone is 9–15 digits (optional `+`, single spaces / dashes
 * between groups) not glued to other digits, letters or a decimal / date
 * separator, and not shaped like `1 250 000 000`. Only http, https, mailto
 * and tel hrefs are ever produced.
 */

export const TLDS = [
	"com", "net", "org", "io", "co", "iq", "ae", "sa", "edu", "gov", "info",
	"app", "dev", "me", "tr", "uk", "de", "cn", "in",
];

// URL body: unreserved + reserved + `%`, ASCII only.
const URL_CH = "[A-Za-z0-9\\-._~:/?#\\[\\]@!$&'()*+,;=%]";
const LABEL = "[A-Za-z0-9](?:[A-Za-z0-9\\-]{0,61}[A-Za-z0-9])?";
const TAIL = `(?::\\d{2,5})?(?:[/?#]${URL_CH}*)?`;

const LINK_SRC =
	// 1. scheme URL
	`(?<scheme>(?<![A-Za-z0-9+.\\-])https?://${URL_CH}+)` +
	// 2. e-mail
	`|(?<email>(?<![A-Za-z0-9._%+\\-])[A-Za-z0-9._%+\\-]+@(?:${LABEL}\\.)+` +
	`[A-Za-z]{2,24}(?![A-Za-z0-9\\-]|\\.[A-Za-z0-9]))` +
	// 3. www.
	`|(?<www>(?<![A-Za-z0-9+.\\-/@:_])www\\.(?:${LABEL}\\.)+[A-Za-z]{2,24}` +
	`(?![A-Za-z0-9\\-_@]|\\.[A-Za-z0-9])${TAIL})` +
	// 4. bare domain with an allow-listed TLD
	`|(?<bare>(?<![A-Za-z0-9+.\\-/@:_])(?:${LABEL}\\.)+` +
	`(?:${TLDS.join("|")})` +
	`(?![A-Za-z0-9\\-_@]|\\.[A-Za-z0-9])${TAIL})` +
	// 5. phone: grouped or a contiguous run
	`|(?<phone>(?<![A-Za-z0-9_+.,/:\\-])` +
	`(?:\\+?\\d{1,5}(?:[ \\-]\\d{2,5}){1,5}|\\+?\\d{9,15})` +
	`(?![A-Za-z0-9_]|[ \\-]?\\d|[.,/:]\\d))`;

// Lookbehind needs Safari 16.4+; on an older engine links are simply not
// detected (plain escaped text) instead of the whole bundle failing to parse.
let LINK_RE = null;
try {
	LINK_RE = new RegExp(LINK_SRC, "gi");
} catch (e) {
	LINK_RE = null;
}

const TRAILING = ".,;:!?)]}\"'»،؛؟";

function count(s, ch) {
	return s.split(ch).length - 1;
}

/** `s` minus sentence punctuation at its end; keeps a balanced `)` / `]`. */
function trim_trailing(s) {
	let end = s.length;
	while (end > 0) {
		const c = s[end - 1];
		if (!TRAILING.includes(c)) break;
		if (c === ")" || c === "]") {
			const body = s.slice(0, end);
			if (count(body, c === ")" ? "(" : "[") >= count(body, c)) break;
		}
		end--;
	}
	return s.slice(0, end);
}

/** `target` if it is a safe http(s) / mailto / tel URI, else null. */
function safe_target(target) {
	for (let i = 0; i < target.length; i++) {
		const u = target.charCodeAt(i);
		if (u < 0x21 || u > 0x7e) return null;
	}
	const scheme = target.slice(0, target.indexOf(":")).toLowerCase();
	if (scheme === "mailto" || scheme === "tel") return target;
	if (scheme !== "http" && scheme !== "https") return null;
	let host = "";
	try {
		host = new URL(target).hostname;
	} catch (e) {
		return null;
	}
	if (!host.includes(".")) return null;
	return /^[a-z]{2,24}$/.test(host.split(".").pop()) ? target : null;
}

/** `1 250 000` — a thousands-separated amount, not a phone. */
function looks_like_amount(raw) {
	if (raw.startsWith("+") || raw.startsWith("0")) return false;
	const groups = raw.split(/[ -]/);
	if (groups.length < 2) return false;
	return groups[0].length <= 3 && groups.slice(1).every((g) => g.length === 3);
}

function segment_of(groups) {
	if (groups.scheme != null) {
		const text = trim_trailing(groups.scheme);
		const colon = text.indexOf(":"); // `HTTPS://x` → `https://x`
		const target = safe_target(text.slice(0, colon).toLowerCase() + text.slice(colon));
		return target && { text, kind: "url", target };
	}
	if (groups.email != null) {
		const target = safe_target(`mailto:${groups.email}`);
		return target && { text: groups.email, kind: "email", target };
	}
	const web = groups.www != null ? groups.www : groups.bare;
	if (web != null) {
		const text = trim_trailing(web);
		const target = safe_target(`https://${text}`);
		return target && { text, kind: "url", target };
	}
	if (groups.phone != null) {
		const phone = groups.phone;
		const digits = phone.replace(/[^0-9]/g, "");
		if (digits.length < 9 || digits.length > 15 || looks_like_amount(phone)) return null;
		const target = safe_target(`tel:${phone.startsWith("+") ? "+" : ""}${digits}`);
		return target && { text: phone, kind: "phone", target };
	}
	return null;
}

/**
 * Pure: RAW text → [{text, kind, target}] with kind plain | url | email |
 * phone. Joining every `text` gives back the input exactly.
 */
export function split_links(raw) {
	const text = raw == null ? "" : String(raw);
	if (!text) return [];
	const out = [];
	const push_plain = (s) => {
		if (!s) return;
		const last = out[out.length - 1];
		if (last && last.kind === "plain") last.text += s;
		else out.push({ text: s, kind: "plain", target: "" });
	};
	let plain_from = 0;
	if (LINK_RE) {
		LINK_RE.lastIndex = 0;
		let m;
		while ((m = LINK_RE.exec(text)) !== null) {
			const seg = segment_of(m.groups);
			if (seg && seg.text) {
				push_plain(text.slice(plain_from, m.index));
				out.push(seg);
				// Punctuation trimmed off the end stays plain.
				plain_from = m.index + seg.text.length;
			}
		}
	}
	push_plain(text.slice(plain_from));
	return out;
}

/**
 * RAW text → SAFE HTML with `<a class="wa-link">` around each link.
 *
 * Why this is safe: nothing reaches the HTML unescaped. The link rules run
 * on the raw string and only DECIDE where links are — they never emit
 * markup. Every piece (plain text, link text AND href) then goes through
 * `escape`, and the href sits inside a double-quoted attribute, so a `"`
 * in a payload arrives as `&quot;` and cannot end the attribute; `<` / `>`
 * arrive as `&lt;` / `&gt;` and cannot open a tag. The scheme is checked
 * before escaping (only http / https / mailto / tel), so `javascript:` can
 * never become an href. We do not regex over the already-escaped string
 * because Frappe's `escape_html` also encodes `=` and `&`, which would mangle
 * query strings before the URL rule could see them.
 */
export function linkify_html(raw, escape) {
	const esc = escape || ((v) => frappe.utils.escape_html(v == null ? "" : String(v)));
	return split_links(raw)
		.map((seg) => {
			if (seg.kind === "plain") return esc(seg.text);
			const external =
				seg.kind === "url" ? ' target="_blank" rel="noopener noreferrer nofollow"' : "";
			return `<a class="wa-link" dir="ltr" href="${esc(seg.target)}"${external}>${esc(
				seg.text
			)}</a>`;
		})
		.join("");
}
