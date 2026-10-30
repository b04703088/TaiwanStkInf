import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import us_site as U  # noqa: E402


class UsSiteTest(unittest.TestCase):
    def test_us_by_tw_maps_previous_night(self):
        # 美股 1/2、1/3（週五）、1/6；台股 1/3、1/6、1/7
        us = (["2025-01-02", "2025-01-03", "2025-01-06"], [0, 0, 0], [100.0, 110.0, 99.0])
        m = U.us_by_tw(us, [20250103, 20250106, 20250107])
        self.assertNotIn(20250103, m)                 # 第一天沒有前一個台股日可比
        self.assertAlmostEqual(m[20250106], 10.0)     # 1/6 台股看 1/3 美股（1/2 → 1/3）
        self.assertAlmostEqual(m[20250107], -10.0)    # 1/7 台股看 1/6 美股

    def test_reactions_next_tw_day(self):
        U_THR = U.THR
        try:
            U.THR = 3.0
            us = (["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"], [0] * 4, [100.0, 110.0, 110.0, 99.0])
            days = [20250103, 20250106, 20250107, 20250108]
            ser = {"2330": {20250103: (100, 100), 20250106: (102, 104), 20250107: (104, 103), 20250108: (101, 100)}}
            thr, up, dn, out = U.reactions(us, ser, days, {})
        finally:
            U.THR = U_THR
        self.assertEqual((up, dn), (1, 1))
        s = out["2330"]
        self.assertAlmostEqual(s[0], 2.0)    # 大漲後開盤跳空 102/100
        self.assertAlmostEqual(s[1], 4.0)    # 當日 104/100
        self.assertEqual(s[2], 100)          # 同向
        self.assertAlmostEqual(s[5], round((100 / 103 - 1) * 100, 2))
        self.assertEqual(thr, 3.0)

    def test_corr(self):
        c, b = U.corr(list(range(30)), [2 * x + 1 for x in range(30)])
        self.assertAlmostEqual(c, 1.0)
        self.assertAlmostEqual(b, 2.0)


if __name__ == "__main__":
    unittest.main()
