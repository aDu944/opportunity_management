# Singleton configuration of the WhatsApp AI responder (ai_agent.py). The API
# key is NOT here: it lives in site_config as `anthropic_api_key` only.
# Defaults / seed text: patches/seed_ai_settings.py (ai_agent_seed.py).

import frappe
from frappe.model.document import Document


class WhatsAppAISettings(Document):
    def validate(self):
        self.live_share_percent = min(max(int(self.live_share_percent or 0), 0), 100)
        for field, floor in (("max_turns", 1), ("history_messages", 2), ("max_output_tokens", 256)):
            if int(self.get(field) or 0) < floor:
                self.set(field, floor)
        for field in ("monthly_budget_usd", "replay_budget_usd"):
            if (self.get(field) or 0) < 0:
                self.set(field, 0)
        self.ai_menus = ",".join(m.strip() for m in (self.ai_menus or "").replace("\n", ",").split(",") if m.strip())
        unknown = [m for m in self.ai_menus.split(",") if m and not frappe.db.exists("WhatsApp Menu", m)]
        if unknown:
            frappe.msgprint("Unknown WhatsApp Menu keys in AI Menus: {0}".format(", ".join(unknown)),
                            indicator="orange")
