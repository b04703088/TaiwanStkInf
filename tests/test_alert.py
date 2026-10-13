import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_alert as F  # noqa: E402
import alert_site as S  # noqa: E402

TWSE_PUNISH = {"fields": ["編號", "公布日期", "證券代號", "證券名稱", "累計", "處置條件", "處置起迄時間", "處置措施", "處置內容", "備註"],
               "data": [[2, "115/10/07", "1709", "和益", 1, "最近十個營業日已有六次", "115/10/08～115/10/15", "第一次處置",
                         "１處置原因：…\n３處置措施：\nａ以人工管制之撮合終端機執行撮合作業（約每二分鐘撮合一次）。\n", "備註"]]}
TPEX_DISP = {"fields": ["編號", "公布日期", "證券代號", "證券名稱", "累計", "處置起訖時間", "處置原因", "處置措施", "處置內容", "收盤價", "本益比", " "],
             "data": [[1, "115/10/08", "6708", "天擎(../../mainboard/listed/company-detail.html?code=6708)", 3, "115/10/12~115/10/16",
                       "連續3個營業日", "再次處置", "* 處置措施：<br>(1)以人工管制之撮合終端機執行撮合作業(約每25分鐘撮合一次)；", "69.20", "223.23", ""]]}
TWSE_NOTICE = {"fields": ["編號", "證券代號", "證券名稱", "累計次數", "注意交易資訊", "日期", "收盤價", "本益比"],
               "data": [[11, "1325", "恆大", "1", "最近六個營業日平均成交量…放大為 21.92倍<font color='#FF0000'>﹝第九款﹞</font>。", "115.10.12", "31.00", "-----"]]}
TPEX_ATT = {"fields": ["編號", "證券代號", "證券名稱", "累計", "注意交易資訊", "公告日期", "收盤價", "本益比", "link"],
            "data": [[1, "3265", "台星科", 15, "漲幅達36.29%(第一款)<br>當日週轉率達6.34%(第四款)<br>…(第十三款)", "115/10/12", "262.00", "36.75", "x"]]}


class ParseTest(unittest.TestCase):
    def test_dates(self):
        for s in ("115/10/07", "115.10.07", "1151007", "115年10月7日", "2026/10/07", "20261007"):
            self.assertEqual(F.iso(s), "2026-10-07", s)
        self.assertEqual(F.period("115/10/13～115/10/19"), ("2026-10-13", "2026-10-19"))
        self.assertEqual(F.period("1151013~1151019"), ("2026-10-13", "2026-10-19"))

    def test_disposal(self):
        r = F.parse_disposal(TWSE_PUNISH["fields"], TWSE_PUNISH["data"], "上市")[0]
        self.assertEqual((r["ann_date"], r["code"], r["name"], r["start"], r["end"], r["reason"], r["measure"], r["interval"]),
                         ("2026-10-07", "1709", "和益", "2026-10-08", "2026-10-15", "最近十個營業日已有六次", "第一次處置", "2"))
        r = F.parse_disposal(TPEX_DISP["fields"], TPEX_DISP["data"], "上櫃")[0]
        self.assertEqual((r["name"], r["start"], r["end"], r["reason"], r["measure"], r["interval"]),
                         ("天擎", "2026-10-12", "2026-10-16", "連續3個營業日", "再次處置", "25"))

    def test_attention(self):
        r = F.parse_attention(TWSE_NOTICE["fields"], TWSE_NOTICE["data"], "上市")[0]
        self.assertEqual((r["date"], r["code"], r["clauses"], r["close"], r["pe"]), ("2026-10-12", "1325", "9", "31.00", ""))
        self.assertNotIn("<font", r["info"])
        r = F.parse_attention(TPEX_ATT["fields"], TPEX_ATT["data"], "上櫃")[0]
        self.assertEqual((r["date"], r["clauses"], r["pe"]), ("2026-10-12", "1;4;13", "36.75"))

    def test_near(self):
        r = F.parse_near_twse([{"Code": "2466", "Name": "冠西電", "RecentlyMetAttentionSecuritiesCriteria": "115年10月8日至115年10月12日連續二次"}])[0]
        self.assertEqual((r["date"], r["market"], r["code"]), ("2026-10-12", "上市", "2466"))
        r = F.parse_near_tpex([{"Date": "20261012", "SecuritiesCompanyCode": "3265", "CompanyName": "台星科",
                                "AccumulationSituation": "115年10月08日至115年10月12日連續二次"}])[0]
        self.assertEqual((r["date"], r["market"], r["name"]), ("2026-10-12", "上櫃", "台星科"))

    def test_merge(self):
        old = [{"market": "上市", "code": "1", "date": "2026-10-01", "info": "舊"}]
        new = [{"market": "上市", "code": "1", "date": "2026-10-01", "info": "新"},
               {"market": "上市", "code": "2", "date": "", "info": "沒日期不收"}]
        self.assertEqual([r["info"] for r in F.merge(old, new, F.KEYS["attention"])], ["新"])


class SiteTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "alert"
            disp = F.parse_disposal(TWSE_PUNISH["fields"], TWSE_PUNISH["data"], "上市") + \
                F.parse_disposal(TPEX_DISP["fields"], TPEX_DISP["data"], "上櫃")
            att = F.parse_attention(TWSE_NOTICE["fields"], TWSE_NOTICE["data"], "上市") + \
                F.parse_attention(TPEX_ATT["fields"], TPEX_ATT["data"], "上櫃") + \
                [{"market": "上市", "date": "2026-10-09", "code": "071804", "name": "達發統一66購01", "info": "x", "clauses": "1"}]
            near = F.parse_near_twse([{"Code": "2466", "Name": "冠西電", "RecentlyMetAttentionSecuritiesCriteria": "115年10月12日連續二次"}])
            F.save(out, disp, att, near)
            p = S.write_alert(d, Path(d) / "site" / "alert.json")
            self.assertEqual(json.loads((Path(d) / "site" / "alert.json").read_text(encoding="utf-8")), p)
            self.assertEqual(p["generated"], "2026-10-12")
            self.assertEqual(p["days"], ["2026-10-09", "2026-10-12"])  # 權證那天也算交易日
            att = [dict(zip(p["att"]["cols"], r)) for r in p["att"]["rows"]]
            self.assertEqual(sorted(a["code"] for a in att), ["1325", "3265"])  # 權證不列
            disp = [dict(zip(p["disp"]["cols"], r)) for r in p["disp"]["rows"]]
            self.assertEqual([x["code"] for x in disp], ["6708", "1709"])  # 新到舊
            self.assertEqual(disp[0]["interval"], 25)
            self.assertEqual(p["near"]["date"], "2026-10-12")
            self.assertEqual(p["names"]["6708"], "天擎")

    def test_is_stock(self):
        for c in ("2330", "0050", "00878", "00631L", "9103"):
            self.assertTrue(S.is_stock(c), c)
        for c in ("071804", "80212", "03356P"):
            self.assertFalse(S.is_stock(c), c)


if __name__ == "__main__":
    unittest.main()
