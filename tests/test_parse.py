import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_daily as fd  # noqa: E402

D = date(2026, 9, 23)

TWSE = {
    "stat": "OK",
    "tables": [
        {"title": "115年09月23日 價格指數(臺灣證券交易所)", "fields": ["指數"], "data": [["x"]]},
        {
            "title": "115年09月23日 每日收盤行情(全部(不含權證、牛熊證))",
            "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價",
                       "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差",
                       "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"],
            "data": [
                ["2330", "台積電", "25,123,456", "45,678", "25,000,000,000", "1,000.00",
                 "1,010.00", "995.00", "1,005.00",
                 "<p style= color:green>-</p>", "5.00", "1,005.00", "10", "1,010.00", "20", "25.1"],
                ["9999", "停牌股", "0", "0", "0", "--", "--", "--", "--",
                 "<p> </p>", "0.00", "", "", "", "", "0.00"],
            ],
        },
    ],
}

TPEX = {
    "stat": "ok",
    "tables": [{
        "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價",
                   "成交股數", "成交金額(元)", "成交筆數"],
        "data": [["6488", "環球晶", "400.50", "-2.50", "403.00", "405.00", "399.00",
                  "401.2", "1,234,000", "495,000,000", "2,345"]],
    }],
}


class ParseTest(unittest.TestCase):
    def test_twse(self):
        rows = fd.parse_twse(TWSE, D)
        self.assertEqual(len(rows), 2)
        r = rows[0]
        self.assertEqual((r["code"], r["close"], r["change"], r["volume"]),
                         ("2330", "1005.00", "-5.00", "25123456"))
        self.assertEqual(rows[1]["close"], "")

    def test_tpex(self):
        r = fd.parse_tpex(TPEX, D)[0]
        self.assertEqual((r["market"], r["code"], r["open"], r["change"], r["value"]),
                         ("TPEx", "6488", "403.00", "-2.50", "495000000"))

    def test_no_data(self):
        self.assertEqual(fd.parse_twse({"stat": "很抱歉，沒有符合條件的資料!"}, D), [])
        self.assertEqual(fd.parse_tpex({"stat": "ok", "tables": [{"data": []}]}, D), [])


if __name__ == "__main__":
    unittest.main()
