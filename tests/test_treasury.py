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


if __name__ == "__main__":
    unittest.main()
