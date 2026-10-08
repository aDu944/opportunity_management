"""
Bench-free tests for `team_today_pure` (late cutoff + attendance roll-up).

    python3 opportunity_management/opportunity_management/tests/test_team_today_pure.py
"""

import datetime as dt
import importlib.util
import os
import unittest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(_HERE, "team_today_pure.py")
    spec = importlib.util.spec_from_file_location("team_today_pure_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P = _load()
D = dt.date(2026, 10, 6)


def at(h, m, s=0):
    return dt.datetime.combine(D, dt.time(h, m, s))


class TestCutoff(unittest.TestCase):
    def test_default(self):
        self.assertEqual(P.late_cutoff(None, None), dt.time(9, 15))

    def test_settings(self):
        self.assertEqual(P.late_cutoff(8, 30), dt.time(8, 30))
        self.assertEqual(P.late_cutoff("9", "45"), dt.time(9, 45))
        self.assertEqual(P.late_cutoff(9, 75), dt.time(10, 15))

    def test_garbage(self):
        self.assertEqual(P.late_cutoff("x", "y"), dt.time(9, 15))
        self.assertEqual(P.late_cutoff(30, -5), dt.time(9, 15))

    def test_boundary_is_on_time(self):
        c = dt.time(9, 15)
        self.assertFalse(P.is_late(at(9, 15, 0), c))
        self.assertTrue(P.is_late(at(9, 15, 1), c))
        self.assertFalse(P.is_late(None, c))


class TestSummarize(unittest.TestCase):
    def test_empty(self):
        s = P.empty_summary()
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["late_names"], [])

    def test_rollup(self):
        rows = [
            {"employee_name": "Ali", "first_in": at(9, 40), "last_in": at(9, 40),
             "last_out": at(17, 0), "on_leave": 0},
            {"employee_name": "Sara", "first_in": at(9, 20), "last_in": at(13, 0),
             "last_out": at(12, 0), "on_leave": 0},
            {"employee_name": "Omar", "first_in": at(8, 55), "last_in": at(8, 55),
             "last_out": None, "on_leave": 1},
            {"employee_name": "Huda", "first_in": None, "on_leave": 1},
            {"employee_name": "zaid", "first_in": None, "on_leave": 0},
            {"employee_name": "Bashar", "first_in": None, "on_leave": 0},
        ]
        s = P.summarize(rows, dt.time(9, 15))
        self.assertEqual(s["total"], 6)
        self.assertEqual(s["checked_in"], 3)
        self.assertEqual(s["late"], 2)
        self.assertEqual(s["on_leave"], 1)  # Omar came in, so not on leave
        self.assertEqual(s["not_in"], 2)
        self.assertEqual(s["checked_out"], 1)  # Sara re-checked in after OUT
        self.assertEqual(s["late_names"], ["Sara", "Ali"])
        self.assertEqual(s["not_in_names"], ["Bashar", "zaid"])

    def test_name_limit(self):
        rows = [{"employee_name": f"E{i}", "first_in": None} for i in range(8)]
        s = P.summarize(rows, dt.time(9, 15))
        self.assertEqual(s["not_in"], 8)
        self.assertEqual(len(s["not_in_names"]), 5)


class TestAttendance(unittest.TestCase):
    C = dt.time(9, 15)

    def raw(self, emp, name, first_in=None, last_in=None, last_out=None, zone=None):
        return {"employee": emp, "employee_name": name, "department": "Sales",
                "designation": None, "image": None, "first_in": first_in,
                "last_in": last_in or first_in, "last_out": last_out, "zone": zone}

    def test_fmt_time(self):
        self.assertEqual(P.fmt_time(at(8, 5, 9)), "08:05:09")
        self.assertEqual(P.fmt_time(dt.timedelta(hours=17, minutes=3)), "17:03:00")
        self.assertIsNone(P.fmt_time(None))

    def test_minutes_late_rounds_up(self):
        self.assertEqual(P.minutes_late(at(9, 15, 0), self.C), 0)
        self.assertEqual(P.minutes_late(at(9, 15, 1), self.C), 1)
        self.assertEqual(P.minutes_late(at(9, 38), self.C), 23)
        self.assertEqual(P.minutes_late(None, self.C), 0)

    def test_parse_zone_first_in(self):
        self.assertEqual(P.parse_zone("1|At client\x1e0|"), (True, "At client"))
        self.assertEqual(P.parse_zone("0|stale\x1e1|later"), (False, None))
        self.assertEqual(P.parse_zone(None), (False, None))
        self.assertEqual(P.parse_zone("1|"), (True, None))

    def test_status_mapping(self):
        c = self.C
        self.assertEqual(P.attendance_status(self.raw("A", "a", at(8, 50)), c), "present")
        self.assertEqual(P.attendance_status(self.raw("A", "a", at(9, 30)), c), "late")
        self.assertEqual(P.attendance_status(
            self.raw("A", "a", at(8, 50), last_out=at(16, 5)), c), "checked_out")
        # late stays late after leaving
        self.assertEqual(P.attendance_status(
            self.raw("A", "a", at(9, 30), last_out=at(16, 5)), c), "late")
        # OUT then IN again → back in
        self.assertEqual(P.attendance_status(
            self.raw("A", "a", at(8, 50), last_in=at(13, 0), last_out=at(12, 0)), c), "present")
        self.assertEqual(P.attendance_status(dict(self.raw("A", "a"), on_leave=True), c), "on_leave")
        self.assertEqual(P.attendance_status(self.raw("A", "a"), c), "not_in")

    def test_build_and_sort(self):
        raw = [
            self.raw("P1", "Pia", at(8, 40), zone="1|Site visit"),
            self.raw("L1", "Lea", at(9, 20)),
            self.raw("L2", "Lou", at(10, 5), last_out=at(15, 0)),
            self.raw("N1", "zed"),
            self.raw("N2", "Amy"),
            self.raw("O1", "Oz", at(8, 0), last_out=at(16, 0)),
            self.raw("V1", "Val"),
            self.raw("V2", "Vic", at(9, 0)),  # on leave but came in
        ]
        summary, rows = P.build_attendance(raw, {"V1": "Annual Leave", "V2": "Sick"}, self.C)
        self.assertEqual(summary, {"total": 8, "checked_in": 5, "late": 2,
                                   "on_leave": 1, "not_in": 2, "checked_out": 2})
        self.assertEqual([r["employee"] for r in rows],
                         ["L2", "L1", "N2", "N1", "P1", "V2", "O1", "V1"])
        by = {r["employee"]: r for r in rows}
        self.assertEqual(by["L2"]["minutes_late"], 50)
        self.assertTrue(by["L2"]["checked_out"])
        self.assertEqual(by["L2"]["last_out"], "15:00:00")
        self.assertEqual(by["P1"]["outside_zone"], True)
        self.assertEqual(by["P1"]["outside_zone_reason"], "Site visit")
        self.assertEqual(by["V1"]["status"], "on_leave")
        self.assertEqual(by["V1"]["leave_type"], "Annual Leave")
        self.assertEqual(by["V2"]["status"], "present")
        self.assertIsNone(by["N1"]["first_in"])

    def test_working_day(self):
        tue = dt.date(2026, 10, 6)
        fri = dt.date(2026, 10, 9)
        self.assertTrue(P.is_working_day(tue, None))
        self.assertFalse(P.is_working_day(fri, None))
        self.assertTrue(P.is_working_day(fri, "Fri, Sat"))
        self.assertFalse(P.is_working_day(tue, "Sun,Tue", {tue}))

    def test_clamp_day(self):
        t = dt.date(2026, 10, 6)
        self.assertEqual(P.clamp_day(None, t), t)
        self.assertEqual(P.clamp_day(dt.date(2026, 10, 7), t), t)
        self.assertEqual(P.clamp_day(dt.date(2026, 10, 1), t), dt.date(2026, 10, 1))


class TestBranches(unittest.TestCase):
    C = dt.time(9, 15)

    def raw(self, emp, branch, first_in=None, last_out=None):
        return {"employee": emp, "employee_name": emp, "branch": branch,
                "first_in": first_in, "last_in": first_in, "last_out": last_out}

    def rows(self):
        return [
            self.raw("B1", "Baghdad", at(8, 50)),
            self.raw("B2", "Baghdad", at(9, 40)),
            self.raw("B3", "Baghdad"),
            self.raw("A1", "Amman", at(8, 0), last_out=at(16, 0)),
            self.raw("A2", "Amman"),
            self.raw("E1", "Erbil", at(9, 0)),
            self.raw("X1", None),
            self.raw("X2", "  "),
            self.raw("Z1", "abu dhabi"),
        ]

    def test_norm_and_order(self):
        self.assertEqual(P.norm_branch(None), "")
        self.assertEqual(P.norm_branch(" Amman "), "Amman")
        self.assertEqual(P.branch_order(["Erbil", "", "Amman", "Baghdad", None], "Baghdad"),
                         ["Baghdad", "Amman", "Erbil", ""])
        self.assertEqual(P.branch_order(["Erbil", "", "abu dhabi", "Amman"]),
                         ["abu dhabi", "Amman", "Erbil", ""])
        # The caller's branch leads even when nobody else is in it.
        self.assertEqual(P.branch_order(["Amman"], "Erbil"), ["Erbil", "Amman"])
        self.assertEqual(P.branch_order([], ""), [])

    def test_card_scoped_to_my_branch(self):
        s = P.summarize_by_branch(self.rows(), self.C, "Baghdad")
        self.assertEqual(s["my_branch"], "Baghdad")
        self.assertEqual(s["summary_scope"], "branch")
        self.assertEqual((s["total"], s["checked_in"], s["late"], s["not_in"]), (3, 2, 1, 1))
        self.assertEqual(s["late_names"], ["B2"])
        self.assertEqual(s["not_in_names"], ["B3"])
        self.assertEqual([b["branch"] for b in s["other_branches"]],
                         ["abu dhabi", "Amman", "Erbil", ""])
        amman = s["other_branches"][1]
        self.assertEqual(amman, {"branch": "Amman", "total": 2, "checked_in": 1,
                                 "late": 0, "on_leave": 0, "not_in": 1})
        self.assertEqual(s["other_branches"][-1]["total"], 2)  # NULL + blank

    def test_card_without_branch_is_everyone(self):
        s = P.summarize_by_branch(self.rows(), self.C, None)
        self.assertEqual(s["my_branch"], "")
        self.assertEqual(s["summary_scope"], "all")
        self.assertEqual(s["total"], 9)
        self.assertEqual(s["other_branches"], [])
        e = P.empty_branch_summary()
        self.assertEqual((e["total"], e["other_branches"]), (0, []))

    def test_page_payload(self):
        out = P.build_branch_attendance(self.rows(), {"A2": "Annual"}, self.C, "Amman")
        self.assertEqual(out["my_branch"], "Amman")
        self.assertEqual(out["summary_scope"], "branch")
        self.assertEqual(out["summary"], {"total": 2, "checked_in": 1, "late": 0,
                                          "on_leave": 1, "not_in": 0, "checked_out": 1})
        self.assertEqual([b["branch"] for b in out["branches"]],
                         ["Amman", "abu dhabi", "Baghdad", "Erbil", ""])
        self.assertEqual(sum(b["total"] for b in out["branches"]), 9)
        by = {r["employee"]: r for r in out["rows"]}
        self.assertEqual(by["X1"]["branch"], "")
        self.assertEqual(by["X2"]["branch"], "")
        self.assertEqual(by["B2"]["branch"], "Baghdad")
        self.assertEqual(by["A2"]["status"], "on_leave")

    def test_page_without_branch(self):
        out = P.build_branch_attendance(self.rows(), {}, self.C, "")
        self.assertEqual(out["summary_scope"], "all")
        self.assertEqual(out["summary"]["total"], 9)
        self.assertEqual(out["branches"][-1]["branch"], "")
        self.assertEqual(len(out["rows"]), 9)

    def test_my_branch_with_nobody(self):
        out = P.build_branch_attendance(self.rows(), {}, self.C, "Basra")
        self.assertEqual(out["summary"]["total"], 0)
        self.assertEqual(out["branches"][0]["branch"], "Basra")


if __name__ == "__main__":
    unittest.main()
