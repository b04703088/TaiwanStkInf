import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import etf_site as E  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_raw_changes(self):
        self.assertEqual(E.classify(None, 5000), ("new", 5000))
        self.assertEqual(E.classify(5000, None), ("removed", -5000))
        self.assertEqual(E.classify(5000, 5000), ("same", 0))
        # 不過濾申購贖回：同比例增加也算增加
        self.assertEqual(E.classify(1_000_000, 1_010_000), ("add", 10_000))
        self.assertEqual(E.classify(608_720_000, 606_820_000), ("cut", -1_900_000))


class BuildTest(unittest.TestCase):
    def test_build_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "2026").mkdir()
            (d / "2026" / "20260929.csv").write_text(
                "date,market,code,name,open,high,low,close,change,volume,value,transactions\n"
                "2026-09-29,TWSE,2330,台積電,1,1,1,2500,0,1,1,1\n", encoding="utf-8")
            (d / "etf" / "00999A").mkdir(parents=True)
            (d / "etf" / "etf_list.csv").write_text(
                "etf,name,issuer,issuer_name,kind\n00999A,測試,x,測試投信,active\n", encoding="utf-8")
            (d / "etf" / "summary.csv").write_text(
                "date,etf,aum,units,nav,holdings,fetched_at\n2026-09-24,00999A,1,100,1,2,x\n2026-09-29,00999A,1,100,1,2,x\n",
                encoding="utf-8")
            cols = "date,etf,code,name,shares,weight\n"
            (d / "etf" / "00999A" / "20260924.csv").write_text(
                cols + "2026-09-24,00999A,2330,台積電,10000,50\n2026-09-24,00999A,2454,聯發科,4000,40\n", encoding="utf-8")
            (d / "etf" / "00999A" / "20260929.csv").write_text(
                cols + "2026-09-29,00999A,2330,台積電,15000,70\n2026-09-29,00999A,3665,貿聯-KY,2000,20\n", encoding="utf-8")
            p = E.build_latest(d)
            self.assertEqual(p["etfs"][0]["prev"], "2026-09-24")
            rows = {r[1]: dict(zip(p["cols"], r)) for r in p["rows"]}
            self.assertEqual((rows["2330"]["cls"], rows["2330"]["d"], rows["2330"]["px"]), ("add", 5000, 2500.0))
            self.assertEqual((rows["2454"]["cls"], rows["2454"]["sh"], rows["2454"]["psh"]), ("removed", 0, 4000))
            self.assertEqual((rows["3665"]["cls"], rows["3665"]["psh"], rows["3665"]["d"]), ("new", 0, 2000))
            self.assertEqual(rows["2454"]["d"], -4000)


if __name__ == "__main__":
    unittest.main()
