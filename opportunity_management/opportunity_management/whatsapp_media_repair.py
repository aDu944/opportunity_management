"""
Keep `WhatsApp Message.attach` equal to the URL of the File attached to it.

Why they drift (23 Nov 2026, 55 rows, every viewer got 403 on those images):
a customer sends the same picture twice. frappe_whatsapp saves a second
public File with the same content hash; when the inbox flips it private,
Frappe moves the file AND rewrites `file_url` on every File that shares the
hash (`update_existing_file_docs`), so the FIRST message's File now names
the second file while the message itself still says the old URL. Frappe
serves /private/files/… only when some File owns that exact URL, so the
first image is refused for everyone.

    realign_attachments(dry_run, limit)   repair every drifted row (bench execute, sweep)
    realign_siblings(file_doc)            after a privatise: the rows sharing its content

Pure part: `fixes(messages, files)` (tests/test_whatsapp_media_repair_pure.py).
"""

import frappe

MSG = "WhatsApp Message"


def fixes(messages, files) -> list:
    """[(message, new_attach, is_private)] for messages whose `attach`
    differs from the URL of the File attached to them.

    messages: [{name, attach}]; files: [{attached_to_name, file_url, is_private}]
    (only Files attached to WhatsApp Message). A message with no File, or
    with an empty attach, is left alone; the first File per message wins."""
    by_message = {}
    for f in files or ():
        name = f.get("attached_to_name")
        if name and name not in by_message and f.get("file_url"):
            by_message[name] = f
    out = []
    for m in messages or ():
        attach = (m.get("attach") or "").strip()
        f = by_message.get(m.get("name"))
        if not attach or not f:
            continue
        if attach != f["file_url"]:
            out.append((m["name"], f["file_url"], bool(f.get("is_private"))))
    return out


def _drifted(limit, names=None):
    """Rows whose attach is owned by no File, joined to their own File."""
    cond = "AND m.name IN %(names)s" if names else ""
    return frappe.db.sql(
        f"""SELECT m.name, m.attach, f.file_url, f.is_private, f.attached_to_name
            FROM `tabWhatsApp Message` m
            JOIN `tabFile` f ON f.attached_to_doctype = %(dt)s AND f.attached_to_name = m.name
            WHERE COALESCE(m.attach, '') != '' AND m.attach != f.file_url
              AND NOT EXISTS (SELECT 1 FROM `tabFile` x WHERE x.file_url = m.attach)
              {cond}
            ORDER BY m.creation DESC LIMIT %(limit)s""",
        {"dt": MSG, "names": tuple(names or ("",)), "limit": int(limit)},
        as_dict=True,
    )


def _apply(rows, dry_run):
    plan = fixes(rows, rows)
    if dry_run:
        return plan
    for name, url, private in plan:
        frappe.db.set_value(MSG, name, {"attach": url, "custom_media_private": 1 if private else 0},
                            update_modified=False)
    return plan


@frappe.whitelist()
def realign_attachments(dry_run=1, limit=200):
    """Repair every drifted message (System Manager only; `bench execute`
    runs as Administrator). Returns the (message, new_url) pairs."""
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("System Manager only", frappe.PermissionError)
    plan = _apply(_drifted(limit), int(dry_run or 0))
    if not int(dry_run or 0):
        frappe.db.commit()
    return [{"message": m, "attach": u} for m, u, _p in plan]


def realign_siblings(file_doc):
    """After privatising `file_doc`: Frappe may have re-pointed every File
    with the same content hash, so bring their messages along. Never raises."""
    try:
        if not file_doc or not file_doc.get("content_hash"):
            return 0
        names = [r[0] for r in frappe.db.sql(
            """SELECT attached_to_name FROM `tabFile`
               WHERE attached_to_doctype = %s AND content_hash = %s AND COALESCE(attached_to_name, '') != ''""",
            (MSG, file_doc.content_hash),
        )]
        names = [n for n in names if n]
        if not names:
            return 0
        return len(_apply(_drifted(len(names), names), dry_run=0))
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: attachment realign failed")
        return 0
