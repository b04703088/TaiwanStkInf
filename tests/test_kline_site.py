import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import kline_site as K  # noqa: E402


class KlineSiteTest(unittest.TestCase):
    def test_build(self):
        prices = {"0050": {"name": "元大台灣50", "market": "TWSE",
                           "rows": [(20250610, 185, 189, 184.9, 188.65, 31483), (20250618, 47.5, 47.72, 47.14, 47.57, 252640)]},
                  "9999": {"name": "已下市", "market": "TPEx", "rows": [(20220103, 10, 10, 10, 10, 1)]}}
        events = {"0050": [[20220121, 0.9785, "除息", "", 3.2], [20250618, 0.24998675, "分割", "1 單位分割為 4 單位", None]]}
        days = [20220103] + list(range(20250501, 20250531)) + list(range(20250601, 20250619))  # 9999 最後成交日已超出最近 LIVE_DAYS 個交易日
        index, per = K.build(prices, events, days)
        self.assertEqual(index["stocks"], [["0050", "元大台灣50", "TWSE"]])  # 最近沒成交的不放
        s = per["0050"]
        self.assertEqual((s["d"], s["c"], s["v"]), ([20250610, 20250618], [188.65, 47.57], [31483, 252640]))
        self.assertEqual(s["ev"], [[20250618, 0.24998675, "分割", "1 單位分割為 4 單位", None]])  # 第一筆價格前的事件略過

    def test_number(self):
        self.assertEqual((K._n("2440.00"), K._n("47.57"), K._n(""), K._n("--")), (2440, 47.57, None, None))


if __name__ == "__main__":
    unittest.main()
