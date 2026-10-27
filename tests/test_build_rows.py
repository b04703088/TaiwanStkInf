import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as B  # noqa: E402

CSV = """date,market,code,name,open,high,low,close,change,volume,value,transactions
2026-09-24,TWSE,2330,台積電,1000.0,1010.0,995.0,1005.0,-5.0,25123456,25000000000,45678
2026-09-24,TWSE,00625K,富邦上証+R,,,,,0.00,0,0,0
2026-09-24,TPEx,6488,環球晶,403.0,405.0,399.0,400.5,-2.5,1234000,495000000,2345
"""


class ReadRowsTest(unittest.TestCase):
    def test_read_rows_skips_no_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "20260924.csv"
            p.write_text(CSV, encoding="utf-8")
            rows = B.read_rows(p)
        self.assertEqual([r["code"] for r in rows], ["2330", "6488"])
        self.assertEqual(rows[0]["close"], 1005.0)
        self.assertEqual(rows[1]["market"], "TPEx")


if __name__ == "__main__":
    unittest.main()
