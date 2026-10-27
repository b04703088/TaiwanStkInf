import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_insider as F  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


class Irb110Test(unittest.TestCase):
    def test_parse(self):
        rows = F.parse_irb110((FIX / "irb110_head.htm").read_bytes().decode("cp950", errors="replace"))
        self.assertGreater(len(rows), 5)
        r = rows[0]
        self.assertEqual((r["code"], r["company"]), ("1101", "臺灣水泥股份有限"))
        self.assertEqual((r["issued"], r["ds_add"], r["ds_sub"], r["ds_held"]), (7723181742, 0, 0, 637628625))
        self.assertEqual((r["ds_pct"], r["mgr_held"], r["major_held"]), (8.25, 15335763, 0))

    def test_parse_irb130(self):
        page = ("<TR><TD>公 司 名 稱</TD><TD>x</TD></TR>"
                "<TR><TD>1110東南水泥股份有限</TD><TD> 186,281,467</TD><TD> 0</TD><TD> 1,000</TD><TD> 40,000,000</TD>"
                "<TD> 21.47</TD><TD> 2,163</TD><TD> 80,496,816</TD><TD> 40,000,000</TD><TD> 49.69</TD></TR>")
        rows = F.parse_irb130(page)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["code"], r["ds_padd"], r["ds_psub"], r["ds_pledged"], r["ds_ppct"]), ("1110", 0, 1000, 40000000, 21.47))
        self.assertEqual((r["major_held"], r["mm_pledged"], r["mm_ppct"]), (80496816, 40000000, 49.69))

    def test_ym_add(self):
        self.assertEqual(F.ym_add((2026, 1), -1), (2025, 12))
        self.assertEqual(F.ym_add((2026, 11), 3), (2027, 2))


class Query6Test(unittest.TestCase):
    def test_tsmc_aug(self):
        res = json.loads((FIX / "query6_1_2330_11508.json").read_text(encoding="utf-8"))["result"]
        rows = F.parse_query6(res, 2026, 8, "sii", "2330", "台積電")
        by = {r["name"]: r for r in rows}
        # 曾繁城 8 月以「其他原因」轉 500 萬股給配偶（贈與），不是在市場賣
        z = by["曾繁城"]
        self.assertEqual((z["sell_mkt"], z["sell_other"], z["held_prev"], z["held_now"]), (0, 5000000, 29472675, 24472675))
        sp = by["曾繁城(配偶/子女)"]
        self.assertEqual((sp["buy_other"], sp["buy_mkt"]), (5000000, 0))
        self.assertEqual(z["month"], "2026-08")
        # 沒有變動的人不列
        self.assertNotIn("林全", by)
        # 同一人多個身分只留一列
        self.assertEqual(len([r for r in rows if r["name"] == z["name"]]), 1)
        self.assertTrue(all("pledge_add" in r and "pledge_sub" in r for r in rows))

    def test_pledge_only_row_kept(self):
        res = json.loads((FIX / "query6_1_2330_11508.json").read_text(encoding="utf-8"))["result"]
        row = list(res["data"][0])
        row[F.I_PLEDGE_ADD], row[F.I_PLEDGE] = "500,000", "2,100,000"
        rows = F.parse_query6({**res, "data": [row]}, 2026, 8, "sii", "2330", "台積電")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["pledge_add"], rows[0]["pledge_sub"], rows[0]["pledged"]), (500000, 0, 2100000))

    def test_spouse_mirror_marked(self):
        base = {"code": "1", "buy_other": 0, "sell_other": 0}
        rows = [{**base, "name": "張三", "buy_mkt": 170, "sell_mkt": 0},
                {**base, "name": "張三(配偶/子女)", "buy_mkt": 137, "sell_mkt": 0},
                {**base, "name": "李四", "buy_mkt": 137, "sell_mkt": 0},
                {**base, "name": "李四(配偶/子女)", "buy_mkt": 170, "sell_mkt": 0},
                {**base, "name": "王五(配偶/子女)", "buy_mkt": 5, "sell_mkt": 0}]
        F.mark_dups(rows)
        self.assertEqual([r["dup"] for r in rows], ["", "李四", "", "張三", ""])

    def test_column_check(self):
        with self.assertRaises(F.C.AdapterError):
            F.parse_query6({"titles": [{"main": "x"}] * 24, "data": []}, 2026, 8, "sii", "1", "x")


class TransferTest(unittest.TestCase):
    def test_both_markets(self):
        twse = json.loads((FIX / "t187ap12_L.json").read_text(encoding="utf-8"))
        tpex = json.loads((FIX / "mopsfin_t187ap12_O.json").read_text(encoding="utf-8"))
        a = F.norm_transfer(twse[0], "sii")
        b = F.norm_transfer(tpex[0], "otc")
        for r in (a, b):
            self.assertRegex(r["date"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertTrue(r["code"] and r["name"] and r["method"])
            self.assertGreater(r["held"], 0)

    def test_append_dedup(self):
        twse = json.loads((FIX / "t187ap12_L.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            old_out, old_http = F.OUT, F.C.http
            F.OUT = Path(d)
            F.C.http = lambda url, **k: twse if "twse" in url else []
            try:
                F.fetch_transfers()
                F.fetch_transfers()
            finally:
                F.OUT, F.C.http = old_out, old_http
            files = list((Path(d) / "transfer").glob("*.csv"))
            with files[0].open(encoding="utf-8") as fp:
                self.assertEqual(len(list(csv.DictReader(fp))), len(twse))


class MonthResumeTest(unittest.TestCase):
    def test_deadline_then_resume(self):
        res = json.loads((FIX / "query6_1_2330_11508.json").read_text(encoding="utf-8"))["result"]
        base = {"company": "x", "issued": 1, "ds_sub": 0, "ds_held": 1, "ds_pct": 1.0, "mgr_held": 0, "major_held": 0}
        cur = [{"code": c, **base, "ds_add": 1} for c in ("2330", "2331", "2332")]
        calls = []
        olds = (F.OUT, F.irb110, F.irb130, F.mops, F.DELAY)
        with tempfile.TemporaryDirectory() as d:
            F.OUT, F.DELAY = Path(d), 0
            F.irb110 = lambda y, m, mkt: cur if mkt == "sii" else []
            F.irb130 = lambda y, m, mkt: []
            F.mops = lambda api, body: calls.append(body["companyId"]) or res
            try:
                self.assertFalse(F.fetch_month(2026, 8, deadline=1))      # 時間已到：一家都不查，存進度
                self.assertEqual(calls, [])
                self.assertTrue(F.fetch_month(2026, 8))
                self.assertEqual(calls, ["2330", "2331", "2332"])
                out = Path(d) / "trades" / "202608.csv"
                self.assertTrue(out.exists())
                self.assertFalse(out.with_suffix(".part.csv").exists())
                self.assertTrue(F.fetch_month(2026, 8))                   # 已完成：不再查
                self.assertEqual(len(calls), 3)
            finally:
                F.OUT, F.irb110, F.irb130, F.mops, F.DELAY = olds


if __name__ == "__main__":
    unittest.main()
