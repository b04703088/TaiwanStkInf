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
