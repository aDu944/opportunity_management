"""
FCM push notification utility for ALKHORA ESS.

Requires:
  - firebase-admin in requirements.txt  (already added)
  - Firebase service account JSON stored in Frappe site config:

    On Frappe Cloud dashboard → Sites → <site> → Config → add key:
        firebase_service_account
    Value: paste the entire service account JSON as a single-line string.

    Or via bench (self-hosted):
        bench --site <site> set-config firebase_service_account "$(cat service_account.json)"

Usage:
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_employee

    send_fcm_to_employee(employee_id, title="Hello", body="World")
    send_fcm_to_user(user_email, title="Hello", body="World")
"""

import json
import frappe

# Firebase Admin app handle — a UNIQUE name per (re)init so a self-heal
# never collides with a zombie left over from the previous init. The prior
# fixed-name approach ("alkhora-ess-fcm") got stuck when `delete_app`
# failed silently: `_app` was set to None but the FirebaseApp stayed
# registered under the name, and the next `get_app(name)` handed the same
# stale/401'd app right back to the caller. Naked-fresh init works fine,
# so we just always take that path.
_APP_BASE = "alkhora-ess-fcm"
_app = None
_app_generation = 0


def _reset_app():
    """Drop the cached handle so the next `_get_app()` builds a fresh
    FirebaseApp under a brand-new name. Best-effort delete_app on the
    old handle; failures are ignored — we don't rely on delete succeeding
    because leaked FirebaseApp objects are small and orphaning them is
    strictly safer than reusing a zombie."""
    global _app
    old = _app
    _app = None
    if old is not None:
        try:
            import firebase_admin
            firebase_admin.delete_app(old)
        except Exception:
            pass


def _get_app():
    """Return a working FirebaseApp. Creates a fresh, uniquely-named one
    every time the module cache is empty (i.e. on first call, or after a
    `_reset_app()`). No `get_app(NAME)` lookup — that path is the exact
    trap that let stale apps survive self-heal."""
    global _app, _app_generation
    if _app is not None:
        return _app
    try:
        import firebase_admin
        from firebase_admin import credentials

        raw = frappe.conf.get("firebase_service_account")
        if not raw:
            frappe.log_error(
                title="FCM Setup Error",
                message="firebase_service_account key not found in site config.\n"
                "Add it via Frappe Cloud dashboard → Sites → Config.",
            )
            return None

        account_info = json.loads(raw) if isinstance(raw, str) else raw
        cred = credentials.Certificate(account_info)

        _app_generation += 1
        name = f"{_APP_BASE}-{_app_generation}"
        _app = firebase_admin.initialize_app(cred, name=name)
        return _app
    except Exception as e:
        frappe.log_error(title="FCM Init Error", message=str(e))
        return None


def _create_notification_log(user: str, title: str, body: str) -> None:
    """Write a Notification Log entry so the employee sees it in-app."""
    try:
        doc = frappe.get_doc({
            "doctype": "Notification Log",
            "subject": title,
            "email_content": body,
            "for_user": user,
            "type": "Alert",
            "read": 0,
        })
        # Mark so on_notification_log_insert doesn't push a second FCM
        # for a row we just created as a side-effect of sending one.
        doc.flags.from_fcm_send = True
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="FCM Notification Log Error", message=str(e))


def _build_message(token: str, title: str, body: str, data: dict = None):
    from firebase_admin import messaging
    return messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={str(k): str(v) for k, v in (data or {}).items()},
        token=token,
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="alkhora_ess_main",
                sound="bell",
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="bell.caf", badge=1)
            )
        ),
    )


def _build_naked_app():
    """Load creds from site config and build a fresh, uniquely-named
    FirebaseApp with zero module-cache reliance. This is the ONLY init
    path proven to work reliably in production — the module-level `_app`
    cache and self-heal loop was producing "fresh" apps that still 401'd
    under some worker conditions we couldn't reproduce with bench execute.
    Isolated ephemeral apps sidestep every one of those failure modes."""
    import firebase_admin
    from firebase_admin import credentials

    raw = frappe.conf.get("firebase_service_account")
    if not raw:
        frappe.log_error(
            title="FCM Setup Error",
            message="firebase_service_account key not found in site config.",
        )
        return None
    account_info = json.loads(raw) if isinstance(raw, str) else raw
    cred = credentials.Certificate(account_info)

    global _app_generation
    _app_generation += 1
    # Include pid to guarantee no worker-vs-worker name overlap even under
    # forked concurrency.
    import os
    name = f"{_APP_BASE}-p{os.getpid()}-g{_app_generation}"
    return firebase_admin.initialize_app(cred, name=name)


def _unread_badge_for_token(token: str) -> int:
    """Best-effort: return the number of unread Notification Logs for the
    user this token belongs to. Used as the iOS badge value so the badge
    always matches what the user sees in the in-app notifications list.

    Returns 1 as a safe fallback if the lookup fails — never returns 0 for
    a fresh push because that would tell iOS to clear the badge."""
    try:
        user = frappe.db.sql(
            """
            SELECT user_id FROM `tabEmployee`
            WHERE custom_fcm_token = %s
            LIMIT 1
            """,
            (token,),
        )
        email = user[0][0] if user and user[0][0] else _device_user(token)
        if not email:
            return 1
        count = frappe.db.count(
            "Notification Log",
            {"for_user": email, "read": 0},
        )
        # We're about to add one more Notification Log (via _create_notification_log)
        # so include it in the badge preemptively.
        return int(count) + 1
    except Exception:
        return 1


_DEVICE_DT = "ESS Push Device"


def _device_user(token: str):
    """User owning `token` as an `ESS Push Device` row, or None."""
    try:
        return frappe.db.get_value(_DEVICE_DT, {"token": token}, "user")
    except Exception:
        return None


def _describe_token(token: str) -> str:
    """Identify a token's owner for error logs, without logging the token.

    A raw FCM token is a device credential, so only a short prefix goes in
    the log — enough to tell two failing devices apart, useless on its own.
    """
    prefix = (token or "")[:12]
    try:
        row = frappe.db.sql(
            """
            SELECT name, employee_name, custom_app_platform, custom_app_version
            FROM `tabEmployee`
            WHERE custom_fcm_token = %s
            LIMIT 1
            """,
            (token,),
        )
        if row:
            emp, emp_name, plat, ver = row[0]
            return f"{emp} ({emp_name}) {plat or '?'} {ver or '?'} token={prefix}…"
        dev = frappe.db.get_value(_DEVICE_DT, {"token": token}, ["name", "user", "platform", "label"])
        if dev:
            name, user, plat, label = dev
            return f"{_DEVICE_DT} {name} {user} {plat or '?'} {label or ''} token={prefix}…"
    except Exception:
        pass
    return f"<no Employee holds this token> token={prefix}…"


# Private per-push options a caller may put in `data`. `send_fcm` pops them
# (so they never reach the client as data) and applies them to the message:
#   _apns_category   → apns aps.category      (WhatsApp Reply action, WA_REPLY)
#   _sound_ios       → apns aps.sound         (e.g. "wa_message.caf")
#   _sound_android   → android notification.sound       (e.g. "wa_message")
#   _android_channel → android notification.channel_id  (e.g. "alkhora_ess_whatsapp")
# Without any of them the message is exactly the default one.
_PRIVATE_KEYS = ("_apns_category", "_sound_ios", "_sound_android", "_android_channel")


def split_private_keys(data):
    """Return `(data_copy_without_private_keys, private_keys)`. The caller's
    dict is never mutated (one dict is reused across a fan-out)."""
    data = dict(data or {})
    private = {k: data.pop(k) for k in _PRIVATE_KEYS if k in data}
    return data, private


def apply_private_keys(message: dict, private: dict) -> dict:
    """Apply popped private keys to an FCM v1 `message` dict in place (and
    return it). Empty / missing values leave the defaults untouched."""
    aps = message["apns"]["payload"]["aps"]
    android = message["android"]["notification"]
    if private.get("_sound_ios"):
        aps["sound"] = str(private["_sound_ios"])
    if private.get("_apns_category"):
        aps["category"] = str(private["_apns_category"])
    if private.get("_sound_android"):
        android["sound"] = str(private["_sound_android"])
    if private.get("_android_channel"):
        android["channel_id"] = str(private["_android_channel"])
    return message


def send_fcm(token: str, title: str, body: str, data: dict = None, platform: str = None) -> bool:
    """Send an FCM notification to a single device token. Returns True on success.
    `platform="web"` adds a `webpush` block (see `fcm_webpush`)."""
    return _send_fcm_result(token, title, body, data, platform)[0]


def _send_fcm_result(token, title, body, data=None, platform=None):
    """`send_fcm` returning `(ok, bad_token, error_text)`; `bad_token` is True
    only when FCM said the token itself is dead (UNREGISTERED / invalid).

    Uses google-auth directly to obtain an OAuth token for the explicit
    `firebase.messaging` scope, then POSTs to the FCM v1 endpoint. The
    firebase_admin.messaging.send path fetched a token successfully but the
    token wasn't accepted by FCM in production workers — the wider default
    scope set firebase_admin requests may miss the specific scope FCM v1
    requires under some runtime combinations. Direct call sidesteps that.
    """
    raw = frappe.conf.get("firebase_service_account")
    if not raw:
        frappe.log_error(
            title="FCM Setup Error",
            message="firebase_service_account key not found in site config.",
        )
        return False, False, "no firebase_service_account"
    account_info = json.loads(raw) if isinstance(raw, str) else raw
    project_id = account_info.get("project_id")
    if not project_id:
        frappe.log_error(
            title="FCM Setup Error",
            message="project_id missing from firebase_service_account",
        )
        return False, False, "no project_id"

    badge = _unread_badge_for_token(token)
    # Optional private keys (see `_PRIVATE_KEYS`) — lifted into the
    # android/apns blocks below, never sent as data.
    data, private = split_private_keys(data)
    payload = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {str(k): str(v) for k, v in (data or {}).items()},
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": "alkhora_ess_main",
                    "sound": "bell",
                    # Match iOS: keep the visible count aligned with the
                    # user's unread in-app notifications.
                    "notification_count": badge,
                },
            },
            "apns": {
                "payload": {
                    # `badge` here SETS iOS badge to that exact number — no
                    # accumulation. Using the user's unread notification
                    # count makes the badge a meaningful indicator instead
                    # of a stale value from a random earlier push.
                    "aps": {"sound": "bell.caf", "badge": badge},
                },
            },
        }
    }
    apply_private_keys(payload["message"], private)
    if platform == "web":
        from opportunity_management.opportunity_management.fcm_webpush import build_webpush

        payload["message"]["webpush"] = build_webpush(title, body, data, _site_url())

    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        # Explicit scope — this is the exact scope FCM v1 checks against.
        # firebase_admin's default scope bundle apparently doesn't always
        # yield a token FCM v1 accepts in every runtime.
        credentials = service_account.Credentials.from_service_account_info(
            account_info,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        session = AuthorizedSession(credentials)
        url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
        resp = session.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            return True, False, None
        # Frappe's log_error title is capped at 140 chars — keep title constant
        # and put the identifying detail in the body. Without the recipient
        # here a recurring UNREGISTERED 404 is unattributable: you can see a
        # dead token is being retried but not whose, which turns a log read
        # into a live token-validation exercise. Never log the token itself.
        frappe.log_error(
            title="FCM Send Error",
            message=(
                f"status={resp.status_code}\n"
                f"recipient={_describe_token(token)}\n"
                f"body={resp.text[:600]}"
            ),
        )
        from opportunity_management.opportunity_management.fcm_webpush import is_bad_token_response

        bad = is_bad_token_response(resp.status_code, resp.text)
        return False, bad, f"status={resp.status_code} {resp.text[:300]}"
    except Exception as e:
        try:
            tb = frappe.get_traceback()
        except Exception:
            tb = ""
        frappe.log_error(
            title="FCM Send Error",
            message=(
                f"recipient={_describe_token(token)}\n"
                f"exc_type={type(e).__name__}\nexc_str={str(e)[:400]}\n"
                f"traceback:\n{tb}"
            ),
        )
        return False, False, f"{type(e).__name__}: {str(e)[:300]}"


def _site_url() -> str:
    try:
        return frappe.utils.get_url()
    except Exception:
        return ""


def _enabled_devices(user):
    """The user's enabled `ESS Push Device` rows (newest first); [] when the
    doctype is not migrated yet."""
    if not user:
        return []
    try:
        return frappe.get_all(
            _DEVICE_DT,
            filters={"user": user, "enabled": 1},
            fields=["name", "token", "platform"],
            order_by="modified desc",
        )
    except Exception:
        return []


def _disable_device(name: str, error: str) -> None:
    """FCM rejected this device's token for good: stop sending to it."""
    try:
        from frappe.utils import now

        frappe.db.set_value(
            _DEVICE_DT, name,
            {"enabled": 0, "last_error": f"{now()} {error or ''}"[:1000]},
            update_modified=False,
        )
        frappe.db.commit()
    except Exception:
        frappe.log_error(title="FCM Device Disable Error", message=frappe.get_traceback())


def _fan_out(user, primary_token, title, body, data) -> bool:
    """Send to the Employee's own token (if any) plus every enabled device of
    `user`, each token once. True if any send succeeded. Only device rows are
    ever disabled on a dead-token response — never Employee.custom_fcm_token."""
    from opportunity_management.opportunity_management.fcm_webpush import merge_targets

    any_ok = False
    for target in merge_targets(primary_token, _enabled_devices(user)):
        ok, bad, error = _send_fcm_result(target["token"], title, body, data, target["platform"])
        any_ok = any_ok or ok
        if not ok and bad and target["device"]:
            _disable_device(target["device"], error)
    return any_ok


def send_fcm_to_employee(employee_id: str, title: str, body: str, data: dict = None) -> bool:
    """Push to the employee's phone token plus their user's registered devices."""
    row = frappe.db.get_value("Employee", employee_id, ["custom_fcm_token", "user_id"], as_dict=True)
    if not row:
        return False
    user = row.get("user_id")
    ok = _fan_out(user, row.get("custom_fcm_token"), title, body, data)
    if ok and user:
        _create_notification_log(user, title, body)
    return ok


def send_fcm_to_user(user_email: str, title: str, body: str, data: dict = None) -> bool:
    """Via the user's Employee when there is one; otherwise straight to the
    user's registered devices (web tokens of non-employee System Managers)."""
    if not user_email:
        return False
    employee_id = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if employee_id:
        return send_fcm_to_employee(employee_id, title, body, data)
    ok = _fan_out(user_email, None, title, body, data)
    if ok:
        _create_notification_log(user_email, title, body)
    return ok
