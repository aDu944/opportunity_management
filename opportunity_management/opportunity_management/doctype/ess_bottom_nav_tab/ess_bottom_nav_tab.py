# Controller for ESS Bottom Nav Tab — one row per tab in the mobile app's
# bottom navigation pill. Replaces the free-text `bottom_nav_layout` string
# so HR picks tabs from a list instead of typing keys that failed silently
# when misspelled. Row order is the display order.
#
# Consumed by api.get_mobile_config, which flattens the rows back into the
# comma-separated string the app already understands.

from frappe.model.document import Document


class ESSBottomNavTab(Document):
    pass
