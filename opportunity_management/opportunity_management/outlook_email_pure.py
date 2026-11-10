"""
Frappe-free logic for linking Outlook emails to Opportunities
(outlook_api.py does the database work).

* addresses: normalising, own-domain / public-domain filtering, which side of
  the email is "the customer" (sender of a received mail, recipients of a
  sent one);
* message IDs: Frappe stores them without the angle brackets
  (frappe/email/receive.py strips " <>"), Outlook returns them with;
* ranking the candidate Opportunities the lookup found, with reasons;
* the Communication values for a linked email.
"""

import re
from datetime import datetime, timezone

# Mail providers whose domain says nothing about the company behind a sender.
PUBLIC_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com",
    "gmx.com", "gmx.de", "mail.com", "yandex.com", "yandex.ru", "zoho.com",
    "mail.ru", "qq.com", "163.com", "126.com",
})

# Opportunity statuses that are finished; shown after the open ones.
CLOSED_STATUSES = frozenset({"Lost", "Closed", "Converted"})
STATUS_DISPLAY = {"Converted": "Won"}  # same wording as api._STATUS_DISPLAY_ALIASES

# Reason codes, strongest first. The panel shows REASON_LABELS.
REASON_ORDER = ("linked", "thread", "reply", "contact_email", "contact", "lead", "domain")
REASON_LABELS = {
    "linked": "This email is linked",
    "thread": "Same email thread",
    "reply": "Reply to an email sent from ERPNext",
    "contact_email": "Sender is the Opportunity's contact",
    "contact": "Sender's contact",
    "lead": "Sender's lead",
    "domain": "Same company domain",
}

MAX_CONTENT_CHARS = 2_000_000  # Communication.content cap (HTML body)
MAX_SUBJECT_CHARS = 980        # Communication.subject is Small Text; keep it sane

_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


# ── addresses ────────────────────────────────────────────────────────────────

def normalize_email(addr) -> str:
    """Lower-cased bare address, or "" when it isn't one."""
    addr = (addr or "").strip()
    m = re.search(r"<([^<>]+)>", addr)
    if m:
        addr = m.group(1)
    addr = addr.strip().strip("'\"").lower()
    return addr if _EMAIL_RE.match(addr) else ""


def email_domain(addr) -> str:
    addr = normalize_email(addr)
    return addr.rsplit("@", 1)[1] if addr else ""


def is_public_domain(domain) -> bool:
    return (domain or "").lower() in PUBLIC_DOMAINS


def direction(sender, mailbox) -> str:
    """"Sent" when the open mailbox wrote the email, else "Received"."""
    s, m = normalize_email(sender), normalize_email(mailbox)
    return "Sent" if s and s == m else "Received"


def counterparts(sender, to, cc, mailbox, own_domains=()):
    """The customer-side addresses of an email, in priority order.

    Received: the sender, then other To/Cc addresses. Sent: To, then Cc.
    Our own mailbox and anyone on our own domains (colleagues) are dropped.
    """
    me = normalize_email(mailbox)
    own = {d.lower() for d in own_domains if d}
    if me:
        own.add(email_domain(me))
    if direction(sender, mailbox) == "Sent":
        ordered = list(to or []) + list(cc or [])
    else:
        ordered = [sender] + list(to or []) + list(cc or [])
    out = []
    for addr in ordered:
        a = normalize_email(addr)
        if a and a != me and email_domain(a) not in own and a not in out:
            out.append(a)
    return out


def company_domains(addresses):
    """Distinct non-public domains of the given addresses."""
    out = []
    for a in addresses:
        d = email_domain(a)
        if d and not is_public_domain(d) and d not in out:
            out.append(d)
    return out


# ── message IDs ──────────────────────────────────────────────────────────────

def normalize_message_id(mid) -> str:
    """Frappe's stored form: surrounding whitespace and angle brackets removed."""
    return (mid or "").strip().strip(" <>").strip()


_ID_IN_HEADER = re.compile(r"<([^<>\s]+)>")
MAX_REFERENCE_IDS = 50


def reference_ids(in_reply_to="", references=""):
    """Message IDs this email replies to (In-Reply-To first, then References,
    newest reference first), bracket-free and de-duplicated. A customer's
    reply to a quotation ERPNext emailed carries that email's Message-ID,
    which ERPNext stored on the sent Communication."""
    out = []
    refs = _ID_IN_HEADER.findall(references or "")
    for mid in _ID_IN_HEADER.findall(in_reply_to or "") + list(reversed(refs)):
        mid = normalize_message_id(mid)
        if mid and mid not in out:
            out.append(mid)
    return out[:MAX_REFERENCE_IDS]


def header_value(raw_headers, name):
    """One header (unfolded) from a raw RFC 5322 header block, or ""."""
    if not raw_headers:
        return ""
    lines = raw_headers.replace("\r\n", "\n").split("\n")
    want = name.lower() + ":"
    value, collecting = [], False
    for line in lines:
        if collecting:
            if line[:1] in (" ", "\t"):
                value.append(line.strip())
                continue
            break
        if line.lower().startswith(want):
            value.append(line[len(want):].strip())
            collecting = True
    return " ".join(value)


# ── ranking ──────────────────────────────────────────────────────────────────

def merge_candidates(found):
    """`found`: iterable of (opportunity_name, reason). Returns
    {name: [reasons, strongest first]}; unknown reasons are ignored."""
    merged = {}
    for name, reason in found:
        if not name or reason not in REASON_ORDER:
            continue
        reasons = merged.setdefault(name, [])
        if reason not in reasons:
            reasons.append(reason)
    for reasons in merged.values():
        reasons.sort(key=REASON_ORDER.index)
    return merged


def _rank_key(row):
    reasons = row.get("reasons") or []
    best = REASON_ORDER.index(reasons[0]) if reasons else len(REASON_ORDER)
    closed = 1 if row.get("status") in CLOSED_STATUSES else 0
    modified = str(row.get("modified") or "")
    return (best, closed, _desc(modified))


def _desc(text):
    # Sort strings descending inside an ascending tuple sort.
    return tuple(-ord(c) for c in text)


def rank(rows, merged):
    """Attach reasons to Opportunity rows (dicts) and order them:
    strongest reason, open before closed, most recently modified first.
    Rows the user may not read never reach here (get_list filtered them)."""
    out = []
    for row in rows:
        reasons = merged.get(row.get("name"))
        if not reasons:
            continue
        r = dict(row)
        r["reasons"] = list(reasons)
        out.append(r)
    out.sort(key=_rank_key)
    return out


def present(row):
    """Panel-facing shape of an Opportunity row."""
    status = row.get("status") or ""
    reasons = row.get("reasons") or []
    return {
        "name": row.get("name"),
        "title": row.get("title") or row.get("custom_tender_title") or "",
        "party": row.get("customer_name") or row.get("party_name") or "",
        "party_type": row.get("opportunity_from") or "",
        "tender_no": row.get("custom_tender_no") or "",
        "inq_no": row.get("custom_inq_number") or "",
        "company": row.get("custom_company") or "",
        "status": STATUS_DISPLAY.get(status, status),
        "closed": status in CLOSED_STATUSES,
        "expected_closing": str(row.get("expected_closing") or "") or None,
        "reasons": reasons,
        "reason_labels": [REASON_LABELS[r] for r in reasons],
    }


# ── the email itself ─────────────────────────────────────────────────────────

def parse_iso_utc(value):
    """ISO-8601 string from Office.js (`Date.toISOString()`) -> naive UTC
    datetime, or None when missing / unreadable."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _people(rows):
    """[{email, name}] or plain strings -> "Name <addr>, ..." recipient text."""
    out = []
    for r in rows or []:
        if isinstance(r, dict):
            addr = normalize_email(r.get("email"))
            name = (r.get("name") or "").replace("<", "").replace(">", "").replace(",", " ").strip()
        else:
            addr, name = normalize_email(r), ""
        if not addr:
            continue
        out.append(f"{name} <{addr}>" if name and name.lower() != addr else addr)
    return ", ".join(out)


def addresses(rows):
    """Bare addresses from [{email, name}] / strings."""
    out = []
    for r in rows or []:
        a = normalize_email(r.get("email") if isinstance(r, dict) else r)
        if a:
            out.append(a)
    return out


def communication_values(email: dict, opportunity: str, mailbox: str) -> dict:
    """Field values for the Communication a linked email becomes.

    `email` is the panel's payload: subject, from {email,name}, to/cc lists,
    date (ISO UTC), body_html, body_text, message_id, conversation_id.
    The date stays naive UTC here; the caller converts it to system time.
    """
    sender = email.get("from") or {}
    sender_addr = normalize_email(sender.get("email") if isinstance(sender, dict) else sender)
    if not sender_addr:
        raise ValueError("the email has no sender address")
    html = email.get("body_html") or ""
    if len(html) > MAX_CONTENT_CHARS:
        text = email.get("body_text") or ""
        html = "<pre>" + _escape(text[:MAX_CONTENT_CHARS]) + "</pre>"
    subject = (email.get("subject") or "").strip()[:MAX_SUBJECT_CHARS] or "(no subject)"
    return {
        "doctype": "Communication",
        "communication_type": "Communication",
        "communication_medium": "Email",
        "sent_or_received": direction(sender_addr, mailbox),
        "subject": subject,
        "content": html,
        "sender": sender_addr,
        "sender_full_name": (sender.get("name") if isinstance(sender, dict) else "") or None,
        "recipients": _people(email.get("to")),
        "cc": _people(email.get("cc")) or None,
        "message_id": normalize_message_id(email.get("message_id")) or None,
        "reference_doctype": "Opportunity",
        "reference_name": opportunity,
        "status": "Linked",
        "seen": 1,
        "custom_outlook_conversation_id": (email.get("conversation_id") or "").strip() or None,
    }


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ── creating an Opportunity from an email ───────────────────────────────────

LEAD_SOURCE = "Email"
_ABR_RE = re.compile(r"^[A-Z0-9]{1,10}$")
_DOMAIN_NOISE = {"mail", "email", "info", "co", "com", "net", "org", "gov", "edu", "ltd", "llc"}


def valid_abr(abr) -> bool:
    """Lead/Customer abbreviation as it goes into the INQ naming series."""
    return bool(_ABR_RE.match(str(abr or "")))


def suggest_abr(text, max_len=5) -> str:
    """Upper-case letters/digits from a company / domain label: 'Oil Co
    Basra' -> 'OCB', 'basraoil' -> 'BASRA' (first `max_len` chars)."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(text or "")) if w]
    if not words:
        return ""
    if len(words) > 1:
        abr = "".join(w[0] for w in words)
    else:
        abr = words[0]
    return abr.upper()[:max_len]


def company_from_domain(domain) -> str:
    """'mail.basra-oil.com.iq' -> 'Basra Oil' (empty for public mail domains)."""
    domain = (domain or "").lower().strip()
    if not domain or is_public_domain(domain):
        return ""
    # The registrable name is the last meaningful label: sales.company.co.uk -> company.
    labels = [l for l in domain.split(".") if l and l not in _DOMAIN_NOISE and len(l) > 2]
    if not labels:
        return ""
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", labels[-1]) if w)


def new_lead_suggestion(sender_email, sender_name) -> dict:
    """Prefill for 'New lead from sender'."""
    addr = normalize_email(sender_email)
    company = company_from_domain(email_domain(addr))
    name = (sender_name or "").strip()
    if not name or normalize_email(name) == addr:
        name = addr.split("@")[0].replace(".", " ").replace("_", " ").title() if addr else ""
    return {
        "lead_name": name,
        "company_name": company,
        "email_id": addr,
        "abr": suggest_abr(company or name),
    }


def title_from_subject(subject) -> str:
    """Opportunity title from an email subject: reply/forward prefixes dropped."""
    text = str(subject or "").strip()
    while True:
        stripped = re.sub(r"^\s*(re|fw|fwd|aw|wg|tr|rv)\s*(\[\d+\])?\s*:\s*", "", text, flags=re.I)
        if stripped == text:
            break
        text = stripped
    return text[:140]


# ── item parsing (alkhora_erp.opportunity_parse.parse_files) ─────────────────

# What the parser on the agents host reads (maya._blocks_for): PDF, images,
# and text pulled from .xlsx/.xlsm/.docx. Old .xls/.doc are refused there.
PARSE_MAX_BYTES = 15 * 1024 * 1024  # parse_files' MAX_TOTAL_BYTES, all files together
_PARSE_KINDS = {
    ".pdf": ("pdf", "application/pdf"),
    ".jpg": ("image", "image/jpeg"), ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"), ".webp": ("image", "image/webp"), ".gif": ("image", "image/gif"),
    ".xlsx": ("sheet", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".xlsm": ("sheet", "application/vnd.ms-excel.sheet.macroEnabled.12"),
    ".docx": ("doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


def parse_kind(filename):
    """(kind, mime) when the parser can read the file, else None."""
    name = str(filename or "").lower().split("?")[0]
    dot = name.rfind(".")
    return _PARSE_KINDS.get(name[dot:]) if dot != -1 else None


EMAIL_TEXT_FILENAME = "email.txt"
EMAIL_TEXT_MAX_CHARS = 100_000

_DROP_BLOCKS = re.compile(r"<(style|script|head|title)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_COMMENTS = re.compile(r"<!--.*?-->", re.S)
_BREAKS = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h[1-6]|/table|/blockquote)\b[^>]*>", re.I)
_CELLS = re.compile(r"<\s*/(td|th)\s*>", re.I)
_BULLETS = re.compile(r"<\s*li\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(html_text) -> str:
    """Email HTML -> readable plain text for the parser: paragraphs and table
    rows on their own lines, cells separated by " | ", tags and styles gone."""
    import html as _html

    text = str(html_text or "")
    text = _DROP_BLOCKS.sub(" ", _COMMENTS.sub(" ", text))
    text = _CELLS.sub(" | ", text)
    text = _BULLETS.sub("\n- ", text)
    text = _BREAKS.sub("\n", text)
    text = _html.unescape(_TAGS.sub(" ", text)).replace("\xa0", " ")
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        line = re.sub(r"^(\|\s*)+|(\s*\|)+$", "", line).strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    return "\n".join(lines).strip()


def email_text(subject="", sender="", recipients="", cc="", date="", html_body="",
               limit=EMAIL_TEXT_MAX_CHARS) -> str:
    """The email as the parser reads it: a short header block, then the body."""
    head = [f"{k}: {v}" for k, v in (("From", sender), ("To", recipients), ("Cc", cc),
                                      ("Date", date), ("Subject", subject)) if v]
    body = html_to_text(html_body)
    text = "\n".join(head) + ("\n\n" if head and body else "") + body
    return text[:limit]


def merge_notes(existing, *parts):
    """Append each non-empty part to `existing` unless it is already in it
    (the desk's dedupe), separated by blank lines."""
    text = (existing or "").strip()
    for part in parts:
        part = (part or "").strip()
        if part and part not in text:
            text = f"{text}\n\n{part}" if text else part
    return text


# ── attachments ──────────────────────────────────────────────────────────────

_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_filename(name, fallback="attachment") -> str:
    name = _UNSAFE_NAME.sub("_", (name or "").strip()).strip(" .")
    return (name or fallback)[:140]
