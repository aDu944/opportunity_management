"""
The WhatsApp auto-response menu engine — pure (no frappe import).

`auto_menu.py` gathers the conversation, the inbound message, the menu tree
and the settings as plain values, calls `next_step`, and applies the effects
it returns in order. Every rule is unit-tested bench-free
(tests/test_auto_menu_pure.py).

State (`menu_state` on the conversation):
    "" / done                  not in the menu (agents own the chat)
    lang                       greeting sent, waiting for a language
    menu:<key>                 a list is showing
    form:<option row>:<step>   collecting customer details (auto_menu_form_pure)
    request:<option row>       waiting for the request itself

Effects (dicts, key "do"): send_list, send_buttons, send_text (prompt=True
marks the message as the one a tap must answer), send_location,
send_attachment, set_state {values}, tag, note, create_lead {fields},
auto_resolve_after {hours}, handoff {group, last_handler}.

Ids the customer's taps send back: lang:ar, lang:en, opt:<row>, menu:root,
lang:toggle, form:individual, form:same_number, form:no_email, form:keep,
form:update.
"""

import datetime
import json
import re

from opportunity_management.opportunity_management import auto_menu_texts as T
from opportunity_management.opportunity_management import auto_menu_form_pure as F

LANG, MENU, FORM, REQUEST, DONE = "lang", "menu", "form", "request", "done"
ACTIVE = (LANG, MENU, FORM, REQUEST)
NOW = "__now__"  # set_state placeholder the frappe side swaps for now_datetime()

REPLY, SUBMENU, FORM_HANDOFF = "Reply", "Submenu", "Form then handoff"
LOCATION, HANDOFF, AUTO_RESOLVE = "Location", "Handoff", "Auto-resolve"
ACTIONS = (REPLY, SUBMENU, FORM_HANDOFF, LOCATION, HANDOFF, AUTO_RESOLVE)

MAX_ROWS = 8          # real options; the two fixed rows make Meta's 10
MAX_ROW_TITLE = 24    # incl. the "n. " prefix
MAX_DESCRIPTION = 72
MAX_BODY = 1024
MAX_MENU_TITLE = 24
MAX_LIST_BUTTON = 20
PATH_SEP = " › "
_DIGIT_RE = re.compile(r"^\s*([0-9])\s*[.)\-]?\s*$")


# ── small helpers ────────────────────────────────────────────────────────────

def _lang(value) -> str:
    return "en" if str(value or "").strip().lower().startswith("en") else "ar"


def _flip(lang) -> str:
    return "en" if lang == "ar" else "ar"


def parse_state(state):
    """(kind, key_or_row, step). Unknown text → ("", None, None)."""
    raw = str(state or "").strip()
    head, _, rest = raw.partition(":")
    if head == FORM:
        row, _, step = rest.rpartition(":")
        return (FORM, row, step) if row and step else ("", None, None)
    if head in (MENU, REQUEST):
        return (head, rest, None) if rest else ("", None, None)
    if head in (LANG, DONE):
        return head, None, None
    return "", None, None


def split_keywords(raw):
    return {w.strip().lower() for w in str(raw or "").split(",") if w.strip()}


def keyword(inbound, settings):
    """"menu" | "lang" | None for a typed reopen / language keyword."""
    if (inbound or {}).get("kind") != "text":
        return None
    text = re.sub(r"\s+", " ", str(inbound.get("text") or "")).strip().lower()
    if text and text in (settings or {}).get("reopen_keywords", ()):
        return "menu"
    if text and text in (settings or {}).get("language_keywords", ()):
        return "lang"
    return None


def parse_digit(text):
    match = _DIGIT_RE.match(F.to_ascii_digits(text))
    return match.group(1) if match else None


def answers_last(ctx, inbound) -> bool:
    """True when a tap replies to the last prompt we sent (row name first,
    the wamid when known)."""
    inbound, ctx = inbound or {}, ctx or {}
    row, wamid = ctx.get("last_prompt_row"), ctx.get("last_prompt_id")
    return bool((row and inbound.get("reply_to_row") == row)
                or (wamid and inbound.get("reply_to_id") == wamid))


def row_title(digit, title) -> str:
    return "{0}. {1}".format(digit, str(title or "").strip())


def _text_of(item, field, lang) -> str:
    return T.pick({"ar": item.get(field + "_ar"), "en": item.get(field + "_en")}, lang).strip()


def sorted_options(menu):
    def key(o):
        return (int(o.get("sort_order") or 0), str(o.get("digit") or ""))
    return sorted((menu or {}).get("options") or [], key=key)[:MAX_ROWS]


def stored_title(raw, option_id) -> str:
    """The title a customer saw for `option_id`, from the prompt row's stored
    `buttons` JSON; "" when not ours / not found."""
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    wanted = str(option_id or "").strip()
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, dict) and str(row.get("id") or "") == wanted and row.get("title"):
            return str(row["title"])
    return ""


# ── limits (WhatsApp Menu controller, seed tests) ────────────────────────────

def check_menu(menu):
    """Human-readable problems with one menu dict (empty list = valid)."""
    errors = []
    for lang in T.LANGS:
        if len(menu.get("title_" + lang) or "") > MAX_MENU_TITLE:
            errors.append("Title ({0}) is longer than {1} characters".format(lang, MAX_MENU_TITLE))
        if len(menu.get("body_" + lang) or "") > MAX_BODY:
            errors.append("Body ({0}) is longer than {1} characters".format(lang, MAX_BODY))
        if len(menu.get("button_" + lang) or "") > MAX_LIST_BUTTON:
            errors.append("List button ({0}) is longer than {1} characters".format(lang, MAX_LIST_BUTTON))
    options = menu.get("options") or []
    if len(options) > MAX_ROWS:
        errors.append("At most {0} options (two rows are reserved)".format(MAX_ROWS))
    digits = [str(o.get("digit") or "").strip() for o in options]
    for o, digit in zip(options, digits):
        label = "Option {0}".format(digit or "?")
        if not (len(digit) == 1 and digit.isdigit()):
            errors.append(label + ": digit must be one of 0–9")
        if digits.count(digit) > 1:
            errors.append(label + ": digit is used twice")
        if not (o.get("title_en") or o.get("title_ar")):
            errors.append(label + ": a title is required")
        for lang in T.LANGS:
            title = o.get("title_" + lang) or ""
            if title and len(row_title(digit, title)) > MAX_ROW_TITLE:
                errors.append("{0}: title ({1}) is longer than {2} characters with the \"{3}. \" prefix"
                              .format(label, lang, MAX_ROW_TITLE, digit))
            if len(o.get("description_" + lang) or "") > MAX_DESCRIPTION:
                errors.append("{0}: description ({1}) is longer than {2} characters"
                              .format(label, lang, MAX_DESCRIPTION))
        action = o.get("action") or ""
        if action not in ACTIONS:
            errors.append(label + ": unknown action")
        if action == SUBMENU and not o.get("target_menu"):
            errors.append(label + ": a Submenu option needs a target menu")
        if action == LOCATION and not (o.get("location_lat") and o.get("location_lng")):  # Float 0 = unset
            errors.append(label + ": a Location option needs latitude and longitude")
    return errors


# ── prompts ──────────────────────────────────────────────────────────────────

def greeting(please=False):
    body = (T.PLEASE_CHOOSE_BOTH + "\n\n" + T.GREETING) if please else T.GREETING
    return {"do": "send_buttons", "body": body, "buttons": [dict(b) for b in T.LANG_BUTTONS], "prompt": True}


def list_prompt(menu, lang, please=False):
    rows = [
        {
            "id": "opt:" + o["row"],
            "title": row_title(o.get("digit"), _text_of(o, "title", lang))[:MAX_ROW_TITLE],
            "description": _text_of(o, "description", lang)[:MAX_DESCRIPTION],
        }
        for o in sorted_options(menu)
    ]
    rows.append({"id": T.MAIN_MENU_ID, "title": T.MAIN_MENU[lang], "description": ""})
    rows.append({"id": T.LANG_TOGGLE_ID, "title": T.LANG_TOGGLE[lang], "description": ""})
    body = _text_of(menu, "body", lang) or _text_of(menu, "title", lang) or T.LIST_BUTTON[lang]
    if please:
        body = T.PLEASE_CHOOSE[lang] + "\n\n" + body
    button = (_text_of(menu, "button", lang) or T.LIST_BUTTON[lang])[:MAX_LIST_BUTTON]
    return {
        "do": "send_list", "menu": menu.get("key"), "body": body[:MAX_BODY], "button": button,
        "section": (_text_of(menu, "title", lang) or button)[:MAX_MENU_TITLE], "rows": rows, "prompt": True,
    }


def start_effects():
    """New / idle conversation: the bilingual greeting with two buttons."""
    return [greeting(), {"do": "set_state", "values": {
        "menu_state": LANG, "menu_path": "", "menu_form_json": None, "menu_retries": 0,
        "menu_started_at": NOW, "menu_completed_at": None, "menu_auto_resolve_at": None,
    }}]


def should_start(state, last_inbound_at, last_message_at, assigned_to, status, now, idle_hours):
    """Before this inbound: start the menu? Times are the values BEFORE the
    message was threaded (naive datetimes or None)."""
    stamps = [t for t in (last_inbound_at, last_message_at) if t]
    if not stamps:
        return True  # a new conversation
    hours = int(idle_hours or 0)
    if hours > 0 and now - max(stamps) > datetime.timedelta(hours=hours):
        return True  # idle: nobody (customer or agent) wrote for that long
    if not str(state or "").strip():
        return not (assigned_to and status != "Resolved")
    return False


def owns(state, start) -> bool:
    """Does the engine consume this inbound (no push / alert / waiting stamp)?"""
    return bool(start) or parse_state(state)[0] in ACTIVE


def takeover_values(state) -> dict:
    """An agent's own (non-auto) message, a template included, parks the menu
    for this chat whatever its state: the menu stays out of a conversation an
    agent is already holding until the idle rule (`should_start`) applies again.
    Writes nothing when the chat is already parked."""
    return {} if parse_state(state)[0] == DONE else {"menu_state": DONE}


def resolve_verdict(due, now, last_inbound_at, completed_at):
    """Auto-resolve sweep: "resolve" | "clear" (customer wrote since) | "wait"."""
    if not due or due > now:
        return "wait"
    if last_inbound_at and completed_at and last_inbound_at > completed_at:
        return "clear"
    return "resolve"


def conv_fields(conv, get):
    """ConvRow additions; `get(conv, field)` reads the row."""
    return {"menu_state": get(conv, "menu_state") or "", "menu_path": get(conv, "menu_path") or "",
            "menu_language": get(conv, "menu_language") or ""}


# ── the engine ───────────────────────────────────────────────────────────────

def next_step(ctx, inbound, tree, settings):
    """Effects for one inbound message. See the module docstring."""
    ctx, settings, tree = ctx or {}, settings or {}, tree or {}
    inbound = dict(inbound or {})
    inbound["fresh"] = answers_last(ctx, inbound)
    if ctx.get("start"):
        return start_effects()
    kind, key, step = parse_state(ctx.get("state"))
    if kind not in ACTIVE:
        return []
    flow = _Flow(ctx, inbound, tree, settings)
    if not flow.menus.get(flow.root):
        return [{"do": "set_state", "values": {"menu_state": DONE}}]  # nothing configured
    if kind == LANG:
        flow.in_lang()
    elif kind == MENU:
        flow.in_menu(key)
    elif kind == FORM:
        flow.in_form(key, step)
    else:
        flow.in_request(key)
    return flow.finish()


class _Flow:
    def __init__(self, ctx, inbound, tree, settings):
        self.ctx, self.inbound, self.settings = ctx, inbound, settings
        self.menus = tree.get("menus") or {}
        self.root = tree.get("root") or "root"
        self.lang = _lang(ctx.get("lang") or ctx.get("fallback_lang"))
        self.effects, self.values = [], {}
        self.kw = keyword(inbound, settings)
        self.tap = str(inbound.get("text") or "").strip() if inbound.get("kind") == "tap" else None

    def finish(self):
        if self.values:
            self.effects.append({"do": "set_state", "values": self.values})
        return self.effects

    def set_lang(self, lang):
        self.lang = _lang(lang)
        self.values["menu_language"] = self.lang

    # navigation
    def show(self, key, please=False, path=None):
        if key not in self.menus:
            key, path = self.root, ""
        if please and self.strikes():
            return self.escape()
        self.effects.append(list_prompt(dict(self.menus[key], key=key), self.lang, please))
        self.values["menu_state"] = MENU + ":" + key
        self.values["menu_retries"] = 0 if not please else int(self.ctx.get("retries") or 0) + 1
        if path is not None:
            self.values["menu_path"] = path

    def strikes(self) -> bool:
        """One more unmatched message: is it time to stop sending lists?"""
        limit = int(self.settings.get("escape_after") or T.STRICT_ESCAPE_AFTER)
        return int(self.ctx.get("retries") or 0) + 1 >= limit

    def escape(self):
        """Hand an unmatched conversation to the escape group with the
        customer's own words instead of yet another list."""
        group = self.settings.get("escape_group") or None
        self.done()
        self.effects.append({"do": "handoff", "group": group, "last_handler": False, "escape": True})
        text = T.ESCAPE[self.lang].format(group=group or T.NO_GROUP[self.lang])
        ooh = (self.settings.get("ooh_text") or {}).get(self.lang) or ""
        if ooh and not self.settings.get("in_hours", True):
            text += "\n\n" + ooh
        self.effects.append({"do": "send_text", "text": text})

    def show_root(self):
        self.show(self.root, path="")

    def option(self, row):
        for key, menu in self.menus.items():
            for o in menu.get("options") or []:
                if o.get("row") == row:
                    return key, o
        return None, None

    # states
    def in_lang(self):
        if self.tap in ("lang:ar", "lang:en"):
            self.set_lang(self.tap[5:])
            return self.show_root()
        if self.kw == "menu" or (self.kw is None and self.tap is None and self.inbound.get("lang")):
            self.set_lang(self.inbound.get("lang") or self.lang)
            return self.show_root()
        if self.kw != "lang" and self.strikes():
            return self.escape()
        self.effects.append(greeting(please=self.kw != "lang"))
        if self.kw != "lang":
            self.values["menu_retries"] = int(self.ctx.get("retries") or 0) + 1

    def in_menu(self, key):
        if key not in self.menus:
            key = self.root
        menu = self.menus[key]
        if self.tap == T.MAIN_MENU_ID or self.kw == "menu":
            return self.show_root()
        if self.tap == T.LANG_TOGGLE_ID or self.kw == "lang":
            self.set_lang(_flip(self.lang))
            return self.show(key)
        if self.tap in ("lang:ar", "lang:en"):
            self.set_lang(self.tap[5:])
            return self.show(key)
        chosen = None
        if self.tap and self.tap.startswith("opt:"):
            # Any tap naming an option of THIS menu counts, fresh or not: the
            # prompt row can be lost after Meta delivered it (a send that
            # failed on insert), and a tap on another menu's list misses here
            # anyway and gets the strict resend.
            chosen = next((o for o in menu.get("options") or [] if "opt:" + o.get("row", "") == self.tap), None)
        elif self.inbound.get("kind") == "text":
            digit = parse_digit(self.inbound.get("text"))
            chosen = next((o for o in sorted_options(menu) if str(o.get("digit")) == digit), None) if digit else None
        if chosen is None:
            return self.show(key, please=True)
        self.choose(key, chosen)

    def choose(self, key, o):
        here = str(self.ctx.get("path") or "") if key != self.root else ""
        path = (here + PATH_SEP if here else "") + str(o.get("digit"))
        action = o.get("action")
        if action in (REPLY, LOCATION, AUTO_RESOLVE, HANDOFF, FORM_HANDOFF):
            if action == LOCATION and o.get("location_lat") and o.get("location_lng"):
                self.effects.append({"do": "send_location", "latitude": o["location_lat"],
                                     "longitude": o.get("location_lng"), "name": o.get("location_name") or "",
                                     "address": _text_of(o, "location_address", self.lang)})
            self.reply(o)
        if o.get("tag"):
            self.effects.append({"do": "tag", "tag": o["tag"]})
        if action == REPLY:
            return self.show(key)
        if action in (SUBMENU, LOCATION):
            target = o.get("target_menu") or key
            if target not in self.menus:
                target = key
            return self.show(target, path=None if target == key else path)
        self.values["menu_path"] = path
        if action == AUTO_RESOLVE:
            self.effects.append({"do": "auto_resolve_after", "hours": int(self.settings.get("auto_resolve_hours") or 24)})
            return self.done()
        if action == HANDOFF:
            return self.handoff(o)
        if action == FORM_HANDOFF:
            self.values.update({"menu_form_json": {}, "menu_retries": 0})
            if self.ctx.get("has_crm"):
                self.values["menu_state"] = "{0}:{1}:{2}".format(FORM, o["row"], F.CONFIRM)
                return self.effects.append(F.returning_prompt(self.lang))
            return self.ask(o, F.steps_for(o)[0])
        return self.show(key, please=True)

    def reply(self, o):
        text = _text_of(o, "reply", self.lang)
        if text:
            hours = (self.settings.get("hours_label") or {}).get(self.lang) or ""
            self.effects.append({"do": "send_text", "text": text.replace(T.BUSINESS_HOURS_PLACEHOLDER, hours)})
        if o.get("attachment"):
            self.effects.append({"do": "send_attachment", "url": o["attachment"]})

    def done(self):
        self.values.update({"menu_state": DONE, "menu_completed_at": NOW, "menu_retries": 0})

    def handoff(self, o):
        self.done()
        self.effects.append({"do": "handoff", "group": o.get("assign_group") or None,
                             "last_handler": bool(o.get("last_handler"))})
        group = o.get("assign_group") or T.NO_GROUP[self.lang]
        text = T.CONFIRMATION[self.lang].format(group=group)
        ooh = (self.settings.get("ooh_text") or {}).get(self.lang) or ""
        if ooh and not self.settings.get("in_hours", True):
            text += "\n\n" + ooh
        self.effects.append({"do": "send_text", "text": text})

    # form
    def ask(self, o, step, hint=False):
        self.values["menu_state"] = "{0}:{1}:{2}".format(FORM, o["row"], step)
        self.effects.append(F.question(step, self.lang, self.ctx.get("phone") or "", hint=hint))

    def request_prompt(self, o):
        text = _text_of(o, "question", self.lang) or T.DEFAULT_QUESTION[self.lang]
        self.effects.append({"do": "send_buttons", "body": text[:MAX_BODY],
                             "buttons": [F.main_menu_button(self.lang)], "prompt": True})

    def to_main(self):
        return self.kw == "menu" or self.tap == T.MAIN_MENU_ID

    def in_form(self, row, step):
        _key, o = self.option(row)
        if o is None or self.to_main():
            return self.show_root()
        if self.kw == "lang":
            self.set_lang(_flip(self.lang))
            if step == F.CONFIRM:
                return self.effects.append(F.returning_prompt(self.lang))
            return self.ask(o, step)
        if step == F.CONFIRM:
            choice = F.returning_choice(self.inbound)
            if choice == "keep":
                return self.complete_form(o, kept=True)
            if choice == "update":
                return self.ask(o, F.steps_for(o)[0])
            return self.effects.append(F.returning_prompt(self.lang, please=True))
        form = self.ctx.get("form") or {}
        form, retries, advance = F.answer(form, step, self.inbound, self.ctx.get("phone") or "",
                                          self.ctx.get("retries"), self.settings.get("max_retries") or 3)
        self.values.update({"menu_form_json": form, "menu_retries": retries})
        if not advance:
            return self.ask(o, step, hint=True)
        following = F.next_step_after(o, step)
        if following:
            return self.ask(o, following)
        self.complete_form(o, form=form)

    def complete_form(self, o, kept=False, form=None):
        form = form if form is not None else (self.ctx.get("form") or {})
        if not kept and not self.ctx.get("has_crm"):
            self.effects.append({"do": "create_lead", "fields": F.lead_fields(form)})
        path = self.values.get("menu_path", self.ctx.get("path") or "")
        self.effects.append({"do": "note", "text": F.summary({} if kept else form, path, kept=kept)})
        self.values.update({"menu_state": REQUEST + ":" + o["row"], "menu_retries": 0})
        self.request_prompt(o)

    def in_request(self, row):
        _key, o = self.option(row)
        if o is None or self.to_main():
            return self.show_root()
        if self.kw == "lang":
            self.set_lang(_flip(self.lang))
            return self.request_prompt(o)
        self.handoff(o)
