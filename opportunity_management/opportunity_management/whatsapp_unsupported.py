"""Readable note for inbound content Meta itself cannot deliver.

Meta sends `type: unsupported` with error 131051 ("Message type is currently
not supported") for polls, events, view-once media and messages sent by
another business account (e.g. Instagram / Meta login codes). The
customer's content never reaches the webhook, so the only useful thing to
show the agent is what to ask the customer for.
"""

EN = (
    "\u26a0\ufe0f Unsupported message \u2014 the customer sent something "
    "WhatsApp Business can't deliver: a poll, event, view-once media, or a "
    "message from another business account such as an Instagram or Meta "
    "login code. Ask them to resend it as text or a photo."
)
AR = "رسالة غير مدعومة — أرسل العميل محتوى لا يدعمه واتساب للأعمال (استطلاع أو حدث أو وسائط تُعرض مرة واحدة أو رسالة من حساب أعمال آخر مثل رمز دخول إنستغرام). اطلب منه إعادة إرسالها كنص أو صورة."


def unsupported_text(message, mtype):
    """Bilingual note for Meta's `unsupported` type (or any entry carrying
    `errors`); the bare tag for other types upstream has no branch for."""
    if mtype == "unsupported" or (message or {}).get("errors"):
        return EN + "\n" + AR
    return f"[unsupported message type: {mtype}]"
