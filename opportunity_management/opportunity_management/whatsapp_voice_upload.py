"""
Voice notes reach Meta as uploaded media (`audio.id`), not as a link.

Since early November 2026 every voice note sent by link ends, a few seconds
later, in a `failed` status from Meta: error 131053 "Audio file uploaded
with mimetype as audio/ogg; codecs=opus, however on processing it is of type
application/octet-stream" — although the file Meta downloaded (nginx: 200,
full length, `facebookexternalhit`) is a valid mono Ogg/Opus and the very
same pipeline delivered on 31 Oct. Uploading the bytes ourselves to
`/{phone_id}/media` with an explicit `type` makes Meta validate the file at
once — the agent sees the reason in the inbox instead of a late failed
tick — and is the path Meta recommends for performance. The link remains
the fallback when the upload cannot happen (no File, network error), so a
send never gets worse than before.

Pure helpers (`media_mime`, `media_endpoint`, `upload_fields`,
`media_id_from`) are tested bench-free in `tests/test_whatsapp_voice_upload_pure.py`.
`upload_media` does the Frappe + HTTP work. The token is read with
`get_password` and only ever placed in the Authorization header: never
logged, never returned.
"""

import os
from urllib.parse import unquote

import frappe

MEDIA_MIME = {
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".amr": "audio/amr",
}
UPLOAD_TIMEOUT = 60
MAX_BYTES = 16 * 1024 * 1024  # Meta: audio up to 16 MB


# ── pure ─────────────────────────────────────────────────────────────────────

def media_mime(file_url) -> str:
    """Meta's MIME for the audio file name, "" when it is not an audio Meta
    accepts (the caller then sends the link as before)."""
    path = unquote(str(file_url or "")).split("?")[0]
    return MEDIA_MIME.get(os.path.splitext(path)[1].lower(), "")


def media_endpoint(url, version, phone_id) -> str:
    return f"{str(url or '').rstrip('/')}/{version}/{phone_id}/media"


def upload_fields(file_name, content, mime):
    """(form data, files) for `requests.post`. `type` is the bare MIME —
    Meta rejects a `codecs=` parameter on the upload."""
    if not content or len(content) > MAX_BYTES:
        raise ValueError(f"voice note is empty or over {MAX_BYTES} bytes")
    data = {"messaging_product": "whatsapp", "type": mime}
    files = {"file": (file_name or "voice" + os.path.splitext(file_name or ".ogg")[1], content, mime)}
    return data, files


def media_id_from(body) -> str:
    """The media id of Meta's upload response; raises with Meta's own
    message when the upload was refused."""
    body = body or {}
    media_id = str(body.get("id") or "").strip()
    if media_id:
        return media_id
    err = body.get("error") or {}
    details = (err.get("error_data") or {}).get("details") or err.get("message") or "no media id"
    raise ValueError(f"Meta media upload: {details}")


# ── frappe ───────────────────────────────────────────────────────────────────

def _log(title, message):
    log = getattr(frappe, "log_error", None)
    if callable(log):
        try:
            log(title=title, message=message)
        except Exception:
            pass


def upload_media(account_name, file_url) -> str:
    """Upload the File at `file_url` to the WhatsApp Account's phone number
    and return Meta's media id; "" when it could not be uploaded (logged),
    so the caller falls back to the link."""
    mime = media_mime(file_url)
    if not account_name or not mime:
        return ""
    try:
        import requests

        account = frappe.get_doc("WhatsApp Account", account_name)
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        data, files = upload_fields(file_doc.file_name or os.path.basename(file_url), file_doc.get_content(), mime)
        token = account.get_password("token")
        response = requests.post(
            media_endpoint(account.url, account.version, account.phone_id),
            headers={"Authorization": f"Bearer {token}"},
            data=data,
            files=files,
            timeout=UPLOAD_TIMEOUT,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"error": {"message": f"HTTP {response.status_code}"}}
        return media_id_from(body)
    except Exception as exc:
        _log("WhatsApp voice: media upload failed", f"file={file_url}\n{type(exc).__name__}: {exc}")
        return ""
