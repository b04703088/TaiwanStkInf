import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import adjust as A  # noqa: E402
import fetch_adjust as F  # noqa: E402

TWT49U = {"stat": "OK", "fields": ["資料日期", "股票代號", "股票名稱", "除權息前收盤價", "除權息參考價", "權值+息值", "權/息",
                                   "漲停價格", "跌停價格", "開盤競價基準", "減除股利參考價", "詳細資料"],
          "data": [["115年06月01日", "2612", "中航", "57.70", "55.50", "2.200000", "息", "61.00", "49.95", "55.50", "55.50", ""],
                   ["111年01月12日", "2406", "國碩", "28.15", "27.56", "0.583491", "權", "30.95", "24.85", "28.15", "28.15", ""],
                   ["115年06月02日", "9999", "缺價", "--", "10.00", "0", "息", "", "", "", "", ""]]}
EXDAILYQ = {"tables": [{"fields": ["除權息日期", "代號", "名稱", "除權息前收盤價", "除權息參考價", "權值", "息值", "權值+息值",
                                    "權/息", "漲停價", "跌停價", "開始交易基準價", "減除股利參考價", "現金股利", "每仟股無償配股"],
                        "data": [["115/06/01", "3709", "鑫聯大投控           ", "88.80", "86.35", "2.445568", "0", "2.445568", "除權",
                                  "97.6", "77.8", "88.8", "88.8", "0.00000000", "28.5"]]}], "stat": "ok"}
REVIVT = {"tables": [{"fields": ["恢復買賣日期", "股票代號", "名稱", "最後交易日之收盤價格", "減資恢復買賣開始日參考價格", "漲停價格",
                                  "跌停價格", "開始交易基準價", "除權參考價", "減資原因", "詳細資料"],
                      "data": [["1140113", "2740", "天蔥", "21.55", "39.18", "43.05", "35.30", "39.20", "0.00", "彌補虧損",
                                "<table><tr><th>每壹仟股換發新股票:</th><td>550.00000000&nbsp股</td></tr>"
                                "<tr><th>每股退還股款:</th><td>0.00000000&nbsp元/股</td></tr></table>"]]}]}
TWTCAU = {"stat": "OK", "fields": ["恢復買賣日期", "ETF代號", "名稱", "分割(反分割)", "停止買賣前收盤價格", "恢復買賣參考價"],
          "data": [["114/06/18", "0050", "元大台灣50", "分割", "188.65", "47.16"],
                   ["113/12/11", "00632R", "元大台灣50反1", "反分割", "3.28", "22.96"]]}
TWTB8U = {"stat": "OK", "fields": ["恢復買賣日期", "股票代號", "名稱", "停止買賣前收盤價格", "恢復買賣參考價"],
          "data": [["114/08/25", "2327", "國巨", "546.00", "136.50"]]}


PVCHG = {"tables": [{"fields": ["恢復買賣日期", "證券代號", "證券名稱", "最後交易日之收盤價格", "恢復買賣開始參考價", "漲停價格",
                                 "跌停價格", "開始交易基準價", "詳細資料"],
                     "data": [["1110905", "6548", "長科*           ", "90.60", "36.24", "39.85", "32.65", "36.25", ""]]}]}


class ParseTest(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(F.roc_date("115年06月01日"), "2026-06-01")
        self.assertEqual(F.roc_date("114/02/12"), "2025-02-12")
        self.assertEqual(F.roc_date("1140113"), "2025-01-13")
        self.assertEqual(F.roc_date("--"), "")

    def test_twse_exright(self):
        ev = F.parse_twse_exright(TWT49U)
        self.assertEqual(len(ev), 2)  # 缺前收盤的略過
        a, b = ev
        self.assertEqual((a["date"], a["market"], a["kind"], a["cash"], a["factor"]),
                         ("2026-06-01", "TWSE", "除息", "2.2", F.fmt(55.5 / 57.7, 8)))
        self.assertEqual((b["kind"], b["cash"]), ("除權", ""))

    def test_tpex_exright(self):
        (e,) = F.parse_tpex_exright(EXDAILYQ)
        self.assertEqual((e["date"], e["market"], e["name"], e["kind"], e["cash"], e["note"]),
                         ("2026-06-01", "TPEx", "鑫聯大投控", "除權", "", "每仟股配股 28.5 股"))

    def test_reduction(self):
        (e,) = F.parse_tpex_reduction(REVIVT)
        self.assertEqual((e["date"], e["kind"], e["prev_close"], e["ref_price"], e["note"], e["cash"]),
                         ("2025-01-13", "減資", "21.55", "39.18", "彌補虧損；每仟股換發 550 股", ""))

    def test_split_and_par(self):
        s, r = F.parse_twse_split(TWTCAU)
        self.assertEqual((s["kind"], s["note"]), ("分割", "1 單位分割為 4 單位"))
        self.assertEqual((r["kind"], r["note"]), ("反分割", "7 單位合併為 1 單位"))
        (p,) = F.parse_twse_par(TWTB8U)
        self.assertEqual((p["kind"], p["note"], p["factor"]), ("面額變更", "1 股換 4 股", "0.25"))

    def test_tpex_par(self):
        (e,) = F.parse_tpex_resume("面額變更", "pvChgRslt")(PVCHG)
        self.assertEqual((e["date"], e["market"], e["name"], e["kind"], e["note"], e["source"]),
                         ("2022-09-05", "TPEx", "長科*", "面額變更", "1 股換 2.5 股", "pvChgRslt"))

    def test_merge(self):
        old = [{"date": "2026-01-05", "code": "1", "kind": "除息", "source": "TWT49U", "market": "TWSE"},
               {"date": "2026-03-05", "code": "2", "kind": "除息", "source": "TWT49U", "market": "TWSE"},
               {"date": "2026-03-06", "code": "3", "kind": "減資", "source": "revivt", "market": "TPEx"}]
        new = [{"date": "2026-03-10", "code": "4", "kind": "除息", "source": "TWT49U", "market": "TWSE"}]
        got = F.merge(old, new, date(2026, 3, 1), date(2026, 3, 31), {"TWT49U"})
        # 區間外保留、區間內被重抓的來源以新資料為準、這次失敗的來源（revivt）保留舊的
        self.assertEqual([r["code"] for r in got], ["1", "3", "4"])


class AdjustTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "events.csv"
        rows = F.parse_twse_split(TWTCAU)[:1] + [
            F.event("2025-07-17", "TWSE", "0050", "元大台灣50", "除息", "50.00", "49.00", "TWT49U")]
        F.write_csv(path, rows)
        self.ev = A.load_events(path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_factor(self):
        split = 47.16 / 188.65
        self.assertAlmostEqual(A.factor_after(self.ev, "0050", "2025-06-17"), split * 0.98, places=6)
        self.assertAlmostEqual(A.factor_after(self.ev, "0050", "2025-06-18"), 0.98, places=6)  # 事件日當天已是新基準
        self.assertEqual(A.factor_after(self.ev, "0050", "2025-07-17"), 1.0)
        self.assertEqual(A.factor_after(self.ev, "2330", "2020-01-01"), 1.0)

    def test_adjust_rows(self):
        rows = A.adjust_rows(self.ev, [{"date": "2025-06-17", "code": "0050", "open": "", "high": "188.65",
                                        "low": "188.65", "close": "188.65", "change": "0", "volume": "1000"}])
        r = rows[0]
        self.assertEqual(r["adj_close"], f"{47.16 * 0.98:.4f}")
        self.assertEqual(r["adj_open"], "")
        self.assertEqual(r["adj_volume"], f"{1000 / (47.16 / 188.65 * 0.98):.0f}")


if __name__ == "__main__":
    unittest.main()
