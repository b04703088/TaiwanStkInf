import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_tip_schedule as T  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


class TipTest(unittest.TestCase):
    def test_list_page(self):
        items = T.parse_list((FIX / "tip_list.html").read_text(encoding="utf-8"))
        self.assertEqual(items[0], ("1325", "2026年11月指數定期審核日程表", "2026-09-30"))
        self.assertEqual(len(items), len({i[0] for i in items}))

    def test_pdf_table_rows(self):
        tables = [[["指數名稱", "", "公告日期", "", "生效日期"], [None, None, "(收盤後)", None, None],
                   ["臺灣指數公司特選臺灣價值高息指數", "2026/11/17", None, None, "2026/11/18"]]]
        self.assertEqual(T.parse_tables(tables), [("臺灣指數公司特選臺灣價值高息指數", "2026-11-17", "2026-11-18")])

    def test_match_etfs(self):
        etfs = [{"etf": "009816", "index": "臺灣指數公司特選臺灣TOP 50指數"},
                {"etf": "00947", "index": "台灣IC設計動能指數"},
                {"etf": "00728", "index": "臺灣工業菁英30指數"},
                {"etf": "009809", "index": "S&amp;P TIP臺灣淨零轉型ESG 50指數"}]
        m = T.match_etfs(["臺灣指數公司特選臺灣 TOP 50 報酬指數", "臺灣指數公司特選臺灣上市上櫃 IC 設計動能指數",
                          "臺灣指數公司特選臺灣上市上櫃 IC 設計報酬指數", "臺灣指數公司工業菁英 30 指數",
                          "S&P TIP 臺灣淨零轉型 ESG 50 指數"], etfs)
        self.assertEqual(m["臺灣指數公司特選臺灣 TOP 50 報酬指數"], ["009816"])
        self.assertEqual(m["臺灣指數公司特選臺灣上市上櫃 IC 設計動能指數"], ["00947"])
        self.assertEqual(m["臺灣指數公司特選臺灣上市上櫃 IC 設計報酬指數"], [])  # 不誤配
        self.assertEqual(m["臺灣指數公司工業菁英 30 指數"], ["00728"])
        self.assertEqual(m["S&P TIP 臺灣淨零轉型 ESG 50 指數"], ["009809"])


if __name__ == "__main__":
    unittest.main()


class TipResultTest(unittest.TestCase):
    def load(self, i):
        return (FIX / f"tip_result_{i}.txt").read_text(encoding="utf-8")

    def test_single_index(self):
        r = T.parse_result(self.load(1317), "「臺灣指數公司台灣上市上櫃旗艦動能50指數」成分股審核結果")
        self.assertEqual(len(r), 1)
        idx, eff, adds, dels = r[0]
        self.assertEqual((idx, eff), ("臺灣指數公司台灣上市上櫃旗艦動能50指數", "2026-09-17"))
        self.assertEqual((len(adds), len(dels)), (22, 21))
        self.assertEqual(adds[0], ("1101", "台泥"))
        self.assertNotIn("2026", [c for c, _ in adds])   # 前言裡的日期不能被當成股票

    def test_multi_index_ftse(self):
        r = {x[0]: x for x in T.parse_result(self.load(1312), "臺灣指數系列成分股定期審核結果")}
        self.assertEqual(r["臺灣50指數"][2], [("6446", "藥華藥")])
        self.assertEqual(r["臺灣50指數"][3], [("3661", "世芯-KY")])   # 候補名單不算
        self.assertEqual(len(r["臺灣中型100指數"][2]), 4)
        self.assertEqual(r["臺灣50指數"][1], "2026-09-21")

    def test_inline_and_reversed_formats(self):
        self.assertEqual(T._stocks("3532 台勝科、6187 萬潤"), [("3532", "台勝科"), ("6187", "萬潤")])
        self.assertEqual(T._stocks("祥碩 5269\n9921巨大"), [("5269", "祥碩"), ("9921", "巨大")])
