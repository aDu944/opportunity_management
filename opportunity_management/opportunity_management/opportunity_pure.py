"""
Pure helpers behind `whatsapp_api_opportunity` ("Create opportunity" from a
WhatsApp / Messenger conversation).

No `frappe` import: the bench-free tests (`tests/test_opportunity_pure.py`)
load this file straight off disk. The endpoints do the querying and call in
here for the name-shape check, party resolution, option parsing, attachment
filtering and the parse_files row mapping.
"""

import json
import mimetypes
import os

MESSENGER = "Messenger"
WHATSAPP = "WhatsApp"
# Lead Source per channel (created by patches/add_lead_abr_field).
LEAD_SOURCES = {WHATSAPP: "WhatsApp", MESSENGER: "Messenger"}
# Lead.custom_abr given to leads created from a chat.
WA_ABR = "WA"
ABR_PLACEHOLDER = "{custom_abr}"
DEFAULT_COMPANY_GROUP = "ALKHORA"
TITLE_SUFFIX = " — WhatsApp inquiry"
MESSENGER_TITLE_SUFFIX = " — Messenger inquiry"

# What parse_files can read that a chat carries: PDFs and photos.
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
PDF_EXTS = (".pdf",)
ATTACHMENT_MESSAGE_TYPES = ("document", "image")

# Opportunity Item columns filled from a parse_files row — the same set the
# ERP's own "Parse Items from File" button copies (alkhora_erp
# public/js/opportunity_parse_items.bundle.js). `_`-prefixed keys are preview
# hints, never columns.
PARSED_ITEM_FIELDS = (
    "item_name", "description", "qty", "uom", "custom_part_number",
    "custom_manufacturer", "custom_tech_desc", "custom_customer_material_no",
    "custom_est_unit_weight_kg", "custom_hs_code", "custom_duty_rate_pct", "brand",
)
# Copied even when 0 (a 0% duty is a real answer); the rest only when truthy.
KEEP_ZERO = ("custom_duty_rate_pct", "qty")
PARSE_METADATA_KEYS = (
    "title", "customer_hint", "conditions", "notes", "skipped", "low_confidence",
    "brand_matched", "brand_unmatched", "hs_unresolved", "hs_assumed", "cached",
)


# ── names ────────────────────────────────────────────────────────────────────

def is_well_formed_name(name) -> bool:
    """False when a naming part came out empty — `Inq. 512--0-26` (a party
    without an abbreviation) or `INQ-512-None-0-26`. `INQ-512-WA-0-26` and
    `ER-036-26` are fine; a tender number of 0 is a real part."""
    text = str(name or "").strip()
    if not text:
        return False
    for part in text.split("-"):
        part = part.strip()
        if not part or part in (".", "None", "null"):
            return False
    return True


def series_uses_abr(series) -> bool:
    return ABR_PLACEHOLDER in str(series or "")


# ── party ────────────────────────────────────────────────────────────────────

def resolve_party(customer=None, lead=None):
    """(party_type, party_name) the opportunity is for: the linked Customer,
    else the linked Lead, else (None, None) — a Lead must be created."""
    if customer:
        return "Customer", customer
    if lead:
        return "Lead", lead
    return None, None


def lead_source_for_channel(channel) -> str:
    return LEAD_SOURCES.get(channel) or LEAD_SOURCES[WHATSAPP]


def title_suggestion(display, channel=None) -> str:
    base = str(display or "").strip()
    suffix = MESSENGER_TITLE_SUFFIX if channel == MESSENGER else TITLE_SUFFIX
    return (base + suffix) if base else suffix.lstrip(" —")


# ── options ──────────────────────────────────────────────────────────────────

def split_options(options):
    """Select options text → list, blanks dropped, order kept, no dupes."""
    out = []
    for line in str(options or "").split("\n"):
        line = line.strip()
        if line and line not in out:
            out.append(line)
    return out


def default_series(options, field_default=None):
    """The series containing `{custom_abr}` (INQ), else the field default,
    else the first option."""
    for opt in options:
        if series_uses_abr(opt):
            return opt
    if field_default and field_default in options:
        return field_default
    return options[0] if options else None


def pick_default(options, preferred):
    if preferred in options:
        return preferred
    return options[0] if options else None


def parse_list(raw):
    """JSON array / comma string / list → deduped list of stripped strings."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                raw = json.loads(text)
            except (TypeError, ValueError):
                raw = text.strip("[]").split(",")
        else:
            raw = text.split(",")
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    out = []
    for item in raw:
        item = str(item if item is not None else "").strip().strip('"').strip()
        if item and item not in out:
            out.append(item)
    return out


# ── attachments ──────────────────────────────────────────────────────────────

def attachment_kind(filename, content_type=None):
    """"pdf" / "image" for what parse_files can read, else None."""
    name = str(filename or "").lower().split("?")[0]
    ext = os.path.splitext(name)[1]
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    if not ext and content_type == "image":
        return "image"
    return None


def mime_for(filename, kind=None) -> str:
    guess = mimetypes.guess_type(str(filename or ""))[0]
    if guess:
        return guess
    return "application/pdf" if kind == "pdf" else "image/jpeg"


def filter_attachments(rows):
    """Message rows ({name, content_type, attach, file_name?, file_size?}) →
    the ones parse_files can read, as [{message, filename, content_type,
    size}], in the given order."""
    out = []
    for row in rows or []:
        if row.get("content_type") not in ATTACHMENT_MESSAGE_TYPES:
            continue
        url = str(row.get("attach") or "").strip()
        if not url:
            continue
        filename = row.get("file_name") or os.path.basename(url.split("?")[0])
        kind = attachment_kind(filename, row.get("content_type"))
        if not kind:
            continue
        out.append({
            "message": row.get("name"),
            "filename": filename,
            "content_type": mime_for(filename, kind),
            "size": int(row.get("file_size") or 0),
        })
    return out


# ── parse_files → Opportunity Item ───────────────────────────────────────────

def map_parsed_row(row, has_field=None):
    """One parse_files row → Opportunity Item values (rate/amount 0: an
    inquiry carries no prices). `has_field(fieldname)` drops columns the
    child table does not have on this site."""
    out = {}
    for field in PARSED_ITEM_FIELDS:
        value = (row or {}).get(field)
        if value is None or value == "":
            continue
        if not value and field not in KEEP_ZERO:
            continue
        if has_field and not has_field(field):
            continue
        out[field] = value
    if not out.get("qty"):
        out["qty"] = 1
    if not out.get("uom"):
        out["uom"] = "Nos"
    out["rate"] = 0
    out["amount"] = 0
    return out


def parse_metadata(result):
    result = result or {}
    meta = {key: result.get(key) for key in PARSE_METADATA_KEYS}
    meta["items_found"] = len(result.get("items") or [])
    return meta
