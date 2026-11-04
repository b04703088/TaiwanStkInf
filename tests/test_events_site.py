import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import events_site as E  # noqa: E402


class EventsTest(unittest.TestCase):
    def test_et_to_taipei(self):
        # 11 月美東標準時間：08:30 ET = 台灣 21:30；14:00 ET = 台灣隔天 03:00
        self.assertEqual(E.to_tw("2026-11-10", "08:30", "ET"), ("2026-11-10", "21:30"))
        self.assertEqual(E.to_tw("2026-12-09", "14:00", "ET"), ("2026-12-10", "03:00"))
        # 夏令時間：08:30 EDT = 台灣 20:30
        self.assertEqual(E.to_tw("2026-07-14", "08:30", "ET"), ("2026-07-14", "20:30"))
        self.assertEqual(E.to_tw("2026-11-10", "", "ET"), ("2026-11-10", ""))

    def test_settle_and_revenue(self):
        hol = {"2026-12-25": "行憲紀念日"}
        s = E.settle_events(hol, date(2026, 11, 1), date(2026, 12, 31))
        self.assertEqual([(e[0], e[6]) for e in s], [("2026-11-18", 2), ("2026-12-16", 3)])  # 12 月是季結算
        r = E.revenue_deadlines({}, date(2026, 10, 1), date(2026, 11, 30))
        self.assertEqual([e[0] for e in r], ["2026-10-12", "2026-11-10"])  # 10/10 週六 → 順延到週一
        self.assertIn("9 月營收", r[0][4])

    def test_upcoming_filters(self):
        p = {"today": "2026-11-04", "events": [
            ["2026-11-04", "", "macro", "US", "今天", "", 3, False, ""],
            ["2026-11-06", "21:30", "macro", "US", "非農", "", 3, False, ""],
            ["2026-11-06", "", "disp", "TW", "出關", "", 3, False, ""],
            ["2026-11-07", "", "earn", "TW", "小法說", "", 1, False, ""],
            ["2026-11-20", "", "macro", "TW", "太遠", "", 3, False, ""]]}
        self.assertEqual([e[4] for e in E.upcoming(p)], ["非農"])


if __name__ == "__main__":
    unittest.main()
