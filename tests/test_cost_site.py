import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import cost_site as C  # noqa: E402


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)


PX = ["date", "market", "code", "name", "open", "high", "low", "close", "change", "volume", "value", "transactions"]


class BookTest(unittest.TestCase):
    def test_move_buy_sell(self):
        b = C.Book(1000, 100)          # 起始部位 1000 股 @100
        b.move(2000, 120)              # 加碼 1000 @120 → 均價 110
        self.assertAlmostEqual(b.avg, 110)
        self.assertEqual(b.buy_sh, 1000)
        b.move(1000, 90)               # 減碼不改均價，起始部位按比例減半
        self.assertAlmostEqual(b.avg, 110)
        self.assertAlmostEqual(b.base, 500)

    def test_flow(self):
        b = C.Book(10, 50, base=False)
        b.flow(4, 6, 60)               # 償還 4 → 剩 6 @50，新增 6 @60 → 均價 55
        self.assertEqual(b.sh, 12)
        self.assertAlmostEqual(b.avg, 55)


class BuildTest(unittest.TestCase):
    def test_etf_and_margin(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            # 行情：VWAP = value / volume
            write(d / "2026" / "20261001.csv", PX, [["2026-10-01", "TWSE", "2330", "台積電", 0, 0, 0, 100, 0, 1000, 100000, 1]])
            write(d / "2026" / "20261002.csv", PX, [["2026-10-02", "TWSE", "2330", "台積電", 0, 0, 0, 112, 0, 1000, 110000, 1]])
            write(d / "2026" / "20261005.csv", PX, [["2026-10-05", "TWSE", "2330", "台積電", 0, 0, 0, 125, 0, 3000, 390000, 1]])
            write(d / "etf" / "etf_list.csv", ["etf", "name", "issuer", "issuer_name", "kind"],
                  [["00981A", "主動統一台股增長", "president", "統一", "active"], ["0050", "元大台灣50", "yuanta", "元大", "passive"]])
            H = ["date", "etf", "code", "name", "shares", "weight"]
            write(d / "etf" / "00981A" / "20261001.csv", H, [["2026-10-01", "00981A", "2330", "台積電", 1000, 10], ["2026-10-01", "00981A", "NVDA", "NVIDIA", 5, 1]])
            # 隔一天沒公布：10/02、10/05 合併 VWAP = (110000+390000)/(1000+3000) = 125
            write(d / "etf" / "00981A" / "20261005.csv", H, [["2026-10-05", "00981A", "2330", "台積電", 2000, 12]])
            MH = ["date", "market", "code", "name", "fin_buy", "fin_sell", "fin_cash", "fin_prev", "fin_bal", "fin_limit",
                  "sht_buy", "sht_sell", "sht_cash", "sht_prev", "sht_bal", "sht_limit", "offset", "note"]
            write(d / "margin" / "2026" / "20261001.csv", MH, [["2026-10-01", "TWSE", "2330", "台積電", 0, 0, 0, 0, 10] + [0] * 9])
            write(d / "margin" / "2026" / "20261002.csv", MH, [["2026-10-02", "TWSE", "2330", "台積電", 10, 0, 0, 10, 20] + [0] * 9])
            p = C.build(d)
            agg = dict(zip(p["etf"]["agg_cols"], p["etf"]["agg"][0]))
            self.assertEqual(agg["code"], "2330")
            self.assertAlmostEqual(agg["cost"], (1000 * 100 + 1000 * 125) / 2000)
            self.assertEqual(agg["base"], 50)
            self.assertEqual(len(p["etf"]["rows"]), 1)   # 海外股略過
            m = dict(zip(p["margin"]["cols"], p["margin"]["rows"][0]))
            self.assertAlmostEqual(m["cost"], 105)       # 10 張 @100（起始收盤）+ 10 張 @110（VWAP）
            self.assertAlmostEqual(m["call"], round(105 * 0.6 * 1.3, 2))
            self.assertEqual(m["ratio"], round(112 / (105 * 0.6) * 100))


if __name__ == "__main__":
    unittest.main()
