# Controller for ESS Push Device — one row per browser / device push token
# (Firebase Cloud Messaging) of a user, in addition to the phone's own
# Employee.custom_fcm_token. Written by push_devices.register_push_device;
# read by fcm_utils.send_fcm_to_employee / send_fcm_to_user, which fan out to
# every enabled row and disable a row whose token FCM reports as dead.

from frappe.model.document import Document


class ESSPushDevice(Document):
    pass
