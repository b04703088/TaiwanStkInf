import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import commod_site as C  # noqa: E402
import fetch_commod as F  # noqa: E402


class CommodSiteTest(unittest.TestCase):
    def test_weekly_detection(self):
        self.assertTrue(C.weekly(["2026-10-16", "2026-10-23"]))
        self.assertFalse(C.weekly(["2026-10-27", "2026-10-28", "2026-10-29"]))

    def test_stats_daily(self):
        ds = [f"2026-{m:02d}-{d:02d}" for m in range(1, 11) for d in range(1, 29)][-300:]
        cs = [100.0 + i for i in range(len(ds))]
        s = C.stats(ds, cs)
        self.assertAlmostEqual(s["r"][0], round((cs[-1] / cs[-2] - 1) * 100, 2))
        self.assertAlmostEqual(s["r"][1], round((cs[-1] / cs[-6] - 1) * 100, 2))
        self.assertEqual(s["pos"], 100)
        self.assertGreater(s["streak"], 20)
        self.assertFalse(s["wk"])

    def test_stats_weekly_steps(self):
        ds = ["2026-09-25", "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23"]
        s = C.stats(ds, [100.0, 110.0, 120.0, 100.0, 90.0])
        self.assertTrue(s["wk"])
        self.assertAlmostEqual(s["r"][0], -10.0)    # 比上一期
        self.assertAlmostEqual(s["r"][2], -10.0)    # 4 期前 100 → 90
        self.assertEqual(s["streak"], -2)

    def test_group_corr(self):
        from datetime import date, timedelta
        dd = [date(2026, 1, 1) + timedelta(days=i) for i in range(80)]
        days = [int(d.strftime("%Y%m%d")) for d in dd]
        # 報價日期在台股日之前一天 → 每個台股日對應前一晚
        series = {"x": ([(d - timedelta(days=1)).isoformat() for d in dd], [100.0 + (i % 3) for i in range(80)])}
        prices = {"1111": {"name": "甲", "rows": [(d, 10, 10, 10, 10 + (i % 3), 1) for i, d in enumerate(days)]}}
        items = [{"key": "x", "name": "X", "cat": "金屬", "sub": "", "unit": "", "label": ""}]
        mapping = [{"item": "x", "group": "甲族群", "codes": "1111", "effect": "受惠", "note": ""}]
        out = C.build(prices, days, {}, series, items, mapping)
        g = out["groups"][0]
        self.assertEqual(g[1], "甲族群")
        self.assertIsNotNone(g[7])


class FetchCommodTest(unittest.TestCase):
    def test_sse_parse(self):
        page = "<td>上期 2026-10-16</td><td>本期 2026-10-23</td> 综合指数 Comprehensive Index <td>3679.58</td><td>3681.34</td>"
        F._page.clear()
        old = F.get
        try:
            F.get = lambda u, h=None, timeout=30: page
            self.assertEqual(F.sse("scfi:综合指数 Comprehensive Index"), {"2026-10-16": 3679.58, "2026-10-23": 3681.34})
        finally:
            F.get = old
            F._page.clear()

    def test_cnyes_parse(self):
        page = "globalData.push([2.2,22.2,'20251030',1983.000000,1983.000000,1983.000000,1983.000000,0,0,3809.4,1455.4,]) ;"
        old = F.get
        try:
            F.get = lambda u, h=None, timeout=30: page
            self.assertEqual(F.cnyes("BDI"), {"2025-10-30": 1983.0})
        finally:
            F.get = old


if __name__ == "__main__":
    unittest.main()
