"""
Bench-free tests for the inbox channel layer (WhatsApp + Messenger):

    inbox_channels.channels_for_roles / manager_channels_for_roles / caps_for
    / window_state / channel_sql / agents_with_channels / conv_channel

    python3 opportunity_management/opportunity_management/tests/test_inbox_channels_pure.py

The pure half of the module imports nothing, so it is loaded straight off disk.
"""

import importlib.util
import os
import sys
import unittest
from datetime import datetime, timedelta

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


IC = _load("_inbox_channels_under_test", "inbox_channels.py")

WA_ROLES = ["WhatsApp Agent", "WhatsApp Manager"]
NOW = datetime(2026, 10, 5, 12, 0, 0)


def old_whatsapp_remaining(last, now):
    """The pre-Messenger serializer rule, verbatim (window_seconds_remaining)."""
    if not last:
        return 0
    remaining = 24 * 60 * 60 - (now - last).total_seconds()
    return int(remaining) if remaining > 0 else 0


class TestAccess(unittest.TestCase):
    def test_whatsapp_agent(self):
        self.assertEqual(IC.channels_for_roles({"WhatsApp Agent"}, WA_ROLES), ["WhatsApp"])

    def test_custom_inbox_role_still_whatsapp(self):
        self.assertEqual(IC.channels_for_roles({"Sales User"}, ["Sales User"]), ["WhatsApp"])

    def test_messenger_agent_only(self):
        self.assertEqual(IC.channels_for_roles({"Messenger Agent"}, WA_ROLES), ["Messenger"])

    def test_both_in_fixed_order(self):
        roles = {"Messenger Manager", "WhatsApp Agent"}
        self.assertEqual(IC.channels_for_roles(roles, WA_ROLES), ["WhatsApp", "Messenger"])

    def test_system_manager_all(self):
        self.assertEqual(IC.channels_for_roles({"System Manager"}, WA_ROLES), ["WhatsApp", "Messenger"])

    def test_system_manager_messenger_only_when_enabled(self):
        # Until Messenger is switched on, a System Manager's inbox is WhatsApp's.
        self.assertEqual(IC.channels_for_roles({"System Manager"}, WA_ROLES, False), ["WhatsApp"])
        self.assertEqual(IC.manager_channels_for_roles({"System Manager"}, False), ["WhatsApp"])
        # An explicit Messenger role is honoured either way.
        self.assertEqual(IC.channels_for_roles({"Messenger Agent"}, WA_ROLES, False), ["Messenger"])
        self.assertEqual(IC.manager_channels_for_roles({"Messenger Manager"}, False), ["Messenger"])

    def test_nobody(self):
        self.assertEqual(IC.channels_for_roles({"Employee"}, WA_ROLES), [])

    def test_manager_is_per_channel(self):
        self.assertEqual(IC.manager_channels_for_roles({"WhatsApp Manager", "Messenger Agent"}), ["WhatsApp"])
        self.assertEqual(IC.manager_channels_for_roles({"Messenger Manager"}), ["Messenger"])
        self.assertEqual(IC.manager_channels_for_roles({"WhatsApp Agent"}), [])
        self.assertEqual(IC.manager_channels_for_roles({"System Manager"}), ["WhatsApp", "Messenger"])


class TestCaps(unittest.TestCase):
    def test_whatsapp_everything(self):
        self.assertTrue(all(IC.caps_for("WhatsApp").values()))
        self.assertEqual(set(IC.caps_for("WhatsApp")), set(IC.CAP_KEYS))

    def test_messenger(self):
        caps = IC.caps_for("Messenger")
        for off in ("templates", "location", "contact", "block"):
            self.assertFalse(caps[off], off)
        for on in ("reactions", "voice", "video", "documents", "options", "typing", "forward"):
            self.assertTrue(caps[on], on)

    def test_empty_channel_is_whatsapp(self):
        self.assertEqual(IC.caps_for(""), IC.caps_for("WhatsApp"))
        self.assertEqual(IC.conv_channel({"channel": ""}), "WhatsApp")
        self.assertEqual(IC.conv_channel({}), "WhatsApp")
        self.assertEqual(IC.conv_channel({"channel": "Messenger"}), "Messenger")
        self.assertEqual(IC.channel_of("Telegram"), "WhatsApp")


class TestWindow(unittest.TestCase):
    def test_whatsapp_matches_old_rule(self):
        for seconds in (0, 1, 3600, 86399, 86399.5, 86400, 86401, 90000, 7 * 86400):
            last = NOW - timedelta(seconds=seconds)
            mode, remaining = IC.window_state("WhatsApp", last, NOW, human_agent=True)
            old = old_whatsapp_remaining(last, NOW)
            self.assertEqual(remaining, old, seconds)
            self.assertEqual(mode, "standard" if old > 0 else "closed", seconds)

    def test_never_opened(self):
        self.assertEqual(IC.window_state("Messenger", None, NOW, True), ("closed", 0))

    def test_messenger_standard(self):
        mode, remaining = IC.window_state("Messenger", NOW - timedelta(hours=2), NOW, False)
        self.assertEqual((mode, remaining), ("standard", 22 * 3600))

    def test_messenger_human_agent(self):
        mode, remaining = IC.window_state("Messenger", NOW - timedelta(days=2), NOW, True)
        self.assertEqual((mode, remaining), ("human_agent", 5 * 86400))

    def test_messenger_closed_without_permission(self):
        self.assertEqual(IC.window_state("Messenger", NOW - timedelta(days=2), NOW, False), ("closed", 0))

    def test_messenger_closed_after_seven_days(self):
        self.assertEqual(IC.window_state("Messenger", NOW - timedelta(days=7, seconds=1), NOW, True), ("closed", 0))


class TestSql(unittest.TestCase):
    def test_all_channels_no_filter(self):
        self.assertEqual(IC.channel_sql("c.channel", ["WhatsApp", "Messenger"]), "")

    def test_one_channel(self):
        self.assertEqual(
            IC.channel_sql("c.channel", ["WhatsApp"]),
            "COALESCE(NULLIF(c.channel, ''), 'WhatsApp') IN ('WhatsApp')",
        )

    def test_none(self):
        self.assertEqual(IC.channel_sql("channel", []), "1 = 0")

    def test_unknown_values_never_inlined(self):
        self.assertEqual(IC.channel_sql("channel", ["x'); DROP TABLE y; --"]), "1 = 0")


class TestRoster(unittest.TestCase):
    def test_channels_per_agent(self):
        users = {"WhatsApp": ["a", "b"], "Messenger": ["b", "c"]}
        self.assertEqual(
            IC.agents_with_channels(users, ["WhatsApp", "Messenger"]),
            [("a", ["WhatsApp"]), ("b", ["WhatsApp", "Messenger"]), ("c", ["Messenger"])],
        )

    def test_whatsapp_only_caller_sees_whatsapp_roster(self):
        users = {"WhatsApp": ["a", "b"], "Messenger": ["b", "c"]}
        self.assertEqual(
            IC.agents_with_channels(users, ["WhatsApp"]), [("a", ["WhatsApp"]), ("b", ["WhatsApp"])]
        )


if __name__ == "__main__":
    unittest.main()
