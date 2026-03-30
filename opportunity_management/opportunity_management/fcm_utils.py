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

_app = None


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
                "firebase_service_account key not found in site config.\n"
                "Add it via Frappe Cloud dashboard → Sites → Config.",
                "FCM Setup Error",
            )
            return None

        account_info = json.loads(raw) if isinstance(raw, str) else raw
        cred = credentials.Certificate(account_info)

        try:
            _app = firebase_admin.get_app()
        except ValueError:
            _app = firebase_admin.initialize_app(cred)

        return _app
    except Exception as e:
        frappe.log_error(str(e), "FCM Init Error")
        return None


def send_fcm(token: str, title: str, body: str, data: dict = None) -> bool:
    """Send an FCM notification to a single device token. Returns True on success."""
    app = _get_app()
    if not app:
        return False
    try:
        from firebase_admin import messaging

        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={str(k): str(v) for k, v in (data or {}).items()},
            token=token,
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default", badge=1)
                )
            ),
        )
        messaging.send(msg, app=app)
        return True
    except Exception as e:
        frappe.log_error(str(e), "FCM Send Error")
        return False


def send_fcm_to_employee(employee_id: str, title: str, body: str, data: dict = None) -> bool:
    """Look up the employee's FCM token and send a notification."""
    token = frappe.db.get_value("Employee", employee_id, "custom_fcm_token")
    if not token:
        return False
    return send_fcm(token, title, body, data)


def send_fcm_to_user(user_email: str, title: str, body: str, data: dict = None) -> bool:
    """Look up the employee by user_id and send a notification."""
    employee_id = frappe.db.get_value("Employee", {"user_id": user_email}, "name")
    if not employee_id:
        return False
    return send_fcm_to_employee(employee_id, title, body, data)
