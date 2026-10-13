import csv
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import broker_score as S  # noqa: E402

PCOLS = ["date", "market", "code", "name", "open", "high", "low", "close", "change", "volume", "value", "transactions"]
BCOLS = ["date", "code", "side", "rank", "bid", "broker", "buy", "sell", "net", "pct"]
TCOLS = ["date", "code", "buy_total", "sell_total", "buy_cost", "sell_cost"]
VOL = 1_000_000          # 每檔每天 1000 張
N_DAYS, N_STOCKS = 30, 100
SMART, DT = "A001", "D001"
NOISE = ["N001", "N002", "N003"]


def weekdays(n, start=date(2026, 6, 1)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _w(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build(tmp):
    """高手 A001：第 t 天買 code(t)，那檔第 t+2～t+5 天每天漲 2%。
    隔日沖 D001：第 t 天買 code(50+t)（當天漲 5%），隔天全部賣掉。
    N001–N003：每天買一檔不會動的股票。"""
    days = weekdays(N_DAYS)
    codes = [str(1101 + i) for i in range(N_STOCKS)]
    rets = {c: [0.0] * N_DAYS for c in codes}
    for t in range(20):
        for j in range(t + 2, min(t + 6, N_DAYS)):
            rets[codes[t]][j] = 0.02
        rets[codes[50 + t]][t] = 0.05
    close = {c: 100.0 for c in codes}
    net = {d: [] for d in days}   # (code, bid, 張數)
    for t, d in enumerate(days):
        if t < 20:
            net[d].append((codes[t], SMART, 100))
            net[d].append((codes[50 + t], DT, 100))
        if 1 <= t <= 20:
            net[d].append((codes[50 + t - 1], DT, -100))
        for k, b in enumerate(NOISE):
            net[d].append((codes[80 + (t + 7 * k) % 20], b, 100))
    for t, d in enumerate(days):
        prows = []
        for c in codes:
            prev = close[c]
            cl = round(prev * (1 + rets[c][t]), 4)
            close[c] = cl
            prows.append({"date": d, "market": "TWSE", "code": c, "name": f"股{c}", "open": prev, "high": cl,
                          "low": prev, "close": cl, "change": f"{cl - prev:+.4f}", "volume": VOL,
                          "value": VOL * cl, "transactions": 1})
        stem = d.replace("-", "")
        _w(tmp / d[:4] / f"{stem}.csv", PCOLS, prows)
        brows = [{"date": d, "code": c, "side": "B" if n > 0 else "S", "rank": 1, "bid": b, "broker": f"分點{b}",
                  "buy": max(n, 0), "sell": max(-n, 0), "net": n, "pct": n / 10} for c, b, n in net[d]]
        _w(tmp / "broker" / d[:4] / f"{stem}.csv", BCOLS, brows)
        _w(tmp / "broker" / d[:4] / f"{stem}_total.csv", TCOLS,
           [{"date": d, "code": c, "buy_total": 1, "sell_total": 1, "buy_cost": 1, "sell_cost": 1} for c in codes])
    return days, codes


class ForwardTest(unittest.TestCase):
    def test_entry_next_open_minus_market(self):
        days = ["d0", "d1", "d2"]
        px = {"1101": {"d0": (10, 10, 0, 1, 1), "d1": (11, 12, 0.2, 1, 1), "d2": (12, 13.2, 0.1, 1, 1)}}
        bm = {"d0": (0, 0), "d1": (0.01, 0.0), "d2": (0, 0.02)}
        # 隔天開盤 11 買 → 收 12（+9.09%）→ 再漲 10%；大盤 1.01 × 1.02
        x = S.forward_excess(days, px, bm, "1101", 0, 2)
        self.assertAlmostEqual(x, 12 / 11 * 1.1 - 1.01 * 1.02)
        self.assertIsNone(S.forward_excess(days, px, bm, "1101", 1, 2))   # 還沒到期
        self.assertIsNone(S.forward_excess(days, {"1101": {"d0": px["1101"]["d0"]}}, bm, "1101", 0, 1))  # 停牌

    def test_dedup_within_horizon(self):
        ev = [(0, "A", "1101", 5, 1), (1, "A", "1101", 5, 1), (5, "A", "1101", 5, 1), (1, "A", "1101", -5, -1)]
        self.assertEqual([e[0] for e in S.dedup(ev, 5)], [0, 5, 1])


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.days, self.codes = build(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def rows(self, res):
        return {r["bid"]: r for r in res["rows"]}

    def test_classes(self):
        res = S.score(self.tmp, horizons=(1, 5), main=5)
        r = self.rows(res)
        self.assertEqual(r[SMART]["class"], S.CLASS_SMART)
        self.assertEqual(r[SMART]["n5"], 20)
        self.assertGreater(r[SMART]["ex5"], 0.07)
        self.assertEqual(r[DT]["class"], S.CLASS_DT)
        self.assertAlmostEqual(r[DT]["flip_ratio"], 1.0)
        self.assertAlmostEqual(r[DT]["buy_day_ret"], 0.05, places=3)
        for b in NOISE:
            self.assertEqual(r[b]["class"], S.CLASS_NORMAL)
            self.assertEqual(r[b]["flip_ratio"], 0.0)   # 隔天看得到、沒有賣

    def test_as_of_does_not_peek(self):
        res = S.score(self.tmp, horizons=(5,), main=5, as_of=self.days[8])
        r = self.rows(res)[SMART]
        self.assertEqual(r["n5"], 4)          # 只有第 0–3 天的買超已經過了 5 天
        self.assertEqual(r["class"], S.CLASS_FEW)
        self.assertEqual(res["as_of"], self.days[8])

    def test_min_days(self):
        res = S.score(self.tmp, horizons=(5,), main=5, min_days=25)
        self.assertEqual(self.rows(res)[SMART]["class"], S.CLASS_FEW)

    def test_signals_and_write(self):
        res = S.score(self.tmp, horizons=(5,), main=5)
        sig = S.signals(res, self.days[19])
        smart = [s for s in sig if s["smart_pct"]]
        self.assertEqual([s["code"] for s in smart], [self.codes[19]])
        self.assertAlmostEqual(smart[0]["smart_pct"], 10.0)
        dt = [s for s in sig if s["daytrade_pct"] > 0]
        self.assertEqual([s["code"] for s in dt], [self.codes[69]])
        bp, sp, _ = S.write(res, self.tmp / "out")
        with bp.open(encoding="utf-8") as fp:
            head = next(csv.reader(fp))
        self.assertEqual(head[:3], ["bid", "branch", "class"])
        self.assertIn("days5", head)

    def test_flip_unobserved(self):
        net = {("d0", "A", "1101"): 100}
        e = (0, "A", "1101", 100, 10.0)
        self.assertIsNone(S.flip_ratio(e, ["d0", "d1"], net, set()))
        self.assertEqual(S.flip_ratio(e, ["d0", "d1"], net, {("s", "d1", "1101")}), 0.0)
        self.assertEqual(S.flip_ratio(e, ["d0", "d1"], net, {("w", "d1", "A")}), 0.0)
        net[("d1", "A", "1101")] = -30
        self.assertAlmostEqual(S.flip_ratio(e, ["d0", "d1"], net, set()), 0.3)

    def test_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(S.score(Path(d))["rows"], [])


if __name__ == "__main__":
    unittest.main()


class BackfillTest(unittest.TestCase):
    def test_newest_first_and_stop_when_empty(self):
        import backfill_broker as B
        import fetch_broker as F
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            days = weekdays(10)
            for x in days:
                _w(d / x[:4] / f"{x.replace('-', '')}.csv", PCOLS, [])
            _w(d / "broker" / days[-1][:4] / f"{days[-1].replace('-', '')}.csv", BCOLS, [])
            called = []

            def fake_main(argv):
                x = argv[1]
                called.append(x)
                if x >= days[5]:   # 只有比較近的日期有資料
                    rp, _ = F.out_paths(x)
                    _w(rp, BCOLS, [{"date": x, "code": "2330", "side": "B", "rank": 1, "bid": "9800",
                                    "broker": "元大", "buy": 1, "sell": 0, "net": 1, "pct": 1}])
                return 0

            old = (F.DATA, F.OUT, F.main)
            F.DATA, F.OUT, F.main = d, d / "broker", fake_main
            try:
                B.main(["--start", days[0]])
            finally:
                F.DATA, F.OUT, F.main = old
            self.assertEqual(called[:4], [days[8], days[7], days[6], days[5]])
            self.assertEqual(called[4:], [days[4], days[3], days[2]])   # 連續 3 天沒資料就停
