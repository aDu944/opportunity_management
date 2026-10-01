/**
 * Composer emoji picker — a static, tabbed grid plus a "recent" row.
 *
 * Its own module so `composer.js` stays small, and static on purpose: a full
 * Unicode table (with search, skin tones, version gating) is a dependency the
 * inbox does not need — agents reach for the same few dozen emojis.
 *
 * Entries are space-separated rather than split per code point, because flags
 * and ZWJ sequences (🇮🇶, 🤦‍♂️) are several code points that render as one.
 */

const RECENT_KEY = "wa_inbox_recent_emoji";
const RECENT_MAX = 16;

const GROUPS = [
	{
		key: "smileys",
		icon: "😀",
		label: "Smileys",
		emojis:
			"😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 🙃 😉 😌 😍 🥰 😘 😗 😙 😚 😋 😛 😜 🤪 " +
			"😝 🤗 🤭 🤫 🤔 🤐 🤨 😐 😑 😶 😏 😒 🙄 😬 😮‍💨 🤥 😔 😪 🤤 😴 😷 🤒 " +
			"🤕 🤢 🥵 🥶 😵 🤯 🤠 🥳 😎 🤓 🧐 😕 😟 🙁 😮 😯 😲 😳 🥺 😦 😧 😨 " +
			"😰 😥 😢 😭 😱 😖 😣 😞 😓 😩 😫 🥱 😤 😡 😠",
	},
	{
		key: "people",
		icon: "👍",
		label: "Gestures & people",
		emojis:
			"👍 👎 👌 🤌 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ ✋ 🤚 🖐️ 🖖 👋 👏 🙌 👐 " +
			"🤲 🤝 🙏 ✍️ 💪 👀 🧠 🙋 🙋‍♂️ 🙋‍♀️ 🙇 🤦 🤦‍♂️ 🤷 🤷‍♂️ 💁 🙆 🙅 " +
			"👨‍💼 👩‍💼 👷 👨‍🔧 🧑‍💻 🚶 🏃",
	},
	{
		key: "symbols",
		icon: "❤️",
		label: "Hearts & symbols",
		emojis:
			"❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 ✅ ☑️ ✔️ ❌ " +
			"❎ ⚠️ ❗ ❓ ‼️ ⁉️ 💯 🔥 ✨ ⭐ 🌟 💫 🎉 🎊 🔔 🔕 ⏰ ⏳ ⌛ 🆗 🆕 🆓 " +
			"🔝 🔴 🟢 🟡 🔵 ⚫ ⚪ ➕ ➖ ➡️ ⬅️ ⬆️ ⬇️ 🔄",
	},
	{
		key: "objects",
		icon: "💼",
		label: "Objects & office",
		emojis:
			"💼 📁 📂 📄 📃 📑 📊 📈 📉 📋 📌 📍 📎 🖇️ ✏️ 🖊️ 📝 📅 📆 🗓️ 📞 ☎️ " +
			"📱 💻 🖥️ 🖨️ ⌨️ 📧 📨 📩 📦 📫 🏢 🏬 🏭 🏗️ 🚚 🚛 🚗 ✈️ 🔑 🔒 🔓 " +
			"🔧 🔨 🛠️ ⚙️ 🧰 💡 🔋 🧾 💰 💵 💳 🪙 🎁 ☕ 🍵",
	},
	{
		key: "flags",
		icon: "🏳️",
		label: "Flags",
		emojis:
			"🇮🇶 🇸🇦 🇦🇪 🇰🇼 🇶🇦 🇧🇭 🇴🇲 🇯🇴 🇱🇧 🇸🇾 🇪🇬 🇹🇷 🇮🇷 🇬🇧 🇺🇸 🇩🇪 " +
			"🇫🇷 🇮🇹 🇪🇸 🇨🇳 🇯🇵 🇰🇷 🇮🇳 🏳️ 🏴 🏁 🚩",
	},
];

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function read_recent() {
	try {
		const raw = JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
		return Array.isArray(raw) ? raw.filter((e) => typeof e === "string").slice(0, RECENT_MAX) : [];
	} catch (e) {
		return [];
	}
}

function write_recent(list) {
	try {
		window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
	} catch (e) {
		// Private window / blocked storage: recents just do not persist.
	}
}

export class EmojiPopover {
	/**
	 * @param {object} opts
	 * @param {jQuery} opts.$host    positioned parent the popover is appended to
	 * @param {jQuery} opts.$button  the toggle button (clicks on it are not "outside")
	 * @param {function} opts.on_pick called with the emoji string
	 */
	constructor(opts) {
		this.$host = opts.$host;
		this.$button = opts.$button;
		this.on_pick = opts.on_pick;
		this.recent = read_recent();
		this.tab = this.recent.length ? "recent" : GROUPS[0].key;
		this.$el = $(`<div class="wa-emoji-popover" hidden></div>`).appendTo(this.$host);
		this._outside = (e) => {
			const target = e.target;
			if (this.$el[0].contains(target) || this.$button[0].contains(target)) {
				return;
			}
			this.close();
		};
		this._keydown = (e) => {
			if (e.key === "Escape") {
				this.close();
			}
		};

		// mousedown, not click: keep focus (and the caret) in the textarea.
		this.$el.on("mousedown", (e) => e.preventDefault());
		this.$el.on("click", ".wa-emoji-tab", (e) => {
			this.tab = $(e.currentTarget).data("tab");
			this.render();
		});
		this.$el.on("click", ".wa-emoji-item", (e) => {
			this.pick($(e.currentTarget).attr("data-emoji"));
		});
	}

	get is_open() {
		return !this.$el.is("[hidden]");
	}

	toggle() {
		if (this.is_open) {
			this.close();
		} else {
			this.open();
		}
	}

	open() {
		this.render();
		this.$el.removeAttr("hidden");
		this.$button.addClass("active");
		document.addEventListener("mousedown", this._outside, true);
		document.addEventListener("keydown", this._keydown, true);
	}

	close() {
		if (!this.is_open) {
			return;
		}
		this.$el.attr("hidden", true);
		this.$button.removeClass("active");
		document.removeEventListener("mousedown", this._outside, true);
		document.removeEventListener("keydown", this._keydown, true);
	}

	pick(emoji) {
		if (!emoji) {
			return;
		}
		this.recent = [emoji].concat(this.recent.filter((e) => e !== emoji)).slice(0, RECENT_MAX);
		write_recent(this.recent);
		this.on_pick(emoji);
		// The popover stays open for several picks; only refresh the recent
		// tab if it is the one on screen, so the grid does not jump under the
		// pointer elsewhere.
		if (this.tab === "recent") {
			this.render();
		}
	}

	render() {
		const tabs = (this.recent.length ? [{ key: "recent", icon: "🕘", label: __("Recent") }] : [])
			.concat(GROUPS.map((g) => ({ key: g.key, icon: g.icon, label: __(g.label) })));
		if (!tabs.some((t) => t.key === this.tab)) {
			this.tab = tabs[0].key;
		}
		const group = GROUPS.find((g) => g.key === this.tab);
		const emojis = group ? group.emojis.split(/\s+/).filter(Boolean) : this.recent;

		this.$el.html(`
			<div class="wa-emoji-tabs">${tabs
				.map(
					(t) =>
						`<button type="button" class="wa-emoji-tab${t.key === this.tab ? " active" : ""}"
							data-tab="${esc(t.key)}" title="${esc(t.label)}">${esc(t.icon)}</button>`
				)
				.join("")}</div>
			<div class="wa-emoji-grid">${emojis
				.map(
					(e) =>
						`<button type="button" class="wa-emoji-item" data-emoji="${esc(e)}">${esc(e)}</button>`
				)
				.join("")}</div>
		`);
	}
}
