# A team a WhatsApp conversation can be handed to (agent_groups.py): Ring
# alerts every active member, Round Robin assigns the next one directly.

from frappe.model.document import Document


class WhatsAppAgentGroup(Document):
    def validate(self):
        # One row per user; a negative timeout means "off", same as 0.
        seen, rows = set(), []
        for row in self.members or []:
            if row.user and row.user not in seen:
                seen.add(row.user)
                rows.append(row)
        if len(rows) != len(self.members or []):
            self.set("members", rows)
        if (self.first_response_timeout_minutes or 0) < 0:
            self.first_response_timeout_minutes = 0
