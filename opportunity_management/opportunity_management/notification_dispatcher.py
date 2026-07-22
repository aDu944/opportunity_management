"""
Async FCM dispatch — pushes each send into the RQ short queue so the
originating request (doc submit, Notification Log insert, etc.) returns
immediately instead of blocking on ~200-400ms per push.

Each ephemeral naked-app FCM send does an OAuth handshake with Google;
without enqueuing, a Journal Entry that touches N employees and gets
broadcast to M managers blocks for (N+M) × handshake time before the
"Submitted" response reaches the browser. Moving to the queue keeps
submits at baseline speed; pushes still land within a few seconds.

Public helpers mirror the direct fcm_utils functions:
  enqueue_fcm_to_user(email, title, body, data)
  enqueue_fcm_to_employee(employee_id, title, body, data)
  enqueue_fcm(token, title, body, data)

Worker entrypoints (`_worker_*`) are the RQ-invoked module-level jobs
they enqueue; they exist as separate functions because `frappe.enqueue`
serializes the target as a dotted path.
"""

import frappe


# ── Public enqueue helpers ────────────────────────────────────────────────────

def enqueue_fcm_to_user(user_email: str, title: str, body: str, data: dict = None) -> None:
    if not user_email:
        return
    frappe.enqueue(
        "opportunity_management.opportunity_management.notification_dispatcher._worker_send_to_user",
        queue="short",
        user_email=user_email,
        title=title,
        body=body,
        data=data or {},
    )


def enqueue_fcm_to_employee(employee_id: str, title: str, body: str, data: dict = None) -> None:
    if not employee_id:
        return
    frappe.enqueue(
        "opportunity_management.opportunity_management.notification_dispatcher._worker_send_to_employee",
        queue="short",
        employee_id=employee_id,
        title=title,
        body=body,
        data=data or {},
    )


def enqueue_fcm(token: str, title: str, body: str, data: dict = None) -> None:
    if not token:
        return
    frappe.enqueue(
        "opportunity_management.opportunity_management.notification_dispatcher._worker_send_raw",
        queue="short",
        token=token,
        title=title,
        body=body,
        data=data or {},
    )


# ── Worker entrypoints (invoked by RQ) ────────────────────────────────────────

def _worker_send_to_user(user_email: str, title: str, body: str, data: dict) -> None:
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_user
    try:
        send_fcm_to_user(user_email, title=title, body=body, data=data)
    except Exception:
        frappe.log_error(
            title="FCM Enqueued Send Error",
            message=f"user={user_email}\n{frappe.get_traceback()}",
        )


def _worker_send_to_employee(employee_id: str, title: str, body: str, data: dict) -> None:
    from opportunity_management.opportunity_management.fcm_utils import send_fcm_to_employee
    try:
        send_fcm_to_employee(employee_id, title=title, body=body, data=data)
    except Exception:
        frappe.log_error(
            title="FCM Enqueued Send Error",
            message=f"employee={employee_id}\n{frappe.get_traceback()}",
        )


def _worker_send_raw(token: str, title: str, body: str, data: dict) -> None:
    from opportunity_management.opportunity_management.fcm_utils import send_fcm
    try:
        send_fcm(token, title=title, body=body, data=data)
    except Exception:
        frappe.log_error(
            title="FCM Enqueued Send Error",
            message=f"token={token[:20]}...\n{frappe.get_traceback()}",
        )
