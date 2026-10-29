import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import limitup_site as L  # noqa: E402

HEAD = "date,market,code,name,open,high,low,close,change,volume,value,transactions\n"


class LimitUpSiteTest(unittest.TestCase):
    def test_limit_price(self):
        self.assertEqual(L.limit(Decimal("73.20")), Decimal("80.5"))     # 80.52 → 0.1 跳
        self.assertEqual(L.limit(Decimal("491")), Decimal("540"))        # 540.1 → 跨到 1 元跳
        self.assertEqual(L.limit(Decimal("2910")), Decimal("3200"))      # 3201 → 5 元跳
        self.assertEqual(L.limit(Decimal("12.35")), Decimal("13.55"))
        self.assertEqual(L.limit(Decimal("50"), up=False), Decimal("45"))

    def test_build_streak_and_next(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "2026"
            d.mkdir()
            days = {
                "20261026": ["TWSE,1111,甲,10,11,10,11,1,1000,11000,1", "TWSE,2222,乙,10,10,10,10,0,1000,10000,1"],
                "20261027": ["TWSE,1111,甲,12.1,12.1,12.1,12.1,1.1,1000,12100,1", "TWSE,2222,乙,10,11,10,10.5,0.5,1000,10500,1",
                             "TWSE,3333,丙,50,60,50,60,10,1000,60000,1"],  # 丙最高超過漲停價（無漲跌幅限制）
                "20261028": ["TWSE,1111,甲,13,13,12,12.5,0.4,1000,12500,1"],
            }
            for k, v in days.items():
                (d / f"{k}.csv").write_text(HEAD + "\n".join(f"2026-10-28,{x}" for x in v) + "\n", encoding="utf-8")
            p = L.build(t)
            r27 = {r[0]: r for r in p["rows"]["20261027"]}
            self.assertEqual(sorted(r27), ["1111", "2222"])
            self.assertEqual(r27["1111"][3], 1)      # 鎖漲停
            self.assertEqual(r27["1111"][8], 2)      # 連 2 板
            self.assertAlmostEqual(r27["1111"][9], 3.31)  # 隔天 +0.4/12.1
            self.assertEqual(r27["2222"][3], 0)      # 觸及打開
            self.assertEqual(p["count"]["lu"], [1, 1, 0])


if __name__ == "__main__":
    unittest.main()
