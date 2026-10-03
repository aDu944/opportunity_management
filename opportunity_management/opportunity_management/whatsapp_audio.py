"""
Playable copies of WhatsApp voice notes.

WhatsApp voice notes are Ogg/Opus (`/files/<hash>.ogg`). iPhones
(AVFoundation) and Safari cannot play that, so every Ogg/Opus audio message
gets an AAC `.m4a` sibling, made with the system `ffmpeg`:

    ffmpeg -nostdin -y -i <in> -vn -ac 1 -c:a aac -b:a 64k -movflags +faststart <out.m4a>
    ffprobe -v error -show_entries format=duration -of csv=p=0 <out.m4a>

The copy is a second File attached to the same `WhatsApp Message`, as
private as the original (private for inbound when inbound privacy is on),
and its URL / length land in `custom_audio_url` / `custom_audio_duration`.
`media_url` keeps pointing at the original.

No ffmpeg on the server → `transcode_message_audio` and the cron sweep are
no-ops returning False/0 and clients play the original where they can.
Nothing here ever raises to its caller.

`needs_transcode` / `ffmpeg_path` touch no frappe API at import time, so the
bench-free tests load this file with a stubbed `frappe`.
"""

import os
import shutil
import subprocess
import tempfile
from urllib.parse import unquote

import frappe

MSG = "WhatsApp Message"
OGG_EXTENSIONS = (".ogg", ".oga", ".opus")
FFMPEG_TIMEOUT = 60
CRON_BATCH = 20
# A file ffmpeg rejected is not retried by the cron for this long.
FAILURE_TTL = 6 * 60 * 60

_PATHS = {}


def _which(binary):
    # Only a hit is cached: after `apt install ffmpeg` a running worker
    # picks it up on its next call instead of needing a restart.
    if not _PATHS.get(binary):
        _PATHS[binary] = shutil.which(binary) or ""
    return _PATHS[binary]


def ffmpeg_path() -> str:
    """Absolute path of ffmpeg, or "" (a found path is cached per process)."""
    return _which("ffmpeg")


def ffprobe_path() -> str:
    return _which("ffprobe")


def needs_transcode(file_url) -> bool:
    """True for Ogg/Opus names, including the `x.ogg; codecs=opus` name
    upstream builds from a mime string that carries parameters."""
    if not file_url:
        return False
    path = unquote(str(file_url)).split("?")[0].split(";")[0].strip().lower()
    return path.endswith(OGG_EXTENSIONS)


def probe_duration(path) -> int:
    """Whole seconds via ffprobe, 0 when it is missing or says nothing."""
    probe = ffprobe_path()
    if not probe:
        return 0
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            timeout=FFMPEG_TIMEOUT,
            capture_output=True,
            check=True,
        )
        return int(round(float(result.stdout.decode().strip() or 0)))
    except Exception:
        return 0


def voice_ogg_args(ffmpeg, source, out):
    """Outbound voice note: WhatsApp renders `audio.voice` only for Ogg/Opus
    mono, so the recording (AAC .m4a from the app, .webm from Desk) is
    re-encoded at speech bitrate."""
    return [
        ffmpeg, "-nostdin", "-y", "-i", source, "-vn",
        "-c:a", "libopus", "-b:a", "32k", "-ac", "1", "-ar", "48000", out,
    ]


def to_voice_ogg(source_path):
    """(ogg bytes, whole seconds) or (None, 0) without ffmpeg / on failure."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg or not source_path:
        return None, 0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "voice.ogg")
            subprocess.run(
                voice_ogg_args(ffmpeg, source_path, out),
                timeout=FFMPEG_TIMEOUT,
                capture_output=True,
                check=True,
            )
            duration = probe_duration(out)
            with open(out, "rb") as handle:
                return handle.read(), duration
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp voice: Ogg/Opus conversion failed")
        return None, 0


def _source_file(name, attach):
    """The original's File doc — resolved by record, never by building a
    path, so it works whether or not it has been privatised already."""
    base = {"attached_to_doctype": MSG, "attached_to_name": name}
    file_name = frappe.db.get_value("File", dict(base, file_url=attach), "name") or frappe.db.get_value(
        "File", {"file_url": attach}, "name"
    )
    return frappe.get_doc("File", file_name) if file_name else None


def _already_done(row) -> bool:
    url = row.get("custom_audio_url")
    return bool(url) and bool(frappe.db.exists("File", {"file_url": url}))


def transcode_message_audio(message_name):
    """RQ job (and cron worker): make the `.m4a` copy for one message.

    True when the copy exists afterwards, False otherwise.
    """
    try:
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            return False
        row = frappe.db.get_value(
            MSG,
            message_name,
            ["name", "type", "attach", "custom_conversation", "custom_audio_url"],
            as_dict=True,
        )
        if not row or not needs_transcode(row.attach):
            return False
        if _already_done(row):
            return True
        source = _source_file(row.name, row.attach)
        if not source:
            return False

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "voice.m4a")
            subprocess.run(
                [
                    ffmpeg, "-nostdin", "-y", "-i", source.get_full_path(),
                    "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k",
                    "-movflags", "+faststart", out,
                ],
                timeout=FFMPEG_TIMEOUT,
                capture_output=True,
                check=True,
            )
            duration = probe_duration(out)
            with open(out, "rb") as handle:
                content = handle.read()

        from opportunity_management.opportunity_management.whatsapp_media import privacy_on

        private = bool(source.is_private) or (row.type == "Incoming" and privacy_on())
        stem = os.path.splitext(os.path.basename(unquote(row.attach).split(";")[0]))[0] or "voice"
        copy = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": f"{stem}.m4a",
                "attached_to_doctype": MSG,
                "attached_to_name": row.name,
                "is_private": 1 if private else 0,
                "content": content,
            }
        )
        copy.save(ignore_permissions=True)
        frappe.db.set_value(
            MSG,
            row.name,
            {"custom_audio_url": copy.file_url, "custom_audio_duration": duration},
            update_modified=False,
        )
        frappe.db.commit()
        _publish(row.name)
        return True
    except Exception:
        frappe.db.rollback()
        _remember_failure(message_name)
        frappe.log_error(frappe.get_traceback(), f"WhatsApp voice transcode failed for {message_name}")
        return False


def _publish(message_name):
    try:
        doc = frappe.get_doc(MSG, message_name)
        if not doc.get("custom_conversation"):
            return
        from opportunity_management.opportunity_management.whatsapp_media import publish_message_update

        conv = frappe.get_doc("WhatsApp Conversation", doc.custom_conversation)
        publish_message_update(doc, conv)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp voice transcode: publish failed")


def _failure_key(name):
    return f"whatsapp_transcode_failed:{name}"


def _remember_failure(name):
    try:
        frappe.cache().set_value(_failure_key(name), 1, expires_in_sec=FAILURE_TTL)
    except Exception:
        pass


def _failed_recently(name) -> bool:
    try:
        return bool(frappe.cache().get_value(_failure_key(name)))
    except Exception:
        return False


def transcode_pending_voice():
    """Cron `*/5`: audio rows (in AND out) still without a playable copy,
    newest first, up to CRON_BATCH per run. No-op without ffmpeg."""
    try:
        if not ffmpeg_path():
            return 0
        if not frappe.db.has_column(MSG, "custom_audio_url"):
            return 0
        rows = frappe.get_all(
            MSG,
            filters=[
                [MSG, "content_type", "=", "audio"],
                [MSG, "attach", "is", "set"],
                [MSG, "custom_audio_url", "is", "not set"],
            ],
            fields=["name", "attach"],
            order_by="creation desc",
            limit_page_length=CRON_BATCH * 5,
        )
        done = 0
        todo = [r for r in rows if needs_transcode(r["attach"]) and not _failed_recently(r["name"])]
        for row in todo[:CRON_BATCH]:
            if transcode_message_audio(row["name"]):
                done += 1
        return done
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: transcode_pending_voice")
        return 0
