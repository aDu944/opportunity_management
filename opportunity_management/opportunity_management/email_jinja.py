"""The ONLY thing exposed to Jinja, deliberately kept tiny and import-free.

Frappe resolves every `jinja.methods` path on every single render_template() call -
rendering an address, a print format, any notification. So whatever sits behind that
path is loaded on the hot path for all templating on the site, and an ImportError or a
typo in it does not break an email, it breaks the ERP.

That is exactly what happened on 2026-10-25: this entry point lived in the same module
as the templates, the templates moved to another file, and until the cached hooks were
rebuilt every address render on the site raised AttributeError.

Hence this module: no module-level imports beyond the standard library, the real work
imported INSIDE the function, and nothing allowed to escape. A broken template module
now costs one ugly email and a logged error, not the site.
"""


def notification_email(doc, kind):
    """Build one Notification record's body. Never raises, never imports at load."""
    try:
        from opportunity_management.opportunity_management import email_templates
        return email_templates.notification_email(doc, kind)
    except Exception as exc:  # noqa: BLE001
        try:
            import frappe
            frappe.log_error(
                title="Notification email unavailable",
                message="kind=%s doc=%s: %s" % (kind, getattr(doc, "name", "?"), exc),
            )
            name = getattr(doc, "name", "") or ""
            dt = (getattr(doc, "doctype", "") or "").lower().replace(" ", "-")
            url = "%s/app/%s/%s" % (frappe.utils.get_url(), dt, name)
            return ('<p style="font-family:sans-serif;font-size:14px">'
                    '%s: <a href="%s">%s</a></p>'
                    % (str(kind).replace("_", " ").title(), url, name))
        except Exception:  # noqa: BLE001 - last resort, still must not raise
            return ""
