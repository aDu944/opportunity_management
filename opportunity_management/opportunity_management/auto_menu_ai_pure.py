"""
The AI branch of the WhatsApp auto menu engine — pure (no frappe).

Mixed into auto_menu_pure._Flow. `settings["ai_mode"]` ("off" | "shadow" |
"live", per conversation: ai_agent_pure.mode_for) and `settings["ai_menus"]`
(menu keys) come from auto_menu.engine_settings.

    free text in an AI menu, Shadow   the strict menu as before + ai_turn (draft)
    free text in an AI menu, Live     ai_turn, state ai:<key>, no strike
    state ai:<key>                    keywords and a tap on that menu's list
                                      still work; anything else → ai_turn

The ai_turn effect carries `fallback`: what the strict menu would have done,
applied when the model refuses, errors or says nothing.
"""

import re

from opportunity_management.opportunity_management import auto_menu_form_pure as F

AI = "ai"
_DIGIT_RE = re.compile(r"^\s*([0-9])\s*[.)\-]?\s*$")  # same as auto_menu_pure.parse_digit


class AiSteps:
    def ai_mode(self, key):
        """"shadow" | "live" | None for menu `key`."""
        mode = self.settings.get("ai_mode")
        if mode in ("shadow", "live") and key in (self.settings.get("ai_menus") or ()):
            return mode
        return None

    def ai_turn(self, key) -> bool:
        mode = self.ai_mode(key)
        if not mode:
            return False
        effects, values = self.effects, self.values
        self.effects, self.values = [], dict(values)
        self.show(key, please=True)
        strict = self.finish()
        if mode == "shadow":
            self.effects, self.values = effects + strict, {}
        else:
            self.effects, self.values = effects, dict(values, menu_state=AI + ":" + key)
        self.effects.append({"do": "ai_turn", "menu": key, "mode": mode, "lang": self.lang, "fallback": strict})
        return True

    def in_ai(self, key):
        if key not in self.menus or self.ai_mode(key) != "live":
            return self.in_menu(key)
        tap = self.tap or ""
        if self.kw or tap.startswith(("opt:", "menu:", "lang:")) or self.menu_digit(key):
            return self.in_menu(key)
        self.ai_turn(key)

    def menu_digit(self, key) -> bool:
        """A typed digit naming a row of this menu is a menu choice, not a question."""
        if self.inbound.get("kind") != "text":
            return False
        match = _DIGIT_RE.match(F.to_ascii_digits(self.inbound.get("text") or ""))
        digits = {str(o.get("digit")) for o in (self.menus.get(key) or {}).get("options") or []}
        return bool(match and match.group(1) in digits)
