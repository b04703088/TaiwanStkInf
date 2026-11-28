import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import gex_site as G  # noqa: E402
import fetch_futures as F  # noqa: E402

H = "exp,exp_date,strike,cp,close,settle,volume,oi\n"
INST = "date,product,who,net_vol,net_val,oi_long,oi_short,oi_net,oi_net_val,oi_long_val,oi_short_val\n"


def chain(F0, T, s, ks, ed, exp="202612", oi=100):
    out = ""
    for k in ks:
        for cp in "CP":
            px = G.b76(F0, k, T, s, cp)
            out += f"{exp},{ed},{k},{cp},{px:.1f},{px:.1f},10,{oi}\n"
    return out


class GexTest(unittest.TestCase):
    def test_iv_roundtrip(self):
        for cp in "CP":
            px = G.b76(40000, 41000, 20 / 365, 0.3, cp)
            self.assertAlmostEqual(G.implied(px, 40000, 41000, 20 / 365, cp), 0.3, places=4)
        self.assertIsNone(G.implied(0.0, 40000, 45000, 5 / 365, "C"))

    def test_gamma_numeric(self):
        Fp, K, T, s = 40000, 40500, 10 / 365, 0.25
        _, g = G.greeks(Fp, K, T, s, "C")
        h = 5
        d_up, _ = G.greeks(Fp + h, K, T, s, "C")
        d_dn, _ = G.greeks(Fp - h, K, T, s, "C")
        self.assertAlmostEqual(g, (d_up - d_dn) / (2 * h), places=7)

    def test_theta_matches_target(self):
        oi, px = [100, 100, 100], [1.0, 10.0, 100.0]
        th, w = G.solve_theta(oi, px, 5.0)
        self.assertLess(th, 0)
        self.assertAlmostEqual(sum(a * b for a, b in zip(w, px)), 5.0, places=4)
        self.assertAlmostEqual(G.solve_theta(oi, px, 37.0)[0], 0, places=3)  # 全市場平均 → θ≈0

    def test_cap(self):
        al = {"a": [8.0, 2.0], "b": [8.0, 2.0]}
        G.cap(al, [10, 10])
        self.assertLessEqual(al["a"][0] + al["b"][0], 10 + 1e-6)
        self.assertAlmostEqual(sum(al["a"]) + sum(al["b"]), 20, places=6)

    def test_parse_opt_vals(self):
        r = ["2026/11/27", "臺指選擇權", "買權", "自營商"] + [str(i) for i in range(4, 16)]
        got = F.parse_opt([r])[0]
        self.assertEqual((got["oi_long"], got["oi_long_val"], got["oi_short"], got["oi_short_val"]), ("10", "11", "12", "13"))

    def test_build_zero_sum(self):
        with tempfile.TemporaryDirectory() as t:
            fut = Path(t) / "futures"
            (fut / "txo" / "2026").mkdir(parents=True)
            ks = range(38000, 42001, 500)
            for d, days in (("20261127", 20), ("20261130", 17)):
                (fut / "txo" / "2026" / f"{d}.csv").write_text(H + chain(40000, (days - 0.01) / 365, 0.3, ks, "2026-12-17"))
            (fut / "tx.csv").write_text("date,contract,close,change,volume,settle,oi,oi_all\n"
                                        "2026-11-27,202612,40000,0,1,1,1,1\n2026-11-30,202612,40100,100,1,1,1,1\n")
            rows = INST
            for d in ("2026-11-27", "2026-11-30"):
                # 自營商：賣價外買權（低權利金）、買賣權；外資只有口數沒有金額 → 第二天一律有金額
                val = d == "2026-11-30"
                rows += f"{d},TXO_C,dealer,0,0,50,300,-250,0,{'1000' if val else ''},{'3000' if val else ''}\n"
                rows += f"{d},TXO_P,dealer,0,0,200,0,200,0,{'50000' if val else ''},{'0' if val else ''}\n"
                rows += f"{d},TXO_C,foreign,0,0,100,100,0,0,,\n"
            (fut / "inst.csv").write_text(rows)
            p = G.build(t)
        self.assertEqual(p["date"], "2026-11-30")
        gs = {g["who"]: g for g in p["groups"]}
        self.assertAlmostEqual(sum(g["gamma"] for g in p["groups"]), 0, delta=2)
        self.assertLess(gs["dealer"]["gamma_c"], 0)                  # 賣買權 → short gamma
        self.assertEqual(p["method"], "equal")                       # 外資沒有金額
        self.assertEqual(p["hist"]["rows"][0][0], "2026-11-27")
        self.assertAlmostEqual(p["spot"], 40000, delta=1)
        self.assertAlmostEqual(p["exps"][0]["iv"], 30, delta=0.5)
        a = {(r[0], r[1], r[2]): r for r in p["alloc"]["rows"]}
        self.assertLess(a[("dealer", "C", "short")][6], 0)           # 平均權利金 ~ 0.2 點 → 偏價外
        self.assertTrue(math.isfinite(p["profile"]["rows"][0][2]))


if __name__ == "__main__":
    unittest.main()
