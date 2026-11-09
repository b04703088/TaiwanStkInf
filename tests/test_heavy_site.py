import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import heavy_site as H  # noqa: E402


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)


PX = ["date", "market", "code", "name", "open", "high", "low", "close", "change", "volume", "value", "transactions"]
MG = ["date", "market", "code", "name", "fin_buy", "fin_sell", "fin_cash", "fin_prev", "fin_bal", "fin_limit"]
UL = ["date", "market", "code", "name", "ul_prev", "ul_new", "ul_sell", "ul_cash", "ul_swap", "ul_bal", "ul_limit"]


class HeavyTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "data"
            write(root / "config" / "heavy_groups.csv", ["code", "group"], [["2330", "晶圓代工"]])
            write(d / "etf" / "0050" / "20261106.csv", ["date", "etf", "code", "name", "shares", "weight"],
                  [["2026-11-06", "0050", "2330", "台積電", "1", "60"], ["2026-11-06", "0050", "2327", "國巨*", "1", "0.7"]])
            closes = {"2330": [100, 110, 90], "2327": [50, 40, 30]}
            fin = {"2330": [1000, 1200, 1500], "2327": [400, 300, 200]}
            ul = {"2330": [2000, 2000, 2100], "2327": [100, 150, 200]}
            for i, k in enumerate(["20261104", "20261105", "20261106"]):
                iso = f"{k[:4]}-{k[4:6]}-{k[6:]}"
                write(d / "2026" / f"{k}.csv", PX, [[iso, "TWSE", c, c, v[i], v[i] + 1, v[i], v[i], 0, 1, 1, 1] for c, v in closes.items()])
                write(d / "margin" / "2026" / f"{k}.csv", MG, [[iso, "TWSE", c, c, 0, 0, 0, 0, v[i], 10000] for c, v in fin.items()])
                write(d / "pledge" / "2026" / f"{k}.csv", UL, [[iso, "TWSE", c, c, 0, 0, 0, 0, 0, v[i], 10000] for c, v in ul.items()])
            old, H.PERIODS = H.PERIODS, (2,)
            try:
                p = H.build(d, root)
            finally:
                H.PERIODS = old
            self.assertEqual(p["date"], "2026-11-06")
            rows = {r[0]: dict(zip(p["cols"], r)) for r in p["rows"]}
            self.assertEqual(rows["2327"]["name"], "國巨")
            self.assertEqual(rows["2330"]["g"], "晶圓代工")
            self.assertEqual(rows["2327"]["g"], "其他")
            self.assertEqual(rows["2330"]["f"], 1500)
            self.assertEqual(rows["2330"]["fl"], 15.0)
            self.assertEqual(p["periods"], {"2": "2026-11-04"})
            ret, dd, f0, u0 = rows["2330"]["p2"]
            self.assertEqual((ret, f0, u0), (-10.0, 1000, 2000))
            self.assertAlmostEqual(dd, (90 / 111 - 1) * 100, 1)  # 區間最高價不含起算日


if __name__ == "__main__":
    unittest.main()
