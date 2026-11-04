import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import liq_site  # noqa: E402


class LiqTest(unittest.TestCase):
    def test_avg_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            for i, (a, b) in enumerate([(1e8, 0), (3e8, 4e8), (2e8, None)]):
                p = Path(tmp) / f"2026110{i + 1}.csv"
                with p.open("w", newline="", encoding="utf-8") as fp:
                    w = csv.DictWriter(fp, fieldnames=["date", "market", "code", "value"])
                    w.writeheader()
                    w.writerow({"date": f"2026-11-0{i + 1}", "market": "TWSE", "code": "2330", "value": a})
                    if b is not None:
                        w.writerow({"date": f"2026-11-0{i + 1}", "market": "TPEx", "code": "8299", "value": b})
                files.append(p)
            out = liq_site.build(files, n=5)
        self.assertEqual((out["date"], out["n"]), ("2026-11-03", 3))
        self.assertEqual(out["v"], {"2330": 2.0, "8299": round(4 / 3, 3)})  # 沒成交的天以 0 計


if __name__ == "__main__":
    unittest.main()
