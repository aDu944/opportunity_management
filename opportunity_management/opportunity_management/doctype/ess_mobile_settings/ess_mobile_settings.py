# Controller for the ESS Mobile Settings singleton. Deliberately minimal —
# every consumer reads via `frappe.get_single("ESS Mobile Settings")` and
# accesses fields via `.get(fieldname)`; no cross-field validation or
# derived state lives here. See api.get_mobile_config for the assembly
# of this single into the mobile-facing config payload.

from frappe.model.document import Document


class ESSMobileSettings(Document):
    pass
