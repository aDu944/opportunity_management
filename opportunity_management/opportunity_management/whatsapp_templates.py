"""
`WhatsApp Templates` (frappe_whatsapp's doctype) as the team inbox sees it.

Two jobs:

1. **Hide** templates that belong to something other than the inbox. "Sync
   from Meta" imports every template on the WhatsApp account, including the
   web shop's login-code templates (category AUTHENTICATION) and Meta's
   `hello_world` sample. Those must never be listed, searched, offered in a
   Link field or sent from the inbox — and above all never *deleted* in
   ERPNext, because frappe_whatsapp's `on_trash` sends an HTTP DELETE to
   Meta and the shop would lose its OTP templates. Desk is covered by the
   `permission_query_conditions` / `has_permission` hooks registered in
   hooks.py; our own endpoints read with `frappe.get_all` (which skips both
   hooks) and call `is_hidden_template` / `usable_template` explicitly.

2. **Create** the follow-up templates the re-engagement picker needs, in one
   command (`create_followup_templates`, run by the owner via
   `bench execute`). Inserting the doc is what submits it to Meta — upstream
   `after_insert` POSTs it and stores Meta's id / status.

Import-cheap like `whatsapp_utils`: every `frappe.*` call lives inside a
function body, so `tests/test_whatsapp_templates.py` loads this file with a
stubbed `frappe` and exercises `is_hidden_template` without a bench.
"""

import frappe

DOCTYPE = "WhatsApp Templates"

# Compared upper-cased. AUTHENTICATION is what Meta calls it today; OTP is
# the older name frappe_whatsapp still offers in its Select.
HIDDEN_CATEGORIES = ("AUTHENTICATION", "OTP")
# Meta template names (`actual_name`), compared lower-cased.
HIDDEN_META_NAMES = ("hello_world",)

_TABLE = "`tabWhatsApp Templates`"

# ── visibility ───────────────────────────────────────────────────────────────


def _field(row_or_doc, key):
    if row_or_doc is None:
        return None
    if isinstance(row_or_doc, dict):
        return row_or_doc.get(key)
    getter = getattr(row_or_doc, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(row_or_doc, key, None)


def meta_name(row_or_doc) -> str:
    """Meta's template name: `actual_name`, else `template_name` normalised
    the way upstream `after_insert` derives `actual_name` from it."""
    raw = _field(row_or_doc, "actual_name") or _field(row_or_doc, "template_name") or ""
    return str(raw).strip().lower().replace(" ", "_")


def is_hidden_template(row_or_doc) -> bool:
    """True for a template the inbox must never show, offer or send.

    Works on a `frappe.get_all` row (dict) or a Document. An empty row is not
    hidden — there is nothing to identify it by.
    """
    category = str(_field(row_or_doc, "category") or "").strip().upper()
    if category in HIDDEN_CATEGORIES:
        return True
    return meta_name(row_or_doc) in HIDDEN_META_NAMES


def _sql_in_list(values):
    return ", ".join(frappe.db.escape(v) for v in values)


def template_query_conditions(user=None):
    """`permission_query_conditions` hook: hidden rows are never listed,
    counted, searched or offered in a Link field — for any user, since the
    point is that they do not exist as far as ERPNext is concerned.

    Mirrors `is_hidden_template`: category upper-cased, Meta name taken from
    `actual_name` (or `template_name` when that is empty) lower-cased with
    spaces → underscores.
    """
    name_expr = (
        f"LOWER(REPLACE(COALESCE(NULLIF({_TABLE}.`actual_name`, ''), "
        f"{_TABLE}.`template_name`, ''), ' ', '_'))"
    )
    return (
        f"(UPPER(COALESCE({_TABLE}.`category`, '')) NOT IN ({_sql_in_list(HIDDEN_CATEGORIES)})"
        f" AND {name_expr} NOT IN ({_sql_in_list(HIDDEN_META_NAMES)}))"
    )


def template_has_permission(doc, ptype=None, user=None):
    """`has_permission` hook: deny every ptype on a hidden template, so a
    direct URL does not open it and Desk cannot delete it (which would
    delete it from Meta). `None` defers to the normal role checks — Frappe
    only treats an explicit `False` as a veto."""
    if is_hidden_template(doc):
        return False
    return None


def load_template(name):
    """`{name, category, actual_name, template_name}` or None if it does not exist."""
    if not name:
        return None
    return frappe.db.get_value(
        DOCTYPE, name, ["name", "category", "actual_name", "template_name"], as_dict=True
    )


def usable_template(name) -> bool:
    """Exists and is not hidden — what the inbox may offer or send."""
    row = load_template(name)
    return bool(row) and not is_hidden_template(row)


def effective_reengage_template(settings) -> str:
    """Inbox Settings `default_reengage_template`, or "" when it points at a
    hidden or deleted template (a stale setting must not resurface one)."""
    name = str(_field(settings, "default_reengage_template") or "").strip()
    return name if name and usable_template(name) else ""


# ── follow-up templates (owner-run, not whitelisted) ─────────────────────────

FOLLOWUP_CATEGORY = "UTILITY"
FOLLOWUP_DEFAULT = "follow_up-ar"

# (template_name, sample_values, {language: body}). One Meta name per row;
# Meta accepts the same name once per language.
FOLLOWUP_TEMPLATES = (
    (
        "follow_up",
        "Ahmed",
        {
            "ar": "مرحباً {{1}}، نتابع معك بخصوص استفسارك السابق لدى شركة الخورة. هل ما زلت بحاجة إلى المساعدة؟",
            "en": "Hello {{1}}, we are following up on your earlier enquiry with AL KHORA. Do you still need assistance?",
        },
    ),
    (
        "follow_up_reply",
        "Ahmed",
        {
            "ar": "مرحباً {{1}}، لدينا رد على رسالتك لدى شركة الخورة. يرجى الرد على هذه الرسالة لمتابعة المحادثة.",
            "en": "Hello {{1}}, we have a reply to your message at AL KHORA. Please reply here to continue the conversation.",
        },
    ),
    (
        "follow_up_quotation",
        "Ahmed,SAL-QTN-2026-00012",
        {
            "ar": "مرحباً {{1}}، نتابع معك بخصوص عرض السعر رقم {{2}} من شركة الخورة. يرجى الرد على هذه الرسالة لمناقشة التفاصيل.",
            "en": "Hello {{1}}, we are following up on quotation {{2}} from AL KHORA. Please reply to this message to discuss the details.",
        },
    ),
)


def _doc_name(template_name, language):
    # Upstream autoname is `{template_name}-{language_code}` and validate
    # derives language_code from the Language name with `-` → `_`.
    return f"{template_name}-{language.replace('-', '_')}"


def _create_one(template_name, language, body, sample_values):
    doc = frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "template_name": template_name,
            "template": body,
            "language": language,
            # Upstream only derives language_code in validate — AFTER autoname
            # (`{template_name}-{language_code}`) has run, so without it every
            # row is named "follow_up-" and the second language collides.
            "language_code": language.replace("-", "_"),
            "category": FOLLOWUP_CATEGORY,
            "sample_values": sample_values,
        }
    )
    # after_insert submits to Meta and throws on Meta's rejection.
    doc.insert(ignore_permissions=True)
    return frappe.db.get_value(DOCTYPE, doc.name, "status") or doc.get("status") or ""


def _fix_misnamed():
    """Rename rows an earlier run left as "follow_up-" (see `_create_one`) to
    their proper `{template_name}-{language_code}`. A rename never calls
    Meta; the template there already has the right name and language."""
    for template_name, _samples, _bodies in FOLLOWUP_TEMPLATES:
        bad = f"{template_name}-"
        code = frappe.db.get_value(DOCTYPE, bad, "language_code")
        if not code:
            continue
        good = f"{template_name}-{code}"
        if frappe.db.exists(DOCTYPE, good):
            print(f"{bad}: left as is — {good} already exists")
            continue
        frappe.rename_doc(DOCTYPE, bad, good, force=True, show_alert=False)
        frappe.db.commit()
        print(f"{bad}: renamed to {good}")


def _maybe_set_default(dry_run, planned=()):
    from opportunity_management.opportunity_management.whatsapp_utils import (
        clear_settings_cache,
    )

    settings = frappe.get_single("WhatsApp Inbox Settings")
    current = str(settings.get("default_reengage_template") or "").strip()
    if current and usable_template(current):
        print(f"default_reengage_template: kept {current}")
        return
    # In a dry run `planned` holds what would have been created.
    if not frappe.db.exists(DOCTYPE, FOLLOWUP_DEFAULT) and FOLLOWUP_DEFAULT not in planned:
        print(f"default_reengage_template: {FOLLOWUP_DEFAULT} does not exist, left as {current or '(empty)'}")
        return
    if dry_run:
        print(f"default_reengage_template: would set {current or '(empty)'} → {FOLLOWUP_DEFAULT}")
        return
    settings.default_reengage_template = FOLLOWUP_DEFAULT
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.db.commit()
    clear_settings_cache()
    print(f"default_reengage_template: set {current or '(empty)'} → {FOLLOWUP_DEFAULT}")


def create_followup_templates(dry_run=0):
    """Insert the Arabic + English follow-up templates (submitting each to
    Meta for approval) and point the re-engagement default at `follow_up-ar`.

        bench --site erp.local execute \\
            opportunity_management.opportunity_management.whatsapp_templates.create_followup_templates
        … --kwargs "{'dry_run': 1}"     # print the plan, touch nothing

    Safe to re-run: an existing `{template_name}-{language_code}` is skipped.
    Each insert is its own transaction — upstream has already called Meta by
    the time `after_insert` returns, so a success is committed at once and a
    rejection only rolls back that one row. Never deletes anything.
    """
    dry_run = str(dry_run).strip().lower() in ("1", "true", "yes")
    if not dry_run:
        _fix_misnamed()
    results = []
    for template_name, sample_values, bodies in FOLLOWUP_TEMPLATES:
        for language, body in bodies.items():
            name = _doc_name(template_name, language)
            result = {"name": name, "template_name": template_name, "language": language}
            if frappe.db.exists(DOCTYPE, name):
                result.update(result="skipped", message="already exists")
            elif not frappe.db.exists("Language", language):
                result.update(result="failed", message=f"Language {language} does not exist")
            elif dry_run:
                result.update(result="would create", message=f"{FOLLOWUP_CATEGORY}, samples: {sample_values}")
            else:
                try:
                    status = _create_one(template_name, language, body, sample_values)
                    frappe.db.commit()
                    result.update(result="created", message=f"Meta status {status or '(none)'}")
                except Exception as exc:
                    frappe.db.rollback()
                    result.update(result="failed", message=str(exc)[:500])
            print(f"{name}: {result['result']} — {result['message']}")
            results.append(result)

    try:
        planned = {r["name"] for r in results if r["result"] == "would create"}
        _maybe_set_default(dry_run, planned)
    except Exception as exc:
        frappe.db.rollback()
        print(f"default_reengage_template: not changed — {str(exc)[:300]}")
    return results
