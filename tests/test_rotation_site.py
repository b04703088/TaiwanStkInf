import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import rotation_site as R  # noqa: E402

HEAD = "date,market,code,name,open,high,low,close,change,volume,value,transactions\n"


def day(d, rows):
    return HEAD + "".join(f"{d},TWSE,{c},{n},0,0,0,{close},{ch},1,{v},1\n" for c, n, close, ch, v in rows)


class RotationTest(unittest.TestCase):
    def test_equal_weight_index_and_share(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "2026").mkdir()
            # 2330: 100 → 110 (+10%)；2303: 50 → 45 (−10%)；1101 不在族群內
            (d / "2026" / "20260102.csv").write_text(day("2026-01-02", [("2330", "台積電", 100, 0, 6e9), ("2303", "聯電", 50, 0, 2e9), ("1101", "台泥", 30, 0, 2e9)]), encoding="utf-8")
            (d / "2026" / "20260105.csv").write_text(day("2026-01-05", [("2330", "台積電", 110, 10, 6e9), ("2303", "聯電", 45, -5, 2e9), ("1101", "台泥", 30, 0, 2e9)]), encoding="utf-8")
            (d / "margin").mkdir()
            (d / "margin" / "index.csv").write_text("date,taiex,value\n2026-01-02,100,1\n2026-01-05,101,1\n", encoding="utf-8")
            orig = R.theme_groups
            R.theme_groups = lambda: [{"n": "晶圓代工", "st": "上游", "note": "", "codes": ["2330", "2303", "9999"]}]
            try:
                p = R.build(d)
            finally:
                R.theme_groups = orig
        g = p["sets"]["theme"][0]
        self.assertEqual(g["codes"], ["2330", "2303"])
        self.assertEqual(g["idx"], [100.0, 100.0])  # 等權：+10% 與 −10% 平均為 0
        self.assertAlmostEqual(g["sh"][-1], 80.0)
        self.assertEqual((g["up"], g["dn"]), (1, 1))
        self.assertEqual(p["taiex"], [100.0, 101.0])
        self.assertEqual(p["stocks"]["2330"][1], 1000)

    def test_theme_config_parses(self):
        gs = R.theme_groups()
        self.assertGreaterEqual(len(gs), 20)
        self.assertTrue(all(g["codes"] for g in gs))


if __name__ == "__main__":
    unittest.main()
