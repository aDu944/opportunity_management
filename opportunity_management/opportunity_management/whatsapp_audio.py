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

The source is resolved to an absolute path and checked right before ffmpeg
runs: the privatise step moves `/files/x.ogg` to `/private/files/x.ogg`, so
a path read a moment earlier can vanish. A vanished source is re-resolved
once from a reloaded File; still missing is transient (no backoff). A real
conversion failure backs off `FAILURE_BACKOFF` and gives up after
`MAX_ATTEMPTS` (counter in the cache, `ATTEMPTS_TTL`) — see `failure_action`.

`needs_transcode` / `ffmpeg_path` / `failure_action` / `cron_should_try` /
`stderr_tail` touch no frappe API, so the bench-free tests load this file
with a stubbed `frappe`.
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
# A file ffmpeg rejected is not retried by the cron for this long…
FAILURE_BACKOFF = 30 * 60
# …and is left alone after this many failures (counted for ATTEMPTS_TTL).
MAX_ATTEMPTS = 6
ATTEMPTS_TTL = 24 * 60 * 60
STDERR_TAIL = 500

# failure_action reasons / results
MISSING = "missing"
FFMPEG = "ffmpeg"
RETRY = "retry"
BACKOFF = "backoff"
GIVE_UP = "give_up"

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


def m4a_args(ffmpeg, source, out):
    """Inbound Ogg/Opus → AAC `.m4a` that iPhones and Safari can play."""
    return [
        ffmpeg, "-nostdin", "-y", "-i", source,
        "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart", out,
    ]


def stderr_tail(stderr, limit=STDERR_TAIL) -> str:
    """Last `limit` characters of ffmpeg's stderr (bytes or str), stripped."""
    if not stderr:
        return ""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    return str(stderr).strip()[-limit:]


def failure_action(attempts, reason) -> str:
    """What one failed transcode leads to.

    `attempts` counts conversion failures so far, this one included.
    A missing source (moved by the privatise step) is transient → RETRY
    with nothing recorded; a real ffmpeg failure → BACKOFF, and GIVE_UP
    once `MAX_ATTEMPTS` is reached.
    """
    if reason == MISSING:
        return RETRY
    return GIVE_UP if int(attempts or 0) >= MAX_ATTEMPTS else BACKOFF


def cron_should_try(attempts, backing_off) -> bool:
    """The cron sweep skips a message in backoff or given up on."""
    return not backing_off and int(attempts or 0) < MAX_ATTEMPTS


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

        converted = _convert(ffmpeg, source)
        if converted is None:
            # Source not on disk even after a reload: it is being moved by
            # the privatise step. Transient — the next run picks it up.
            return False
        content, duration = converted

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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # ffmpeg ran against a file that exists and failed: a real failure.
        frappe.db.rollback()
        detail = f"{exc}\n\nffmpeg stderr (last {STDERR_TAIL} chars):\n{stderr_tail(exc.stderr)}"
        _record_failure(message_name, f"{detail}\n\n{frappe.get_traceback()}")
        return False
    except Exception:
        frappe.db.rollback()
        _record_failure(message_name, frappe.get_traceback())
        return False


def _abs_path(source) -> str:
    try:
        return os.path.abspath(source.get_full_path())
    except Exception:
        return ""


def _resolve_source(source) -> str:
    """Absolute path of the File on disk, or "" when it is not there.

    On a miss the File is reloaded once — privatising moves the file and
    rewrites `file_url` / `is_private`. The rollback before the reload only
    ends this job's read snapshot so the move committed by the privatise
    step is visible; nothing has been written by this job at that point.
    """
    path = _abs_path(source)
    if path and os.path.exists(path):
        return path
    try:
        frappe.db.rollback()
        source.reload()
    except Exception:
        return ""
    path = _abs_path(source)
    return path if path and os.path.exists(path) else ""


def _run_ffmpeg(ffmpeg, path):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "voice.m4a")
        subprocess.run(
            m4a_args(ffmpeg, path, out), timeout=FFMPEG_TIMEOUT, capture_output=True, check=True
        )
        duration = probe_duration(out)
        with open(out, "rb") as handle:
            return handle.read(), duration


def _convert(ffmpeg, source):
    """(m4a bytes, seconds), or None when the source is not on disk.

    If ffmpeg fails AND its input has disappeared meanwhile (moved
    mid-run), the path is re-resolved and ffmpeg runs once more; a failure
    against a file that still exists propagates as a real one.
    """
    path = _resolve_source(source)
    if not path:
        return None
    try:
        return _run_ffmpeg(ffmpeg, path)
    except subprocess.CalledProcessError:
        if os.path.exists(path):
            raise
    path = _resolve_source(source)
    if not path:
        return None
    return _run_ffmpeg(ffmpeg, path)


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
    # Not the old `whatsapp_transcode_failed:` key: entries left under it
    # carry the former 6-hour TTL and would keep blocking the cron.
    return f"whatsapp_transcode_backoff:{name}"


def _attempts_key(name):
    return f"whatsapp_transcode_attempts:{name}"


def _attempts(name) -> int:
    try:
        return int(frappe.cache().get_value(_attempts_key(name)) or 0)
    except Exception:
        return 0


def _record_failure(name, detail):
    """Count a real conversion failure, back off, and log it — the last
    allowed one says it is the last."""
    attempts = _attempts(name) + 1
    action = failure_action(attempts, FFMPEG)
    try:
        cache = frappe.cache()
        cache.set_value(_attempts_key(name), attempts, expires_in_sec=ATTEMPTS_TTL)
        cache.set_value(_failure_key(name), 1, expires_in_sec=FAILURE_BACKOFF)
    except Exception:
        pass
    if action == GIVE_UP:
        title = f"WhatsApp voice transcode gave up on {name} after {attempts} attempts"
    else:
        title = f"WhatsApp voice transcode failed for {name} (attempt {attempts}/{MAX_ATTEMPTS})"
    frappe.log_error(detail, title)


def _cron_wants(name) -> bool:
    try:
        backing_off = bool(frappe.cache().get_value(_failure_key(name)))
    except Exception:
        backing_off = False
    return cron_should_try(_attempts(name), backing_off)


def transcode_pending_voice():
    """Cron `*/5` (via `whatsapp_jobs.process_inbound_media`, after the
    privatise sweep): audio rows (in AND out) still without a playable
    copy, newest first, up to CRON_BATCH per run, minus those backing off
    or given up on. No-op without ffmpeg."""
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
        todo = [r for r in rows if needs_transcode(r["attach"]) and _cron_wants(r["name"])]
        for row in todo[:CRON_BATCH]:
            if transcode_message_audio(row["name"]):
                done += 1
        return done
    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp inbox: transcode_pending_voice")
        return 0
