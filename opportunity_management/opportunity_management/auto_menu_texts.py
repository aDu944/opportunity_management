"""
Fixed customer-facing strings of the WhatsApp auto menu (EN + AR).

Menus, options and their replies live in the `WhatsApp Menu` doctype (seeded
by patches/seed_auto_menu.py); only the texts the engine itself owns are here.
No frappe import: auto_menu_pure / auto_menu_form_pure use them bench-free.
"""

LANGS = ("ar", "en")

# Language step (state `lang`): one bilingual body, two reply buttons.
GREETING = (
    "شكراً لتواصلكم مع شركة الخورة، يرجى اختيار لغتك المفضلة للمتابعة:\n"
    "Thank you for contacting ALKHORA, please choose your language to proceed:"
)
LANG_BUTTONS = [{"id": "lang:ar", "title": "العربية"}, {"id": "lang:en", "title": "English"}]

# Fixed rows closing every list (ids are what the customer's tap sends back).
MAIN_MENU = {"ar": "القائمة الرئيسية", "en": "Main menu"}
# The toggle row names the OTHER language.
LANG_TOGGLE = {"ar": "🌐 English", "en": "🌐 العربية"}
MAIN_MENU_ID = "menu:root"
LANG_TOGGLE_ID = "lang:toggle"
# Reply button closing every form / request prompt (≤20 chars): a way out of
# a half-filled form without knowing the typed keyword.
MAIN_MENU_BUTTON = {"id": MAIN_MENU_ID, "title": MAIN_MENU}

# Strict-menu resend line, prepended to the prompt body.
PLEASE_CHOOSE = {
    "ar": "الرجاء اختيار أحد الخيارات من القائمة.",
    "en": "Please choose one of the options from the list.",
}
PLEASE_CHOOSE_BOTH = PLEASE_CHOOSE["ar"] + " / " + PLEASE_CHOOSE["en"]

# List button label when a menu has none of its own.
LIST_BUTTON = {"ar": "اختر", "en": "Choose"}

# Customer details form.
QUESTIONS = {
    "name": {"ar": "ما اسمك الكامل؟", "en": "What is your full name?"},
    "company": {"ar": "ما اسم الشركة أو الجهة؟", "en": "Company or organisation name?"},
    "address": {"ar": "ما عنوانك (المدينة والمنطقة)؟", "en": "Your address (city and area)?"},
    "mobile": {"ar": "رقم الموبايل؟", "en": "Mobile number?"},
    "email": {"ar": "البريد الإلكتروني؟", "en": "Email address?"},
}
HINTS = {
    "name": {
        "ar": "يرجى كتابة الاسم الكامل (الاسم واللقب).",
        "en": "Please enter your full name (first and last).",
    },
    "mobile": {
        "ar": "يرجى إدخال رقم صحيح مكوّن من 10 إلى 15 رقماً.",
        "en": "Please enter a valid number, 10 to 15 digits.",
    },
    "email": {"ar": "يرجى إدخال بريد إلكتروني صحيح.", "en": "Please enter a valid email address."},
}
# Company / address only fail on a non-text answer (photo, sticker...).
TEXT_HINT = {"ar": "يرجى كتابة الإجابة نصاً.", "en": "Please type your answer."}

FORM_BUTTONS = {
    "company": [{"id": "form:individual", "title": {"ar": "شخصي", "en": "Individual"}}],
    "mobile": [{"id": "form:same_number", "title": {"ar": "نفس هذا الرقم", "en": "Same as this number"}}],
    "email": [{"id": "form:no_email", "title": {"ar": "لا يوجد", "en": "No email"}}],
}

RETURNING = {"ar": "هل نكمل ببياناتك المسجلة لدينا؟", "en": "Continue with your saved details?"}
RETURNING_BUTTONS = [
    {"id": "form:keep", "title": {"ar": "نعم", "en": "Yes"}},
    {"id": "form:update", "title": {"ar": "تحديث", "en": "Update"}},
]
# Typed answers accepted for the two returning-customer buttons.
KEEP_WORDS = ("yes", "y", "ok", "نعم", "اي", "ايوه")
UPDATE_WORDS = ("update", "تحديث")

# Request prompt when the option has none.
DEFAULT_QUESTION = {"ar": "كيف يمكننا مساعدتك؟", "en": "How can we help you?"}

CONFIRMATION = {
    "ar": "شكراً، تم تسجيل طلبك وسيتواصل معك فريق {group} خلال ساعات العمل.",
    "en": "Thank you, your request is registered. The {group} team will contact you during business hours.",
}
# {group} when the option names no group.
NO_GROUP = {"ar": "الخورة", "en": "AL KHORA"}
# Escape hatch: after STRICT_ESCAPE_AFTER unmatched messages in one menu the
# chat goes to the escape group with the customer's words (no more lists).
STRICT_ESCAPE_AFTER = 2
ESCAPE = {
    "ar": "لم نتمكن من مطابقة رسالتك مع خيارات القائمة، لذا تم تحويل محادثتك إلى فريق {group} وسيرد عليك أحد موظفينا خلال ساعات العمل.",
    "en": "We could not match your message to the menu, so your chat has been passed to our {group} team. A colleague will reply during business hours.",
}

# `{{business_hours}}` in option replies renders from Inbox Settings.
BUSINESS_HOURS_PLACEHOLDER = "{{business_hours}}"


def pick(texts, lang) -> str:
    """`texts[lang]`, falling back to the other language, then ""."""
    if not isinstance(texts, dict):
        return str(texts or "")
    lang = "ar" if lang == "ar" else "en"
    return str(texts.get(lang) or texts.get("en" if lang == "ar" else "ar") or "")
