import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_margin as F  # noqa: E402
import margin_site  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "margin"
D = date(2026, 10, 16)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class ParseTest(unittest.TestCase):
    def test_twse(self):
        rows, s = F.parse_twse(load("twse.json"), D)
        self.assertEqual(len(rows), 2)
        r = rows[1]
        self.assertEqual((r["code"], r["fin_buy"], r["fin_sell"], r["fin_cash"], r["fin_prev"], r["fin_bal"], r["fin_limit"]),
                         ("9958", "103", "21", "0", "8579", "8661", "66724"))
        self.assertEqual((r["sht_buy"], r["sht_sell"], r["sht_bal"]), ("2", "99", "168"))
        self.assertEqual(s, {"date": "2026-10-16", "market": "TWSE", "fin_lots": "9538664",
                             "fin_amount": "645594048000", "sht_lots": "233602"})

    def test_tpex(self):
        rows, s = F.parse_tpex(load("tpex.json"), D)
        r = rows[0]
        self.assertEqual((r["market"], r["code"], r["fin_prev"], r["fin_buy"], r["fin_sell"], r["fin_bal"], r["fin_limit"]),
                         ("TPEx", "00411A", "14118", "413", "244", "14287", "113144"))
        self.assertEqual((r["sht_sell"], r["sht_buy"], r["sht_bal"], r["offset"]), ("90", "10", "90", "29"))
        self.assertEqual(s["fin_amount"], "218250119000")
        self.assertEqual(s["fin_lots"], "2364632")

    def test_pledge(self):
        rows = F.parse_pledge(load("twta1u.json"), D)
        r = rows[0]
        self.assertEqual((r["market"], r["code"], r["ul_prev"], r["ul_new"], r["ul_sell"], r["ul_cash"], r["ul_swap"],
                          r["ul_bal"], r["ul_limit"], r["sf_bal"], r["bl_bal"]),
                         ("TWSE", "2330", "122760", "657", "47", "15", "184", "123171", "2593237", "18461", "29"))
        self.assertEqual(rows[1]["market"], "TPEx")
        self.assertEqual(F.parse_pledge({"stat": "很抱歉，沒有符合條件的資料"}, D), [])

    def test_empty(self):
        self.assertEqual(F.parse_twse({"stat": "很抱歉，沒有符合條件的資料"}, D), ([], None))
        self.assertEqual(F.parse_tpex({"stat": "ok", "tables": [{"data": []}]}, D), ([], None))


def write(p, cols, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class SiteTest(unittest.TestCase):
    def test_build(self):
        # 三天：第 2 天融資買進 100 張 @ 120，第 3 天股價跌到 90、融資被砍 300 張
        days = [("2026-10-14", 100, 1000, 0, 0, 0), ("2026-10-15", 120, 1100, 100, 0, 0),
                ("2026-10-16", 90, 800, 0, 250, 50)]
        with tempfile.TemporaryDirectory() as tmp:
            dd = Path(tmp)
            for d, px, bal, buy, sell, cash in days:
                ymd = d.replace("-", "")
                write(dd / "margin" / d[:4] / f"{ymd}.csv", F.COLUMNS,
                      [{"date": d, "market": "TWSE", "code": "1234", "name": "測試", "fin_buy": buy, "fin_sell": sell,
                        "fin_cash": cash, "fin_bal": bal, "fin_limit": 10000, "sht_bal": 40}])
                write(dd / d[:4] / f"{ymd}.csv", ["date", "market", "code", "close"],
                      [{"date": d, "market": "TWSE", "code": "1234", "close": px}])
            for d, ul in (("2026-10-15", 500), ("2026-10-16", 450)):
                write(dd / "pledge" / d[:4] / (d.replace("-", "") + ".csv"), F.PLEDGE_COLUMNS,
                      [{"date": d, "market": "TWSE", "code": "1234", "ul_bal": ul, "ul_limit": 3000, "sf_bal": 7}])
            write(dd / "margin" / "summary.csv", F.SUMMARY_COLS,
                  [{"date": d, "market": "TWSE", "fin_lots": bal, "fin_amount": bal * 1000 * 60} for d, _, bal, *_ in days])
            out = margin_site.build(dd)
        st = dict(zip(margin_site.STOCK_COLS, out["stocks"]["rows"][0]))
        cost = (1000 * 100 + 100 * 120) / 1100
        self.assertAlmostEqual(st["cost"], round(cost, 2))
        self.assertEqual(st["ratio"], round(90 / (cost * 0.6) * 100))
        self.assertEqual((st["f1"], st["r1"], st["use"], st["ss_ratio"]), (-300, -25.0, 8.0, 5.0))
        self.assertEqual((st["ul"], st["ul1"], st["ul5"], st["ul_val"], st["ul_use"], st["sf"]),
                         (450, -50, None, 450 * 1000 * 90, 15.0, 7))
        self.assertEqual([x[5] for x in out["series"]["1234"]], [None, 500, 450])
        m = out["market"]["rows"]
        self.assertEqual(m[-1][margin_site.MARKET_COLS.index("twse_ratio")], 150.0)  # 90 / 60
        self.assertEqual(m[-1][margin_site.MARKET_COLS.index("n_down")], 1)
        self.assertEqual(m[-1][margin_site.MARKET_COLS.index("ul_lots")], 450)
        self.assertIsNone(m[0][margin_site.MARKET_COLS.index("ul_lots")])
        self.assertEqual(len(out["series"]["1234"]), 3)


    def test_deleverage(self):
        # 25 天：張數緩升到第 23 天 1022 → 最後兩天 950、902（連 2 天大減、離高點 -11.7%），
        # 00631L 融資與單位數最後 5 天都減少，主動式 ETF 融資一直增加
        n = 25
        lots = [1000 + i for i in range(23)] + [950, 902]
        with tempfile.TemporaryDirectory() as tmp:
            dd = Path(tmp)
            dates = [f"2026-09-{i + 1:02d}" for i in range(n)]
            for i, d in enumerate(dates):
                ymd = d.replace("-", "")
                write(dd / "margin" / d[:4] / f"{ymd}.csv", F.COLUMNS, [
                    {"date": d, "market": "TWSE", "code": "1234", "name": "測試", "fin_bal": lots[i]},
                    {"date": d, "market": "TWSE", "code": "00631L", "name": "正2", "fin_bal": 500 - max(0, i - 19) * 10},
                    {"date": d, "market": "TWSE", "code": "00980A", "name": "主動", "fin_bal": 100 + i}])
                write(dd / d[:4] / f"{ymd}.csv", ["date", "market", "code", "close"],
                      [{"date": d, "market": "TWSE", "code": c, "close": 100} for c in ("1234", "00631L", "00980A")])
                write(dd / "etf" / "aum" / f"{ymd}.csv", ["date", "etf", "units", "flow"],
                      [{"date": d, "etf": "00631L", "units": 1000 - max(0, i - 19) * 5, "flow": -5e8 if i > 19 else 0}])
            write(dd / "margin" / "summary.csv", F.SUMMARY_COLS,
                  [{"date": d, "market": "TWSE", "fin_lots": lots[i],
                    "fin_amount": 1} for i, d in enumerate(dates)])
            out = margin_site.deleverage_from_disk(dd)
        self.assertEqual(out["market"]["peak_date"], "2026-09-23")
        hit = {c["key"]: c["hit"] for c in out["checks"]}
        self.assertEqual(hit, {"dd": True, "drop2": True, "ratio": False, "lev": True, "active": False})
        self.assertEqual((out["level"], out["label"]), (2, "去槓桿進行中"))
        e = out["etfs"][0]
        self.assertEqual((e["code"], e["fin"], e["flow5"]), ("00631L", 450, -25.0))
        self.assertEqual(out["active"]["fin"], 124)


if __name__ == "__main__":
    unittest.main()
