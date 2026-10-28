"""
The customer-details form of the WhatsApp auto menu — pure (no frappe).

State `form:<option row>:<step>`; the answers live in `menu_form_json`:
    {"name", "company", "individual", "address", "mobile", "email", "missing": [...]}

    steps_for(option)                         ["name", "company", ...]
    validate(step, inbound, phone)            (ok, value)
    question(step, lang, phone, hint=False)   the send effect for one question
    answer(form, step, inbound, phone, retries, max_retries)
                                              -> (form, next_retries, advance)
    summary(form, path)                       the System note text
    lead_fields(form)                         Lead values for insert_lead_for_conversation

`inbound` is the engine's dict: {"kind": "tap"|"text"|"media", "text", "fresh"}
where `fresh` is True when a tap answers our last prompt.
"""

import re

from opportunity_management.opportunity_management import auto_menu_texts as T

FULL_STEPS = ("name", "company", "address", "mobile", "email")
SHORT_STEPS = ("name", "company")
CONFIRM = "confirm"

INDIVIDUAL_ID = "form:individual"
SAME_NUMBER_ID = "form:same_number"
NO_EMAIL_ID = "form:no_email"
KEEP_ID = "form:keep"
UPDATE_ID = "form:update"

MAX_TEXT = 140
MIN_MOBILE, MAX_MOBILE = 10, 15
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
# Arabic-Indic and Eastern Arabic-Indic digits → ASCII.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MOBILE_JUNK = re.compile(r"[\s+\-().]")


def to_ascii_digits(text) -> str:
    return str(text or "").translate(_DIGITS)


def steps_for(option) -> tuple:
    """Name + company only for a short-form option (Follow up, Other)."""
    return SHORT_STEPS if (option or {}).get("short_form") else FULL_STEPS


def next_step_after(option, step):
    """The step after `step`, or None when the form is complete."""
    steps = steps_for(option)
    if step not in steps:
        return steps[0]
    i = steps.index(step)
    return steps[i + 1] if i + 1 < len(steps) else None


def _text(inbound) -> str:
    if (inbound or {}).get("kind") != "text":
        return ""
    return re.sub(r"\s+", " ", str(inbound.get("text") or "")).strip()


def _tap(inbound, wanted) -> bool:
    inbound = inbound or {}
    return inbound.get("kind") == "tap" and bool(inbound.get("fresh")) and (
        str(inbound.get("text") or "").strip() == wanted
    )


def clean_mobile(text) -> str:
    """Digits of a typed number, or "" when it is not 10–15 digits."""
    raw = _MOBILE_JUNK.sub("", to_ascii_digits(text))
    if raw.isdigit() and MIN_MOBILE <= len(raw) <= MAX_MOBILE:
        return raw
    return ""


def validate(step, inbound, phone=""):
    """(ok, value) for one answer. `phone` is the conversation's real number
    ("" for a hidden-number customer) — the `same_number` button needs it."""
    text = _text(inbound)
    if step == "name":
        words = [w for w in text.split(" ") if w]
        if len(words) >= 2 and len(text) <= MAX_TEXT:
            return True, text
        return False, None
    if step == "company":
        if _tap(inbound, INDIVIDUAL_ID):
            return True, ""
        return (True, text[:MAX_TEXT]) if text else (False, None)
    if step == "address":
        return (True, text[:MAX_TEXT]) if text else (False, None)
    if step == "mobile":
        if _tap(inbound, SAME_NUMBER_ID) and phone:
            return True, str(phone)
        number = clean_mobile(text)
        return (True, number) if number else (False, None)
    if step == "email":
        if _tap(inbound, NO_EMAIL_ID):
            return True, ""
        email = text.replace(" ", "")
        if EMAIL_RE.match(email) and len(email) <= MAX_TEXT:
            return True, email.lower()
        return False, None
    return False, None


def _buttons(step, lang, phone):
    rows = []
    for button in T.FORM_BUTTONS.get(step, ()):
        if button["id"] == SAME_NUMBER_ID and not phone:
            continue  # WhatsApp with a real number only
        rows.append({"id": button["id"], "title": T.pick(button["title"], lang)})
    return rows


def question(step, lang, phone="", hint=False):
    """The send effect asking `step`; with `hint` the hint line leads."""
    body = T.pick(T.QUESTIONS.get(step, {}), lang)
    if hint:
        line = T.pick(T.HINTS.get(step) or T.TEXT_HINT, lang)
        body = line + "\n" + body
    buttons = _buttons(step, lang, phone)
    if buttons:
        return {"do": "send_buttons", "body": body, "buttons": buttons, "prompt": True}
    return {"do": "send_text", "text": body, "prompt": True}


def returning_prompt(lang, please=False):
    body = T.pick(T.RETURNING, lang)
    if please:
        body = T.pick(T.PLEASE_CHOOSE, lang) + "\n" + body
    buttons = [{"id": b["id"], "title": T.pick(b["title"], lang)} for b in T.RETURNING_BUTTONS]
    return {"do": "send_buttons", "body": body, "buttons": buttons, "prompt": True}


def returning_choice(inbound):
    """"keep" | "update" | None for an answer to the returning-customer prompt."""
    if _tap(inbound, KEEP_ID):
        return "keep"
    if _tap(inbound, UPDATE_ID):
        return "update"
    text = _text(inbound).lower().rstrip(".!")
    if text in T.KEEP_WORDS:
        return "keep"
    if text in T.UPDATE_WORDS:
        return "update"
    return None


def answer(form, step, inbound, phone, retries, max_retries):
    """Apply one answer. Returns (form, retries, advance):
    advance True → move to the next step (valid, or skipped as missing);
    False → ask the same step again with its hint."""
    form = dict(form or {})
    missing = [m for m in (form.get("missing") or []) if m != step]
    ok, value = validate(step, inbound, phone)
    if ok:
        form[step] = value
        if step == "company":
            form["individual"] = value == ""
        form["missing"] = missing
        return form, 0, True
    retries = int(retries or 0) + 1
    if retries >= max(int(max_retries or 0), 1):
        form[step] = ""
        form["missing"] = missing + [step]
        return form, 0, True
    form["missing"] = missing
    return form, retries, False


_LABELS = (("name", "Name"), ("company", "Company"), ("address", "Address"),
           ("mobile", "Mobile"), ("email", "Email"))


def summary(form, path="", kept=False):
    """One System note with the answers (agent-facing, English)."""
    form = form or {}
    lines = ["Auto menu" + (" — " + path if path else "")]
    if kept:
        lines.append("Customer kept the saved details.")
    for key, label in _LABELS:
        if key not in form:
            continue
        value = form.get(key) or ""
        if key == "company" and form.get("individual"):
            value = "Individual"
        elif key == "email" and not value and key not in (form.get("missing") or []):
            value = "No email"
        lines.append("{0}: {1}".format(label, value or "—"))
    missing = form.get("missing") or []
    if missing:
        lines.append("Missing: " + ", ".join(missing))
    return "\n".join(lines)


def lead_fields(form):
    """Lead values for `insert_lead_for_conversation` (empty ones dropped)."""
    form = form or {}
    values = {
        "lead_name": form.get("name") or None,
        "company_name": None if form.get("individual") else (form.get("company") or None),
        "city": form.get("address") or None,
        "mobile_no": form.get("mobile") or None,
        "email_id": form.get("email") or None,
    }
    return {k: v for k, v in values.items() if v}
