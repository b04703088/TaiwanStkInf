import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_etf_rebalance as R  # noqa: E402

DAYS = [f"2026-06-{d:02d}" for d in (15, 16, 17, 18, 22, 23, 24, 25, 26, 29, 30)] + ["2026-07-01", "2026-07-02"]


def snap(weights):
    return {c: (c, int(w * 1000), w) for c, w in weights.items()}


BASE = {f"S{i}": 4.0 for i in range(25)}  # 25 檔、各 4%


class DetectTest(unittest.TestCase):
    def test_spread_rebalance(self):
        """生效日 6/22：A、B 6/18 開始賣、6/24 賣完；X、Y 6/18 開始買、6/25 買到位"""
        hist = {}
        for d in DAYS:
            w = dict(BASE)
            w["A"] = w["B"] = 4.0
            if d >= "2026-06-18":
                w["A"] = w["B"] = 2.0 if d < "2026-06-24" else 0
                w["X"] = w["Y"] = 1.0 if d < "2026-06-25" else 4.0
            hist[d] = snap({k: v for k, v in w.items() if v})
        ev = R.detect_events(hist, DAYS, ["2026-06-22"])
        self.assertEqual(len(ev), 1)
        e = ev[0]
        self.assertEqual((e["start"], e["end"], e["days"]), ("2026-06-18", "2026-06-25", 5))  # 6/19 休市
        self.assertEqual((e["effective"], e["start_off"], e["end_off"]), ("2026-06-22", -1, 3))
        self.assertEqual((e["adds"], e["dels"]), ("X Y", "A B"))

    def test_small_drift_after_done_ignored(self):
        """6/22 一天換完；之後新增股因申購小幅增加 0.4%，不算還在調整"""
        hist = {}
        for i, d in enumerate(DAYS):
            w = dict(BASE)
            w["A"] = 4.0
            if d >= "2026-06-22":
                del w["A"]
                w["X"] = 4.0
            sc = 1 + 0.004 * max(0, i - 4)
            hist[d] = {c: (c, int(v * 1000 * (sc if c == "X" else 1)), v) for c, v in w.items()}
        ev = R.detect_events(hist, DAYS, ["2026-06-22"])
        self.assertEqual([(e["start"], e["end"], e["days"]) for e in ev], [("2026-06-22", "2026-06-22", 1)])

    def test_incomplete_snapshot_ignored(self):
        """某天只抓到一半的持股（資料不完整），不是換股"""
        hist = {d: snap(BASE) for d in DAYS}
        hist["2026-06-23"] = snap({k: v for k, v in list(BASE.items())[:10]})
        self.assertEqual(R.detect_events(hist, DAYS, []), [])

    def test_creation_redemption_not_rebalance(self):
        """申購贖回只會讓股數同比例變動，成分股不變 → 沒有事件"""
        hist = {d: {c: (c, 1000 * (i + 1), w) for c, w in BASE.items()} for i, d in enumerate(DAYS)}
        self.assertEqual(R.detect_events(hist, DAYS, []), [])


if __name__ == "__main__":
    unittest.main()
