import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import newhigh_site as N  # noqa: E402


def rows(closes, start=20240101):
    return [(start + i, c, c, c, c, 1000) for i, c in enumerate(closes)]


class NewHighSiteTest(unittest.TestCase):
    def test_scan_high_low_ath(self):
        # 300 天：中間一段 120，其餘 100；倒數第二天 99 是 52 週新低，最後一天 110 不是新高
        cl = [100] * 100 + [120] * 30 + [100] * 168 + [99, 110]
        r = rows(cl)
        days = [x[0] for x in r[-5:]]
        hi, lo, ath, info = N.scan(r, None, days)
        self.assertEqual(hi, [])
        self.assertAlmostEqual(info["dist"], -8.33)
        self.assertEqual(lo, [3])
        self.assertEqual(ath, [])
        # 最後一天拉到 130：52 週與 2022 年以來都創新高
        r = rows(cl[:-1] + [130])
        hi, lo, ath, info = N.scan(r, None, days)
        self.assertEqual(hi, [4])
        self.assertEqual(lo, [3])
        self.assertEqual(ath, [4])
        self.assertEqual(info["dist"], 0)
        self.assertEqual(info["vol"], 1000)

    def test_adjusted_by_events(self):
        # 第 290 天除權（因子 0.5）：原始價腰斬但還原後沒跌，之後漲回原始 60 → 還原後是新高
        cl = [100] * 290 + [50] * 9 + [60]
        r = rows(cl)
        ev = [[r[290][0], 0.5, "除權", "", None]]
        hi, lo, ath, _ = N.scan(r, ev, [r[-1][0]])
        self.assertEqual(hi, [0])
        self.assertEqual(lo, [])

    def test_build_groups(self):
        prices = {"1101": {"name": "A", "market": "TWSE", "rows": rows([10] * 259 + [11])},
                  "1102": {"name": "B", "market": "TPEx", "rows": rows([10] * 260)},
                  "0050": {"name": "ETF", "market": "TWSE", "rows": rows([10] * 259 + [11])}}
        days = [x[0] for x in prices["1101"]["rows"]]
        ind = {"nodes": [["水泥", "上游", "石灰", "", ""]], "stocks": {"1101": ["A", "水泥工業", [0]], "1102": ["B", "水泥工業", [0]]}}
        p = N.build(prices, days, {}, ind)
        self.assertEqual([r[0] for r in p["rows"]], ["1101", "1102"])
        self.assertEqual(p["breadth"]["hi"][-1], 1)
        self.assertEqual(p["groups"]["off"], [["水泥工業", "官方產業別", [0, 1]]])


if __name__ == "__main__":
    unittest.main()
