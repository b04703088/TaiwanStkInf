import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_financials as F  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "financials"


class RevenueTest(unittest.TestCase):
    def test_parse(self):
        text = (FIX / "revenue_sii.html").read_bytes().decode("cp950")
        rows = F.parse_revenue(text, "202608", "上市")
        self.assertEqual([r["code"] for r in rows], ["1101", "2330"])  # 合計列略過
        tw = rows[0]
        self.assertEqual((tw["name"], tw["industry"], tw["revenue"], tw["mom_pct"], tw["yoy_pct"], tw["cum"], tw["note"]),
                         ("台泥", "水泥工業", 13515534.0, -1.66, 10.64, 98726969.0, ""))
        tsmc = rows[1]
        self.assertEqual((tsmc["industry"], tsmc["revenue"], tsmc["last_year"], tsmc["cum_yoy_pct"]),
                         ("半導體業", 514805337.0, 335771691.0, 39.26))
        self.assertEqual(tsmc["note"], "因先進製程產品需求增加所致。")


class QuarterTest(unittest.TestCase):
    def setUp(self):
        self.inc = F.parse_fin((FIX / "t163sb04_sii.html").read_text(encoding="utf-8"), F.IS_MAP)
        self.bal = F.parse_fin((FIX / "t163sb05_sii.html").read_text(encoding="utf-8"), F.BS_MAP)

    def test_income_general(self):
        r = self.inc["1101"]
        self.assertEqual(r["type"], "一般")
        self.assertEqual((r["revenue"], r["gross_profit"], r["operating_income"], r["pretax_income"], r["net_income"],
                          r["net_income_parent"], r["eps"]),
                         (70310678.0, 11240554.0, 3415898.0, 3071567.0, 1498464.0, 960722.0, 0.07))

    def test_income_bank_revenue_is_net_revenue(self):
        r = self.inc["2801"]
        self.assertEqual(r["type"], "銀行")
        self.assertEqual(r["revenue"], 12965050 + 9569125)
        self.assertNotIn("operating_income", r)  # 銀行格式沒有營業利益
        self.assertEqual((r["pretax_income"], r["net_income"], r["net_income_parent"], r["eps"]),
                         (10981262.0, 9129310.0, 9129310.0, 0.78))

    def test_income_financial_holding(self):
        r = self.inc["2880"]
        self.assertEqual(r["type"], "金控")
        self.assertEqual((r["revenue"], r["pretax_income"], r["net_income"], r["eps"]),
                         (32363526.0, 14803823.0, 11682511.0, 0.84))

    def test_income_insurance_ifrs17(self):
        head = ["公司代號", "公司名稱", "保險服務結果", "財務結果", "其他營業結果", "營業利益（損失）", "營業外收入及支出",
                "繼續營業單位稅前純益（純損）", "所得稅費用（利益）", "本期淨利（淨損）", "淨利（損）歸屬於母公司業主", "基本每股盈餘"]
        row = ["2816", "旺旺保", "930,279", "1,247,908", "-246,731", "1,931,456", "6,205", "1,937,661", "183,948",
               "1,753,713", "--", "7.84"]
        page = ("<table class='hasBorder'><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr><tr>"
                + "".join(f"<td>{v}</td>" for v in row) + "</tr></table>")
        r = F.parse_fin(page, F.IS_MAP)["2816"]
        self.assertEqual((r["type"], r["operating_income"], r["pretax_income"], r["net_income"], r["eps"]),
                         ("保險", 1931456.0, 1937661.0, 1753713.0, 7.84))
        self.assertNotIn("revenue", r)

    def test_balance(self):
        r = self.bal["1101"]
        self.assertEqual((r["current_assets"], r["total_assets"], r["total_liabilities"], r["capital"],
                          r["equity_parent"], r["equity"], r["bvps"]),
                         (166160771.0, 566872339.0, 289988360.0, 77511817.0, 220371152.0, 276883979.0, 28.5))
        fh = self.bal["2880"]  # 金控格式：資產總額／負債總額／權益總額、有空白表頭
        self.assertEqual((fh["total_assets"], fh["total_liabilities"], fh["equity_parent"], fh["equity"], fh["bvps"]),
                         (4186253927.0, 3971147365.0, 215104130.0, 215106562.0, 15.61))
        self.assertNotIn("current_assets", fh)

    def test_single_quarter_and_files(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(F, "OUT", Path(tmp)):
            q1 = [{"year": 2026, "season": 1, "market": "上市", "code": "1101", "name": "台泥", "type": "一般",
                   "revenue": 30.0, "net_income": 5.0, "eps": 0.03}]
            q2 = [{"year": 2026, "season": 2, "market": "上市", "code": "1101", "name": "台泥", "type": "一般",
                   "revenue": 70.0, "net_income": 4.0, "eps": 0.07},
                  {"year": 2026, "season": 2, "market": "上市", "code": "9999", "name": "新上市", "type": "一般",
                   "revenue": 10.0}]
            F.save_quarter(2026, 2, [dict(r) for r in q2])  # 先有 Q2（Q1 還沒抓）
            self.assertEqual(F._read(F.qpath(2026, 2))[0]["q_revenue"], "")
            F.save_quarter(2026, 1, [dict(r) for r in q1])  # 補上 Q1 → Q2 單季重算
            rows = {r["code"]: r for r in F._read(F.qpath(2026, 2))}
            self.assertEqual((rows["1101"]["q_revenue"], rows["1101"]["q_net_income"], rows["1101"]["q_eps"]),
                             ("40", "-1", "0.04"))
            self.assertEqual(rows["9999"]["q_revenue"], "")
            self.assertEqual(F._read(F.qpath(2026, 1))[0]["q_revenue"], "30")


class FillParentTest(unittest.TestCase):
    def test_individual_statement(self):
        r = F.fill_parent({"net_income": 5.0, "equity": 100.0, "net_income_parent": None, "equity_parent": None})
        self.assertEqual((r["net_income_parent"], r["equity_parent"]), (5.0, 100.0))
        r = F.fill_parent({"net_income": 5.0, "equity": 100.0, "net_income_parent": 4.0, "equity_parent": 90.0})
        self.assertEqual((r["net_income_parent"], r["equity_parent"]), (4.0, 90.0))


class PlanTest(unittest.TestCase):
    def test_quarter_windows(self):
        self.assertTrue(F.quarter_active(2026, 3, date(2026, 10, 13)))
        self.assertFalse(F.quarter_active(2026, 2, date(2026, 10, 13)))
        self.assertTrue(F.quarter_active(2025, 4, date(2026, 3, 31)))
        self.assertTrue(F.quarter_ended(2026, 3, date(2026, 10, 1)))
        self.assertFalse(F.quarter_ended(2026, 4, date(2026, 12, 31)))

    def test_plans(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(F, "OUT", Path(tmp)):
            active, missing = F.plan_quarters(date(2026, 10, 13), (2026, 1))
            self.assertEqual((active, missing), ([(2026, 3)], [(2026, 2), (2026, 1)]))
            recent, missing = F.plan_months(date(2026, 10, 13), (2026, 6))
            self.assertEqual(recent, [(2026, 9), (2026, 8)])
            self.assertEqual(missing, [(2026, 7), (2026, 6)])


if __name__ == "__main__":
    unittest.main()
