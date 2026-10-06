import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import flow_site  # noqa: E402


def write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class FlowTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cols = ["date", "market", "code", "name", "close", "change", "value"]
            for day, v in (("20261001", 1e9), ("20261002", 3e9)):
                write(d / "2026" / f"{day}.csv", cols, [
                    {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "market": "TWSE", "code": "2330", "name": "台積電", "close": 1, "change": 0, "value": v},
                    {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "market": "TWSE", "code": "0050", "name": "元大台灣50", "close": 1, "change": 0, "value": 5e9},
                    {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "market": "TWSE", "code": "2303", "name": "聯電", "close": 1, "change": 0, "value": 2e8}])
            write(d / "industry" / "chain.csv", ["code", "name", "industry_id", "industry", "stream", "node_id", "node", "sub_id", "sub"], [
                {"code": "2330", "name": "台積電", "industry_id": "D000", "industry": "半導體", "stream": "中游", "node_id": "D300", "node": "IC/晶圓製造", "sub_id": "D310", "sub": "晶圓製造"},
                {"code": "2303", "name": "聯電", "industry_id": "D000", "industry": "半導體", "stream": "中游", "node_id": "D300", "node": "IC/晶圓製造", "sub_id": "D310", "sub": "晶圓製造"}])
            write(d / "industry" / "official.csv", ["code", "name", "market", "ind_code", "industry"], [
                {"code": "2330", "name": "台積電", "market": "上市", "ind_code": "24", "industry": "半導體"}])
            p = flow_site.build(d)
        self.assertEqual(p["days"], ["2026-10-01", "2026-10-02"])
        self.assertNotIn("0050", p["vals"])                 # ETF 不算
        self.assertEqual(p["vals"]["2330"], [1000, 3000])  # 百萬元
        sub = p["groups"]["sub"][0]
        self.assertEqual((sub[0], sub[1], sub[2]), ("晶圓製造", "半導體 › 中游 › IC/晶圓製造", ["2303", "2330"]))
        self.assertEqual(p["groups"]["ind"][0][2], ["2303", "2330"])
        self.assertEqual(p["groups"]["off"], [["半導體", "官方產業別", ["2330"]]])


if __name__ == "__main__":
    unittest.main()
