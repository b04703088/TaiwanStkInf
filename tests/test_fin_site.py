import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fin_site as S  # noqa: E402


def rev(ym, code, v, yoy=None):
    return {"ym": ym, "market": "上市", "code": code, "name": "台積電", "industry": "半導體業", "revenue": str(v),
            "mom_pct": "", "yoy_pct": "" if yoy is None else str(yoy), "cum": "", "cum_yoy_pct": "", "note": ""}


def q(yq, code, rv, ni, eps, eq=1000):
    return {"year": yq[:4], "season": yq[-1], "market": "上市", "code": code, "name": "台積電", "type": "一般",
            "q_revenue": str(rv), "q_gross_profit": str(rv / 2), "q_operating_income": str(rv / 4),
            "q_net_income_parent": str(ni), "q_eps": str(eps), "total_assets": "3000", "total_liabilities": "1000",
            "equity_parent": str(eq), "bvps": "50"}


class FinSiteTest(unittest.TestCase):
    def test_high_n(self):
        s = [["a", 10], ["b", 30], ["c", 5], ["d", 20], ["e", 25]]
        self.assertEqual(S.high_n(s, 4), 2)  # 25 比 20、5 高，碰到 30 停
        self.assertEqual(S.high_n([["a", 1], ["b", 2]], 1), 1)

    def test_build(self):
        revs = {"202608": [rev("202608", "2330", 100)], "202609": [rev("202609", "2330", 120, 20.0)]}
        qs = {f"{y}Q{s}": [q(f"{y}Q{s}", "2330", 100 + s, 10 * s, 1.0 * s)] for y in (2025, 2026) for s in (1, 2, 3, 4)
              if (y, s) <= (2026, 2)}
        qs["2026Q2"][0]["q_eps"] = "4"
        idx, stocks = S.build(revs, qs)
        r = dict(zip(idx["rev"]["cols"], idx["rev"]["rows"][0]))
        self.assertEqual((idx["rev"]["ym"], r["revenue"], r["yoy"], r["high_n"]), ("202609", 120, 20, 1))
        self.assertEqual(idx["q"]["yq"], "2026Q2")
        k = dict(zip(idx["q"]["cols"], idx["q"]["rows"][0]))
        self.assertEqual(k["eps_yoy"], 100.0)  # 4 vs 2025Q2 的 2
        self.assertEqual(k["ttm_eps"], 3 + 4 + 1 + 4)  # 2025Q3、Q4、2026Q1、Q2
        self.assertEqual(k["gm"], 50.0)
        self.assertEqual(k["roe"], (30 + 40 + 10 + 20) / 1000 * 100)
        st = stocks["2330"]
        self.assertEqual([x[0] for x in st["rev"]["rows"]], ["202608", "202609"])
        self.assertEqual(st["q"]["rows"][-1][0], "2026Q2")

    def test_rank_quarter_skips_thin_filing(self):
        base = {f"2026Q{s}": [q(f"2026Q{s}", c, 100, 10, 1) for c in ("1101", "1102", "1103")] for s in (1, 2)}
        base["2026Q3"] = [q("2026Q3", "1101", 100, 10, 1)]  # 申報期間剛開始
        idx, stocks = S.build({}, base)
        self.assertEqual((idx["q"]["yq"], idx["q"]["latest"]), ("2026Q2", "2026Q3"))
        self.assertEqual(stocks["1101"]["q"]["rows"][-1][0], "2026Q3")

    def test_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "financials" / "revenue"
            d.mkdir(parents=True)
            (d / "202609.csv").write_text("ym,market,code,name,industry,revenue,prev_month,last_year,mom_pct,yoy_pct,cum,"
                                          "cum_last_year,cum_yoy_pct,note\n202609,上市,2330,台積電,半導體業,5,,,,,,,,\n",
                                          encoding="utf-8")
            S.write_fin(tmp, Path(tmp) / "out")
            self.assertEqual(json.loads((Path(tmp) / "out" / "s" / "2330.json").read_text())["name"], "台積電")


if __name__ == "__main__":
    unittest.main()
