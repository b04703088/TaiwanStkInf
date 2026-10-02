import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_cb as F  # noqa: E402
import cb_site  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "cb"


def notice(sn):
    return F.parse_notice((FIX / f"notice_{sn}.txt").read_text(encoding="utf-8"))


class NoticeTest(unittest.TestCase):
    def test_bookbuilding_notice(self):
        self.assertEqual(notice("115395"), {
            "series": 5, "issue_pct": "101.5", "total_units": 25000, "done_date": "2026-09-29",
            "price_base_date": "2026-10-01", "conv_price": "1656.0", "premium": "105.256",
            "pay_date": "2026-10-05", "list_expected": "2026-10-12"})

    def test_variants(self):
        a = notice("115386")  # 「即發行之轉換價格為每股新台幣46.4元」「上櫃日期預定為」
        self.assertEqual((a["series"], a["conv_price"], a["premium"], a["price_base_date"], a["pay_date"],
                          a["list_expected"]), (3, "46.4", "105.22", "2026-09-22", "2026-09-24", "2026-10-02"))
        b = notice("115003")  # 跨年：114 年 12 月詢圈、115 年 1 月繳款
        self.assertEqual((b["done_date"], b["price_base_date"], b["pay_date"], b["issue_pct"]),
                         ("2025-12-29", "2025-12-31", "2026-01-05", "105"))

    def test_auction_notice(self):
        c = notice("115391")
        self.assertEqual((c["issue_pct"], c["conv_price"], c["premium"], c["done_date"], c["price_base_date"],
                          c["pay_date"], c["list_expected"]),
                         ("100.7", "30.00", "114.29", "2026-09-23", "2026-09-14", "2026-09-29", "2026-10-06"))

    def test_cn_num(self):
        self.assertEqual([F.cn_num(x) for x in ("三", "十", "十二", "二十一", "7")], [3, 10, 12, 21, 7])


class ListTest(unittest.TestCase):
    def test_bookbuilding_list(self):
        rows = F.parse_bookbuilding(*F.parse_grid((FIX / "bookbuilding.html").read_text(encoding="utf-8")))
        r = {x["sn"]: x for x in rows}["115065"]
        self.assertEqual((r["company"], r["bb_start"], r["bb_end"], r["premium_lo"], r["premium_hi"], r["units"]),
                         ("東聯互動股份有限公司", "2026-10-02", "2026-10-05", "105.01", "110.00", 5000))

    def test_notice_list(self):
        rows = F.parse_notice_list(*F.parse_grid((FIX / "notice_list.html").read_text(encoding="utf-8")))
        self.assertEqual([r["sn"] for r in rows], ["115003", "115386", "115391", "115395"])  # 115001 是現增
        self.assertTrue(all(r["_btn"].endswith("imgbtnFileName") for r in rows))

    def test_issbd5_skips_private(self):
        data = json.loads((FIX / "issbd5.json").read_text(encoding="utf-8"))
        rows = F.parse_issbd5(data, "2026-01-01")
        self.assertNotIn("83019737", {r["code"] for r in rows})
        r = {x["code"]: x for x in rows}["8996"]
        self.assertEqual((r["series"], r["bond_code"], r["list_date"], r["conv_price"], r["underwriter"]),
                         (5, "89965", "2026-10-12", "1656", "富邦綜合證券"))


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.bb = F.parse_bookbuilding(*F.parse_grid((FIX / "bookbuilding.html").read_text(encoding="utf-8")))
        self.bb.append({"sn": "115060", "company": "高力熱處理工業股份有限公司", "lead": "富邦綜合證券股份有限公司",
                        "type": "無擔保轉換公司債", "units": 25000, "bb_units": 22500, "bb_start": "2026-09-25",
                        "bb_end": "2026-09-29", "premium_lo": "102.00", "premium_hi": "110.00"})
        nts = F.parse_notice_list(*F.parse_grid((FIX / "notice_list.html").read_text(encoding="utf-8")))
        self.nts = [{**n, **notice(n["sn"]), "parsed": "1"} for n in nts]
        self.issued = F.parse_issbd5(json.loads((FIX / "issbd5.json").read_text(encoding="utf-8")), "2025-01-01")
        cos = [{"code": "8996", "name": "高力熱處理工業股份有限公司", "abbr": "高力"},
               {"code": "6174", "name": "安碁科技股份有限公司", "abbr": "安碁"},
               {"code": "6464", "name": "東聯互動股份有限公司", "abbr": "東聯互動"}]
        self.cases = F.merge(self.bb, [], self.nts, self.issued, F.company_mapper(cos, self.issued))
        self.by = {c["id"]: c for c in self.cases}

    def test_links_all_sources(self):
        c = self.by["8996-5"]
        self.assertEqual((c["bb_sn"], c["nt_sn"], c["bond_code"], c["bb_start"], c["price_base_date"],
                          c["conv_price"], c["list_date"], c["method"]),
                         ("115060", "115395", "89965", "2026-09-25", "2026-10-01", "1656", "2026-10-12", "詢價圈購"))

    def test_pending_bookbuilding(self):
        c = next(c for c in self.cases if c["bb_sn"] == "115065")
        self.assertEqual((c["code"], c["nt_sn"], c["conv_price"], c["id"]), ("6464", "", "", "bb115065"))

    def test_notice_only_and_name_via_issuer(self):
        # 可寧衛 沒有在公司清單裡，但櫃買發行資料的簡稱可以對到
        c = self.by["8422-3"]
        self.assertEqual((c["method"], c["nt_sn"], c["bond_code"]), ("競價拍賣", "115391", "84223"))
        self.assertIn("6174-3", self.by)

    def test_site_payload(self):
        p = cb_site.build(self.cases)
        self.assertEqual(p["cols"], cb_site.COLS)
        self.assertEqual(len(p["rows"]), len(self.cases))


if __name__ == "__main__":
    unittest.main()
