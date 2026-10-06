import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_industry as I  # noqa: E402
import industry_site as S  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "industry"


class ChainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (FIX / "ic_D000.html").read_text(encoding="utf-8")
        cls.rows = I.parse_chain(cls.page, "D000", "半導體")

    def paths(self, code):
        return sorted({(r["stream"], r["node"], r["sub"]) for r in self.rows if r["code"] == code})

    def test_industry_list(self):
        inds = I.parse_industries(self.page)
        self.assertEqual(len(inds), 47)
        self.assertIn(("C100", "製藥"), inds)
        self.assertIn(("X000", "其他"), inds)

    def test_streams_and_subs(self):
        self.assertEqual(self.paths("2330"), [("中游", "IC/晶圓製造", "晶圓製造")])
        mtk = self.paths("2454")
        self.assertIn(("上游", "IC設計", "電源管理IC"), mtk)
        self.assertEqual(len(mtk), 5)
        self.assertEqual(self.paths("3711"), [("下游", "IC封裝測試", "")])

    def test_no_duplicates(self):
        keys = [(r["code"], r["node_id"], r["sub_id"]) for r in self.rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(r["code"] for r in self.rows))  # 外國企業（沒有代號）不列


class SiteTest(unittest.TestCase):
    def test_short_name(self):
        self.assertEqual(S.short("無線通訊設備(如行動電話、衛星定位系統、數位機上盒)"), "無線通訊設備")
        self.assertEqual(S.short("IC/晶圓製造"), "IC/晶圓製造")

    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "industry"
            p.mkdir()
            rows = I.parse_chain((FIX / "ic_D000.html").read_text(encoding="utf-8"), "D000", "半導體")
            with (p / "chain.csv").open("w", newline="", encoding="utf-8") as fp:
                w = csv.DictWriter(fp, fieldnames=I.CHAIN_COLS)
                w.writeheader()
                w.writerows(rows)
            with (p / "official.csv").open("w", newline="", encoding="utf-8") as fp:
                w = csv.DictWriter(fp, fieldnames=I.OFF_COLS)
                w.writeheader()
                w.writerow({"code": "2330", "name": "台積電", "market": "上市", "ind_code": "24", "industry": "半導體"})
                w.writerow({"code": "6781", "name": "AES-KY", "market": "上市", "ind_code": "28", "industry": "電子零組件"})
            out = S.build(d)
        self.assertEqual(out["industries"], ["半導體"])
        name, official, idx = out["stocks"]["2330"]
        self.assertEqual((name, official), ("台積電", "半導體"))
        self.assertEqual([out["nodes"][i][1:4] for i in idx], [["中游", "IC/晶圓製造", "晶圓製造"]])
        self.assertEqual(out["stocks"]["6781"], ["AES-KY", "電子零組件", []])  # 平台沒收錄：只有官方產業別


if __name__ == "__main__":
    unittest.main()
