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


def send_fcm(token: str, title: str, body: str, data: dict = None) -> bool:
    """Send an FCM notification to a single device token. Returns True on success.

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
        return False
    account_info = json.loads(raw) if isinstance(raw, str) else raw
    project_id = account_info.get("project_id")
    if not project_id:
        frappe.log_error(
            title="FCM Setup Error",
            message="project_id missing from firebase_service_account",
        )
        return False

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
                },
            },
            "apns": {
                "payload": {
                    "aps": {"sound": "bell.caf", "badge": 1},
                },
            },
        }
    }

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
            return True
        # Frappe's log_error title is capped at 140 chars — keep title constant.
        frappe.log_error(
            title="FCM Send Error",
            message=(
                f"status={resp.status_code}\n"
                f"body={resp.text[:600]}"
            ),
        )
        return False
    except Exception as e:
        try:
            tb = frappe.get_traceback()
        except Exception:
            tb = ""
        frappe.log_error(
            title="FCM Send Error",
            message=f"exc_type={type(e).__name__}\nexc_str={str(e)[:400]}\ntraceback:\n{tb}",
        )
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
