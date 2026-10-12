import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import analyst_site as S  # noqa: E402


class AnalystSiteTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            a = Path(d) / "analyst"
            a.mkdir()
            (a / "consensus_2026.csv").write_text(
                "date,time,news_id,code,name,kind,year,analysts,prev,value,chg_pct,high,low,target,bull,neutral,bear,close,url\n"
                "2026-10-07,12:10,6623548,6147,頎邦,tp,,6,260,270,3.85,290,225,270,5,1,0,234.5,u\n"
                "2026-10-08,08:10,6623600,4958,臻鼎-KY,eps,2026,8,14.05,13.79,-1.85,16.18,11.51,644,,,,,u\n", encoding="utf-8")
            (a / "reports_2025.csv").write_text(
                "date,time,news_id,broker,code,name,action,rating,target,prev_target,title,url\n"
                "2025-12-01,09:00,6200000,高盛,2330,台積電,up,買進,1800,1600,標題,u\n", encoding="utf-8")
            out = Path(d) / "out" / "analyst.json"
            p = S.write_analyst(d, out)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), p)
            self.assertEqual(p["generated"], "2026-10-08")
            cons = [dict(zip(p["cons"]["cols"], r)) for r in p["cons"]["rows"]]
            self.assertEqual([c["code"] for c in cons], ["4958", "6147"])  # 新到舊
            self.assertEqual((cons[1]["bull"], cons[1]["target"], cons[0]["bull"]), (5, 270, None))
            rep = dict(zip(p["reps"]["cols"], p["reps"]["rows"][0]))
            self.assertEqual((rep["broker"], rep["target"], rep["prev_target"]), ("高盛", 1800, 1600))
            self.assertEqual(p["names"], {"4958": "臻鼎-KY", "6147": "頎邦", "2330": "台積電"})

    def test_no_data(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(S.write_analyst(d, Path(d) / "x.json"))


if __name__ == "__main__":
    unittest.main()
