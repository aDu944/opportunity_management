# Email domain -> Customer / Lead, used by the Outlook add-in: emails from
# the domain always suggest that party's Opportunities and pre-select it in
# the create form (outlook_api.lookup, outlook_create.create_defaults).
# Seeded by patches/seed_email_domain_rules.py.

import frappe
from frappe import _
from frappe.model.document import Document

from opportunity_management.opportunity_management import outlook_email_pure as P

DISPLAY_FIELD = {"Customer": "customer_name", "Lead": "lead_name"}


class EmailDomainRule(Document):
    def before_insert(self):
        # Runs before naming (autoname field:domain), so the record is named
        # by the normalised domain.
        self.domain = P.normalize_domain(self.domain)

    def validate(self):
        self.domain = P.normalize_domain(self.domain)
        if not self.domain or "." not in self.domain:
            frappe.throw(_("Enter a domain like badraproject.com"))
        if P.is_public_domain(self.domain):
            frappe.throw(_("{0} is a public mail provider; it can't belong to one customer")
                         .format(self.domain))
        if self.party_type in DISPLAY_FIELD and self.party:
            self.party_display = frappe.db.get_value(self.party_type, self.party,
                                                     DISPLAY_FIELD[self.party_type]) or self.party
