import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import attention_model as M  # noqa: E402


def feat(**kw):
    f = {"close": 100.0, "pct": 5.0, "vol": 1_000_000, "ind": "24", "pe": 20.0, "shares": 50_000_000,
         "m": {"s6": 1.0, "r30": 2.0, "r60": 3.0, "r90": 4.0, "vx": 1.0, "turn": 1.0},
         "i": {"s6": (2.0, 30), "r30": (2.0, 30), "r60": (3.0, 30), "r90": (4.0, 30)}}
    f.update(kw)
    return f


class JudgeTest(unittest.TestCase):
    def test_k1_main_and_band(self):
        self.assertIn("1", M.judge("TWSE", feat(s6=33.0, gap6=10.0), False))
        self.assertNotIn("1", M.judge("TWSE", feat(s6=31.0, gap6=10.0), False))
        self.assertIn("1", M.judge("TWSE", feat(s6=26.0, gap6=55.0), False))   # 25% 且價差 50 元
        self.assertIn("1", M.judge("TPEx", feat(s6=23.5, gap6=41.0), False))   # 上櫃 23% 且 40 元
        self.assertIn("1", M.judge("TPEx", feat(s6=-31.0, gap6=-5.0, pct=-3.0), False))

    def test_k1_exemptions(self):
        self.assertNotIn("1", M.judge("TWSE", feat(s6=40.0, gap6=1.0, close=4.5), False))       # 未滿 5 元
        f = feat(s6=40.0, gap6=10.0)
        f["i"] = dict(f["i"], s6=(30.0, 30))                                                       # 同類股也大漲
        self.assertNotIn("1", M.judge("TWSE", f, False))
        f["pe"] = 70.0                                                                             # 本益比 ≥ 60 不比同類
        self.assertIn("1", M.judge("TWSE", f, False))

    def test_k2_needs_red_close_and_exemption(self):
        f = feat(s6=10.0, gap6=5.0, r90=170.0)
        self.assertIn("2", M.judge("TWSE", f, False))
        self.assertNotIn("2", M.judge("TWSE", dict(f, pct=-1.0), False))   # 漲的要收紅
        self.assertNotIn("2", M.judge("TWSE", f, True))                    # 30 日內列過第一款、6 日沒超過 25%

    def test_k3_k4(self):
        f = feat(s6=26.0, gap6=5.0, vx=6.0, turn=12.0)
        self.assertEqual(M.judge("TWSE", f, False), {"3", "4"})
        self.assertEqual(M.judge("TPEx", f, False), set())                 # 上櫃第三、四款要超過 27%


class TriggerTest(unittest.TestCase):
    def test_up_trigger(self):
        up, dn, k34 = M.triggers("TWSE", {"close": 100.0, "s5": 30.0, "b5": 90.0})
        self.assertAlmostEqual(up, 2.0)        # 32－30；價差那條要漲 40% 才到 50 元，取較小
        self.assertAlmostEqual(dn, -60.0)
        self.assertAlmostEqual(k34, -5.0)
        self.assertEqual(M.bucket(up), "3")
        up, _, _ = M.triggers("TWSE", {"close": 100.0, "s5": 30.0, "b5": 40.0})
        self.assertAlmostEqual(up, -5.0)       # 價差已經 60 元，累積過 25% 就中
        self.assertEqual(M.bucket(-12), "lock")
        self.assertEqual(M.bucket(12), "far")


if __name__ == "__main__":
    unittest.main()
