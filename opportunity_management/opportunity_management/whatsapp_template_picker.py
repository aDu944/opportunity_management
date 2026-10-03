"""
Which approved template the re-engagement picker preselects.

Pure functions over the rows `whatsapp_api.get_templates` builds — no frappe
import at all, so `tests/test_whatsapp_template_picker.py` runs without a
bench.

A Meta template name carries one language in ERPNext (upstream's
`template_name` is unique), so the Arabic and English versions of the same
template are told apart by a suffix: `follow_up` (ar) ↔ `follow_up_en` (en);
see `whatsapp_templates._meta_name`. Stripping a trailing `_<lang>` gives the
shared base name.
"""


def lang_of(language_code) -> str:
    """Two-letter (lower-case) language of a Meta code: `en_US` → `en`."""
    return str(language_code or "").strip().replace("-", "_").split("_")[0].lower()


def _lang(row) -> str:
    return row.get("language") or lang_of(row.get("language_code"))


def base_name(row) -> str:
    """`follow_up_en` (en) → `follow_up`; `follow_up` (ar) → `follow_up`."""
    name = str(row.get("template_name") or row.get("name") or "").strip().lower()
    code = str(row.get("language_code") or "").strip().lower().replace("-", "_")
    for suffix in {"_" + code, "_" + _lang(row)}:
        if suffix != "_" and name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _alpha(row):
    return (str(row.get("template_name") or row.get("name") or "").lower(), row.get("language_code") or "")


def pick_default(rows, configured, lang) -> str:
    """Name of the row to preselect for a customer speaking `lang`.

    1. the configured default, if it is already in that language;
    2. else its counterpart in that language (same base name);
    3. else the first (alphabetical) template in that language;
    4. else the configured default;
    5. else the first template at all. "" only for an empty list.
    """
    rows = list(rows or [])
    if not rows:
        return ""
    lang = lang_of(lang)
    conf = next((r for r in rows if r.get("name") == configured), None) if configured else None
    in_lang = sorted((r for r in rows if _lang(r) == lang), key=_alpha) if lang else []

    if conf is not None and lang and _lang(conf) == lang:
        return conf["name"]
    if conf is not None:
        base = base_name(conf)
        for row in in_lang:
            if base_name(row) == base:
                return row["name"]
    if in_lang:
        return in_lang[0]["name"]
    if conf is not None:
        return conf["name"]
    return sorted(rows, key=_alpha)[0]["name"]


def order_templates(rows, configured, customer_lang=None):
    """Add `language` to every row; with a customer language, move the single
    `default: 1` to `pick_default` and sort default → that language → rest,
    alphabetical inside each group. Without one, today's order."""
    rows = list(rows or [])
    for row in rows:
        row["language"] = lang_of(row.get("language_code"))
    if not customer_lang:
        rows.sort(key=lambda t: (-t.get("default", 0),) + _alpha(t))
        return rows

    lang = lang_of(customer_lang)
    chosen = pick_default(rows, configured, lang)
    for row in rows:
        row["default"] = 1 if row["name"] == chosen else 0

    def group(row):
        if row["default"]:
            return 0
        return 1 if row["language"] == lang else 2

    rows.sort(key=lambda t: (group(t),) + _alpha(t))
    return rows
