import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import calendar_site as C  # noqa: E402
import fetch_holidays as H  # noqa: E402


class HolidayTest(unittest.TestCase):
    def test_parse_skips_trading_days(self):
        items = [{"Name": "中華民國開國紀念日", "Date": "1150101"},
                 {"Name": "國曆新年開始交易日", "Date": "1150102"},
                 {"Name": "農曆春節前最後交易日", "Date": "1150211"},
                 {"Name": "市場無交易，僅辦理結算交割作業", "Date": "1150212"}]
        self.assertEqual(sorted(H.parse(items)), ["2026-01-01", "2026-02-12"])


class ProjectTest(unittest.TestCase):
    HOL = {"2026-12-25": "行憲紀念日"}

    def test_projects_same_weekday_next_year(self):
        rv = [["臺灣50指數", "FTSE", "2025-12-05", "2025-12-22", ["0050"], False, [], []]]
        out = C.project(rv, self.HOL, date(2026, 10, 6))
        self.assertEqual([(r[2], r[3], r[5]) for r in out], [("2026-12-04", "2026-12-21", True)])

    def test_skip_when_scheduled(self):
        rv = [["X指數", "TIP", "2025-12-16", "2025-12-17", [], False, [], []],
              ["X指數", "TIP", "2026-12-14", "2026-12-15", [], False, [], []]]
        self.assertEqual(C.project(rv, self.HOL, date(2026, 10, 6)), [])

    def test_keeps_trading_day_gap_over_new_year(self):
        """去年 12/31 公告、隔一個交易日（1/2）生效 → 今年 12/30 公告、12/31 生效"""
        rv = [["Y指數", "TIP", "2025-12-31", "2026-01-02", [], False, [], []]]
        out = C.project(rv, self.HOL, date(2026, 10, 6))
        self.assertEqual((out[0][2], out[0][3]), ("2026-12-30", "2026-12-31"))



class CutoffTest(unittest.TestCase):
    def setUp(self):
        import index_rules as IR
        self.IR = IR
        self.cal = IR.TradingCalendar([], {"2026-10-09": "", "2026-10-26": ""})

    def cut(self, etf, ann, eff):
        c = self.IR.cutoff(self.IR.RULES[etf], ann, eff, self.cal)
        return c[0].isoformat(), c[1].isoformat()

    def test_ftse_four_weeks_before(self):
        self.assertEqual(self.cut("0050", "2026-09-04", "2026-09-21"), ("2026-08-24", "2026-08-24"))

    def test_tip_month_rules(self):
        self.assertEqual(self.cut("00919", "2026-12-15", "2026-12-16")[0], "2026-11-30")   # 12 月審核：11 月最後交易日
        self.assertEqual(self.cut("00923", "2026-10-02", "2026-10-05")[0], "2026-09-09")   # 9 月第 7 個交易日
        self.assertEqual(self.cut("00881", "2026-10-19", "2026-10-20")[0], "2026-09-30")

    def test_msci_window(self):
        self.assertEqual(self.cut("0057", "2026-11-11", "2026-12-01"), ("2026-10-19", "2026-10-30"))

    def test_ice(self):
        self.assertEqual(self.cut("00891", "", "2026-10-27"), ("2026-10-13", "2026-10-13"))
        self.assertEqual([d.isoformat() for d in self.IR.ice_reviews(self.cal, date(2026, 10, 1), date(2026, 10, 31))], ["2026-10-27"])


if __name__ == "__main__":
    unittest.main()
