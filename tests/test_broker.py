import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_broker as F  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return (FIX / name).read_bytes().decode("cp950", errors="replace")


class BrokerParseTest(unittest.TestCase):
    def test_top15_both_sides(self):
        rows, total = F.parse(load("zco_2330.html"), "2026-09-30", "2330")
        buys = [r for r in rows if r["side"] == "B"]
        sells = [r for r in rows if r["side"] == "S"]
        self.assertEqual((len(buys), len(sells)), (15, 15))
        self.assertEqual((buys[0]["broker"], buys[0]["bid"], buys[0]["net"], buys[0]["pct"]), ("摩根大通", "8440", 2188, 6.73))
        self.assertEqual((sells[0]["broker"], sells[0]["net"]), ("新加坡商瑞銀", -3681))
        self.assertEqual([r["rank"] for r in buys], list(range(1, 16)))
        self.assertEqual((total["buy_total"], total["sell_total"], total["buy_cost"]), (9555, 8446, 2491.47))

    def test_hex_branch_id(self):
        rows, _ = F.parse(load("zco_6488.html"), "2026-09-30", "6488")
        self.assertIn("888A", {r["bid"] for r in rows})
        self.assertEqual(F.decode_bid("0039004200320030"), "9B20")
        self.assertEqual(F.decode_bid("9800"), "9800")

    def test_no_data(self):
        rows, total = F.parse(load("zco_nodata.html"), "2026-10-01", "2330")
        self.assertEqual(rows, [])
        self.assertEqual(total["buy_total"], "")

    def test_resume_skips_done_codes(self):
        with tempfile.TemporaryDirectory() as d:
            old_data, old_out, old_fetch = F.DATA, F.OUT, F.fetch_page
            F.DATA, F.OUT = Path(d), Path(d) / "broker"
            (Path(d) / "2026").mkdir()
            (Path(d) / "2026" / "20260930.csv").write_text(
                "date,code,volume\n2026-09-30,2330,100\n2026-09-30,6488,50\n2026-09-30,9999,0\n", encoding="utf-8")
            calls = []

            def fake(code, date):
                calls.append(code)
                return load("zco_2330.html")
            F.fetch_page = fake
            try:
                F.DELAY = 0
                self.assertEqual(F.main(["--date", "2026-09-30"]), 0)
                self.assertEqual(calls, ["2330", "2330", "6488"])  # 探測 + 兩檔；成交量 0 的略過
                calls.clear()
                self.assertEqual(F.main(["--date", "2026-09-30"]), 0)
                self.assertEqual(calls, [])
                rows = F._read(F.out_paths("2026-09-30")[0])
                self.assertEqual(len(rows), 60)
            finally:
                F.DATA, F.OUT, F.fetch_page = old_data, old_out, old_fetch


if __name__ == "__main__":
    unittest.main()
