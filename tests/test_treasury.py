import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_treasury as F  # noqa: E402
import treasury_site  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "treasury"


def programs():
    return F.parse_programs((FIX / "t35sc09.html").read_text(encoding="utf-8"), "sii")


class ProgramsTest(unittest.TestCase):
    def test_parse(self):
        p = programs()
        self.assertEqual([x["code"] for x in p], ["1101", "1103", "3303"])  # 「累計」列略過
        a = p[0]
        self.assertEqual((a["board_date"], a["purpose"], a["cap_amount"], a["plan_shares"], a["price_lo"], a["price_hi"],
                          a["start"], a["end"], a["done"]),
                         ("2025-06-30", "3", "126554019000", "28000000", "17.85", "41.50",
                          "2025-08-04", "2025-08-29", "Y"))
        self.assertEqual((a["bought_shares"], a["cancelled_shares"], a["exec_pct"], a["bought_amount"], a["avg_price"],
                          a["issued_pct"], a["reason"]),
                         ("28000000", "28000000", "100.00", "656204639", "23.44", "0.36", ""))
        b = p[1]
        self.assertEqual((b["bought_shares"], b["cancelled_shares"], b["exec_pct"]), ("1574000", "", "44.97"))
        self.assertIn("未執行完畢", b["reason"])
        c = p[2]  # 執行中：結果欄空白
        self.assertEqual((c["bought_shares"], c["avg_price"], c["done"], c["end"]), ("", "", "N", "2026-12-06"))

    def test_merge_keeps_old(self):
        old = [{**programs()[1], "name": "舊名"}, {**programs()[0], "board_date": "2020-01-01"}]
        m = F.merge(old, programs())
        self.assertEqual(len(m), 4)
        self.assertEqual([x["name"] for x in m if x["code"] == "1103"], ["嘉泥"])
        self.assertEqual(m[0]["code"], "3303")  # 決議日新到舊

    def test_active(self):
        act = F.active(programs(), date(2026, 10, 13))
        self.assertEqual([x["code"] for x in act], ["3303"])

    def test_roc(self):
        self.assertEqual(F.roc_date("115/08/05"), "2026-08-05")
        self.assertEqual(F.roc_date("1150805"), "2026-08-05")
        self.assertEqual(F.roc_date("----"), "")
        self.assertEqual(F.roc_param(date(2026, 8, 5)), "1150805")


class ProgressTest(unittest.TestCase):
    def test_parse_and_period(self):
        prog = programs()[2]
        rows = F.parse_progress((FIX / "t35sb01.html").read_text(encoding="utf-8"), "otc", "3303", prog["board_date"])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["buy_date"], rows[0]["shares"], rows[0]["amount"], rows[0]["held_pct"], rows[0]["note"]),
                         ("2026-10-20", "1000000", "22000000", "2.62", ""))
        self.assertEqual([F.in_period(r, prog) for r in rows], [True, False])  # 107 年的舊申報不算這次


class AnnounceTest(unittest.TestCase):
    PROG = {"market": "sii", "code": "1437", "board_date": "2026-10-17"}

    def test_notice_filter(self):
        yes = ["公告本公司董事會決議買回庫藏股", "公告董事會決議買回本公司股份", "公告本公司董事會決議第十七次買回庫藏股事宜",
               "本公司董事會決議通過買回公司股份"]
        no = ["公告本公司買回股份金額達新台幣三億元以上", "公告本公司買回庫藏股執行完畢", "公告本公司買回庫藏股期間屆滿執行情形",
              "公告本公司董事會決議註銷庫藏股暨訂定減資基準日", "公告本公司庫藏股買回數量達已發行股份總數百分之二",
              "代子公司Winking Studios Limited公告庫藏股執行情形", "公告本公司董事會決議授權董事長訂定庫藏股轉讓員工認股基準日"]
        self.assertTrue(all(F.is_buyback_notice(x) for x in yes))
        self.assertFalse(any(F.is_buyback_notice(x) for x in no))

    def test_fill(self):
        calls = []
        day = {"2026-10-17": [], "2026-10-18": [], "2026-10-19": [
            {"date": "2026-10-19", "time": "16:54:01", "code": "1437", "subject": "公告本公司董事會決議第十七次買回庫藏股事宜"},
            {"date": "2026-10-19", "time": "08:10:00", "code": "1437", "subject": "(更正)公告本公司董事會決議買回庫藏股"},
            {"date": "2026-10-19", "time": "10:00:00", "code": "9999", "subject": "公告本公司董事會決議買回庫藏股"}]}

        def fetch(d):
            calls.append(d.isoformat())
            return day.get(d.isoformat(), [])
        orig = F._local_news
        F._local_news = lambda: ({}, {"2026-10-18"})
        try:
            ann, err = F.fill_announce([self.PROG], [], date(2026, 11, 8), 60, fetch)
            self.assertEqual(calls, ["2026-10-17", "2026-10-19"])  # 本地已抓過的日子不查、找到就停
            self.assertEqual((ann[0]["ann_date"], ann[0]["ann_time"]), ("2026-10-19", "16:54"))  # 更正公告排後面
            # 窗內都查過還沒有 → 記「-」，下次不再查
            day["2026-10-19"] = []
            ann, _ = F.fill_announce([self.PROG], [], date(2026, 11, 8), 60, fetch)
            self.assertEqual((ann[0]["ann_date"], ann[0]["subject"]), ("", "-"))
            calls.clear()
            F.fill_announce([self.PROG], ann, date(2026, 11, 8), 60, fetch)
            self.assertEqual(calls, [])
            # 窗還沒過完（今天 10/18）不記
            ann, _ = F.fill_announce([self.PROG], [], date(2026, 10, 18), 60, fetch)
            self.assertEqual(ann, [])
        finally:
            F._local_news = orig

    def test_session(self):
        td = {"2026-11-05", "2026-11-06"}
        S = treasury_site.session
        self.assertEqual([S("2026-11-06", "08:30", td), S("2026-11-06", "13:30", td), S("2026-11-06", "13:31", td),
                          S("2026-11-07", "10:00", td), S("2026-11-09", "17:00", td), S("2026-11-04", "10:00", td)],
                         ["盤前", "盤中", "盤後", "休市", "盤後", "休市"])


class SiteTest(unittest.TestCase):
    def test_build(self):
        p = programs()
        p[2]["market"] = "otc"
        progress = [{"market": "otc", "code": "3303", "board_date": "2026-10-06", "seq": "1", "report_date": "2026-10-20",
                     "buy_date": "2026-10-20", "shares": "1000000", "amount": "22000000", "avg_price": "22",
                     "held_shares": "", "held_pct": "2.62", "note": ""},
                    {"market": "otc", "code": "3303", "board_date": "2026-10-06", "seq": "2", "report_date": "2026-11-02",
                     "buy_date": "2026-11-01", "shares": "500000", "amount": "12000000", "avg_price": "24",
                     "held_shares": "", "held_pct": "3.1", "note": ""}]
        d = treasury_site.build(p, progress, "2026-10-13 18:00")
        rows = [dict(zip(d["cols"], r)) for r in d["rows"]]
        self.assertEqual([r["code"] for r in rows], ["3303", "1101", "1103"])
        a = rows[0]
        self.assertEqual((a["prog_shares"], a["prog_amount"], a["prog_date"], a["prog_held_pct"]),
                         (1500000, 34000000, "2026-11-01", 3.1))
        self.assertEqual((rows[1]["plan_shares"], rows[1]["price_lo"], rows[1]["prog_shares"]), (28000000, 17.85, None))
        ann = [{"market": "otc", "code": "3303", "board_date": "2026-10-06", "ann_date": "2026-10-06", "ann_time": "13:43",
                "subject": "x"}]
        rows = [dict(zip(d["cols"], r)) for r in treasury_site.build(p, progress, None, announce=ann, tdays={"2026-10-06"})["rows"]]
        self.assertEqual((rows[0]["ann_date"], rows[0]["ann_time"], rows[0]["ann_sess"]), ("2026-10-06", "13:43", "盤後"))
        self.assertIsNone(rows[1]["ann_time"])


if __name__ == "__main__":
    unittest.main()
