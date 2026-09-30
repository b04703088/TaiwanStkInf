import csv
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import health  # noqa: E402


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(cols)
        w.writerows(rows)


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        for day in ("20260923", "20260924", "20260929"):
            write(self.d / "2026" / f"{day}.csv", ["code", "close"], [[str(i), "10"] for i in range(1200)])
        (self.d / "no_trading_days.txt").write_text("2026-09-25\n2026-09-28\n")
        write(self.d / "etf" / "etf_list.csv", ["etf", "name", "issuer", "issuer_name", "kind"],
              [["A", "甲", "x", "X", "passive"], ["B", "乙", "x", "X", "passive"], ["C", "丙", "x", "X", "passive"]])
        hold = [[f"{i}", "n", "1000", "10"] for i in range(10)]
        cols = ["code", "name", "shares", "weight"]
        write(self.d / "etf" / "A" / "20260929.csv", cols, hold)                           # 正常
        write(self.d / "etf" / "B" / "20260923.csv", cols, hold)                           # 落後 2 天
        write(self.d / "etf" / "C" / "20260929.csv", cols, [r[:3] + ["5"] for r in hold])  # 權重 50%
        self.now = datetime(2026, 9, 30, 9, 10, tzinfo=health.TPE)

    def tearDown(self):
        self.tmp.cleanup()

    def levels(self, h):
        return {i["id"]: i["level"] for i in h["items"]}

    def test_levels(self):
        h = health.check(self.d, self.now)
        self.assertEqual(h["expected"], "2026-09-29")
        lv = self.levels(h)
        self.assertEqual((lv["prices"], lv["A"], lv["B"], lv["C"]), ("ok", "ok", "error", "error"))

    def test_missing_price_day(self):
        h = health.check(self.d, datetime(2026, 10, 1, 9, 10, tzinfo=health.TPE))  # 應有 09-30，沒抓到
        lv = self.levels(h)
        self.assertEqual(lv["prices"], "error")
        self.assertEqual(lv["A"], "ok")  # 落後 1 天（09-30）不算異常

    def test_holiday_not_expected(self):
        h = health.check(self.d, datetime(2026, 9, 28, 9, 10, tzinfo=health.TPE))  # 09-25 休市 → 應有 09-24
        self.assertEqual(h["expected"], "2026-09-24")


if __name__ == "__main__":
    unittest.main()
