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
                "date,code,volume,value\n2026-09-30,6488,50,500000000\n2026-09-30,2330,100,900000000\n"
                "2026-09-30,1234,10,1000000\n2026-09-30,9999,0,0\n", encoding="utf-8")
            calls = []

            def fake(code, date):
                calls.append(code)
                return load("zco_2330.html")
            F.fetch_page = fake
            try:
                F.DELAY = 0
                self.assertEqual(F.main(["--date", "2026-09-30"]), 0)
                # 探測 + 兩檔（依成交金額大到小）；成交金額低於門檻的 1234、成交量 0 的 9999 略過
                self.assertEqual(calls, ["2330", "2330", "6488"])
                calls.clear()
                self.assertEqual(F.main(["--date", "2026-09-30"]), 0)
                self.assertEqual(calls, [])
                rows = F._read(F.out_paths("2026-09-30")[0])
                self.assertEqual(len(rows), 60)
            finally:
                F.DATA, F.OUT, F.fetch_page = old_data, old_out, old_fetch


if __name__ == "__main__":
    unittest.main()


class BrokerSiteTest(unittest.TestCase):
    def test_build_day_indexes(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import broker_site as S
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "2026").mkdir()
            (d / "2026" / "20260930.csv").write_text(
                "date,market,code,name,close,change,volume\n2026-09-30,TWSE,2330,台積電,1000,5,32500000\n", encoding="utf-8")
            (d / "broker" / "2026").mkdir(parents=True)
            (d / "broker" / "2026" / "20260930.csv").write_text(
                "date,code,side,rank,bid,broker,buy,sell,net,pct\n"
                "2026-09-30,2330,B,1,8440,摩根大通,6241,4053,2188,6.73\n"
                "2026-09-30,2330,S,1,1650,新加坡商瑞銀,3308,6989,-3681,11.32\n", encoding="utf-8")
            (d / "broker" / "2026" / "20260930_total.csv").write_text(
                "date,code,buy_total,sell_total,buy_cost,sell_cost\n2026-09-30,2330,9555,8446,2491.47,2489.04\n", encoding="utf-8")
            out = d / "_site"
            self.assertEqual(S.write_site(d, out), ["2026-09-30"])
            import json
            j = json.loads((out / "data" / "broker" / "2026-09-30.json").read_text(encoding="utf-8"))
            self.assertEqual(j["stocks"][0][:6], ["2330", "台積電", "TWSE", 1000, 5, 32500])
            self.assertEqual(j["stocks"][0][6:8], [9555, 8446])
            self.assertEqual(j["brokers"], [["8440", "摩根大通"], ["1650", "新加坡商瑞銀"]])
            self.assertEqual(j["rows"][1], [0, 1, 1, 1, 3308, 6989, 11.32])


class BrokerLocalTest(unittest.TestCase):
    def test_build_local_excludes_foreign_hq_and_kgi_taipei(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import broker_site as S
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "2026").mkdir()
            (d / "2026" / "20260930.csv").write_text(
                "date,market,code,name,close,change,volume\n2026-09-30,TWSE,2330,台積電,1000,5,32500000\n", encoding="utf-8")
            (d / "broker" / "2026").mkdir(parents=True)
            (d / "broker" / "branches.csv").write_text(
                "broker_id,broker,bid,branch\n8440,摩根大通,8440,摩根大通\n9200,凱基,9200,凱基\n"
                "9200,凱基,9268,凱基-台北\n9200,凱基,9275,凱基-三多\n9800,元大,98A8,元大-松江\n", encoding="utf-8")
            (d / "broker" / "2026" / "20260930.csv").write_text(
                "date,code,side,rank,bid,broker,buy,sell,net,pct\n"
                "2026-09-30,2330,B,1,8440,摩根大通,500,0,500,1\n"
                "2026-09-30,2330,B,2,9200,凱基,400,0,400,1\n"
                "2026-09-30,2330,B,3,9268,凱基-台北,300,0,300,1\n"
                "2026-09-30,2330,B,4,9275,凱基-三多,20,5,15,1\n"
                "2026-09-30,2330,S,1,98A8,元大-松江,0,10,-10,1\n", encoding="utf-8")
            j = S.build_local(d)
            self.assertEqual(j["date"], "2026-09-30")
            rows = j["periods"]["1"]["rows"]
            self.assertEqual([r[0] for r in rows], ["9275", "98A8"])  # 外資、總公司、凱基-台北都排除
            self.assertEqual(rows[0][:8], ["9275", "凱基-三多", 15000, 0, 15000, 1, 0, 1])
            self.assertEqual(rows[0][8], [["2330", 15000]])
            self.assertEqual(rows[1][2:5], [0, 10000, -10000])
