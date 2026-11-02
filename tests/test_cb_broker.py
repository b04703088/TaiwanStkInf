import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fetch_cb_broker as F  # noqa: E402


def case(**kw):
    c = {k: "" for k in ("board_date", "filed_date", "eff_date", "bb_start", "bb_end", "done_date")}
    c.update(kw)
    return c


TD = [f"2026-10-{d:02d}" for d in range(1, 31)]   # 30 個「交易日」


class StagesTest(unittest.TestCase):
    def test_open_stage_runs_to_last_day(self):
        c = case(board_date="2026-10-22", filed_date="2026-10-27", eff_date="2026-11-16")
        st = {w: (a, b, fin) for w, a, b, fin in F.stages(c, TD)}
        self.assertEqual(st["s0"], ("2026-10-02", "2026-10-21", True))
        self.assertEqual(st["s1"], ("2026-10-22", "2026-10-26", True))
        self.assertEqual(st["s2"], ("2026-10-27", "2026-10-30", False))   # 生效日還沒到
        self.assertNotIn("s3", st)

    def test_priced_case_has_closed_s4(self):
        c = case(board_date="2026-10-21", filed_date="2026-10-23", eff_date="2026-10-25",
                 bb_start="2026-10-27", done_date="2026-10-28")
        st = {w: (a, b, fin) for w, a, b, fin in F.stages(c, TD)}
        self.assertEqual(st["s3"], ("2026-10-25", "2026-10-26", True))
        self.assertEqual(st["s4"], ("2026-10-27", "2026-10-28", True))

    def test_active_cases_skip_withdrawn(self):
        base = dict(method="詢價圈購", code="1234", sfb_status="生效", wd_date="")
        cs = [case(**base, id="a", board_date="2026-10-01"),
              case(**{**base, "wd_date": "2026-10-05"}, id="b", board_date="2026-10-01")]
        self.assertEqual([c["id"] for c in F.active_cases(cs, "2026-10-30")], ["a"])


if __name__ == "__main__":
    unittest.main()
