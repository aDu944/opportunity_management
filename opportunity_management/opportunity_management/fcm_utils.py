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

# Named Firebase Admin app so we never collide with the default app any
# other code path in the codebase may or may not have initialized. Keyed
# off `_APP_NAME`; two different modules that both want their own creds
# should pick different names. `_app` is a module-level cache holding the
# handle after the first init.
_APP_NAME = "alkhora-ess-fcm"
_app = None


def _reset_app():
    """Drop the cached handle and delete the named app so the next call
    reinitializes with fresh credentials. Useful for self-healing after a
    401/ThirdPartyAuthError caused by stale/rotated tokens."""
    global _app
    _app = None
    try:
        import firebase_admin
        existing = firebase_admin.get_app(_APP_NAME)
        firebase_admin.delete_app(existing)
    except (ValueError, Exception):
        pass


def _get_app():
    global _app
    if _app is not None:
        return _app
    try:
        import firebase_admin
        from firebase_admin import credentials

        # Read service account from site config (works on Frappe Cloud)
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

        # Use a NAMED app so this never overlaps with any other Firebase
        # Admin initialization (e.g. api.py's file-based init that may
        # or may not have populated the default app).
        try:
            _app = firebase_admin.get_app(_APP_NAME)
        except ValueError:
            _app = firebase_admin.initialize_app(cred, name=_APP_NAME)

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


def send_fcm(token: str, title: str, body: str, data: dict = None) -> bool:
    """Send an FCM notification to a single device token. Returns True on success.

    Self-heals from stale-credential 401s: on ThirdPartyAuthError we drop
    the cached Firebase Admin app, reinitialize from site config, and try
    once more before giving up.
    """
    app = _get_app()
    if not app:
        return False
    try:
        from firebase_admin import messaging
        messaging.send(_build_message(token, title, body, data), app=app)
        return True
    except Exception as e:
        # Detect the specific "stale OAuth token" family and retry once
        # with a fresh app before logging.
        etype = type(e).__name__
        is_auth = etype == "ThirdPartyAuthError" or "401" in str(e) or "Unauthorized" in str(e)
        if is_auth:
            _reset_app()
            fresh = _get_app()
            if fresh:
                try:
                    from firebase_admin import messaging
                    messaging.send(_build_message(token, title, body, data), app=fresh)
                    return True
                except Exception as e2:
                    e = e2  # fall through and log the retry error
        # frappe.log_error's title field is 140 chars max — always pass a
        # short constant title and put the exception detail in the message
        # body. Explicit keyword args so version differences in signature
        # order can never swap them.
        frappe.log_error(message=str(e), title="FCM Send Error")
        return False


def send_fcm_to_employee(employee_id: str, title: str, body: str, data: dict = None) -> bool:
    """Look up the employee's FCM token and send a notification."""
    token = frappe.db.get_value("Employee", employee_id, "custom_fcm_token")
    if not token:
        return False
    ok = send_fcm(token, title, body, data)
    if ok:
        user = frappe.db.get_value("Employee", employee_id, "user_id")
        if user:
            _create_notification_log(user, title, body)
    return ok


def send_fcm_to_user(user_email: str, title: str, body: str, data: dict = None) -> bool:
    """Look up the employee by user_id and send a notification."""
    employee_id = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if not employee_id:
        return False
    return send_fcm_to_employee(employee_id, title, body, data)
