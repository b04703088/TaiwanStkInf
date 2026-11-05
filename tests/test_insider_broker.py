import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_insider_broker as F  # noqa: E402
import insider_broker as IB  # noqa: E402


def tr(month, code, buy=0, sell=0, dup=""):
    return {"month": month, "market": "sii", "code": code, "buy_mkt": str(buy), "sell_mkt": str(sell), "dup": dup}


def br(kind, code, ref, d, lots, win, side, rank, bid, buy, sell, d1="2026-09-01", d2="2026-09-30"):
    return {"kind": kind, "market": "sii", "code": code, "ref": ref, "dir": d, "lots": str(lots), "win": win,
            "d1": d1, "d2": d2, "side": side, "rank": str(rank), "bid": bid, "broker": "分點" + bid,
            "buy": str(buy), "sell": str(sell), "net": str(buy - sell)}


def day(kind, code, ref, bid, days, bd, sd, bn, sn):
    return {"kind": kind, "code": code, "ref": ref, "bid": bid, "days": str(days), "buy_days": str(bd),
            "sell_days": str(sd), "buy_net": str(bn), "sell_net": str(sn)}


class JobsTest(unittest.TestCase):
    def test_month_jobs(self):
        trades = [tr("2026-09", "1111", sell=500000), tr("2026-09", "1111", sell=500000, dup="甲"),
                  tr("2026-09", "2222", buy=50000),                      # 太少
                  tr("2026-09", "3333", buy=300000, sell=250000),        # 買賣互抵，不是一面倒
                  tr("2026-09", "4444", buy=200000)]
        pers = F.periods([{"market": "sii", "code": "1111", "method": "一般交易(每日得轉讓股數限制)", "shares": "800000",
                           "period": "1150910~1151009", "date": "2026-09-07"},
                          {"market": "sii", "code": "1111", "method": "信託", "shares": "1",
                           "period": "1150901~1150902", "date": "2026-09-01"}])
        js = {j["code"]: j for j in F.month_jobs(trades, pers, "2026-11-05")}
        self.assertEqual(set(js), {"1111", "4444"})
        self.assertEqual((js["1111"]["dir"], js["1111"]["lots"], js["1111"]["d1"], js["1111"]["d2"]),
                         ("S", 500, "2026-09-10", "2026-09-30"))   # dup 列不加總；縮到申報期間
        self.assertEqual((js["4444"]["dir"], js["4444"]["d1"]), ("B", "2026-09-01"))

    def test_live_jobs(self):
        pers = F.periods([{"market": "otc", "code": "5555", "method": "一般交易", "shares": "600000",
                           "period": "1151020~1151119", "date": "2026-10-17"},
                          {"market": "sii", "code": "6666", "method": "一般交易", "shares": "600000",
                           "period": "1150901~1150930", "date": "2026-08-28"}])   # 早就結束
        js = F.live_jobs(pers, "2026-11-05")
        self.assertEqual([(j["code"], j["d1"], j["d2"], j["lots"]) for j in js], [("5555", "2026-10-20", "2026-11-05", 600)])


class MatchTest(unittest.TestCase):
    def test_sell_match(self):
        rows = [br("m", "1111", "2026-09", "S", 500, "in", "S", 1, "A", 20, 520),       # 一面倒賣 500
                br("m", "1111", "2026-09", "S", 500, "in", "S", 2, "B", 900, 1300),     # 買賣都多
                br("m", "1111", "2026-09", "S", 500, "in", "B", 1, "C", 800, 10),
                br("m", "1111", "2026-09", "S", 500, "pre", "S", 1, "B", 0, 600, "2026-08-01", "2026-08-31")]
        days = [day("m", "1111", "2026-09", "A", 15, 1, 14, 3, 503)]
        res = IB.build(rows, days)
        m = res["match"]["1111|2026-09"]
        self.assertEqual(m["conf"], "高")
        self.assertEqual([e[0] for e in m["m"]], ["A"])
        self.assertEqual(m["m"][0][2:5], [500, 520, 20])
        self.assertEqual(res["known"]["1111"][0][:4], ["A", "分點A", 1, 0])

    def test_oversized_is_low(self):
        rows = [br("m", "2222", "2026-09", "B", 100, "in", "B", 1, "X", 500, 50)]
        m = IB.build(rows)["match"]["2222|2026-09"]
        self.assertEqual((m["conf"], m["cov"]), ("低", 4.5))

    def test_live_progress(self):
        rows = [br("m", "1111", "2026-09", "S", 500, "in", "S", 1, "A", 0, 500),
                br("t", "1111", "2026-10-20", "S", 1000, "in", "S", 1, "A", 5, 405, "2026-10-20", "2026-11-05"),
                br("t", "1111", "2026-10-20", "S", 1000, "in", "S", 2, "Z", 0, 300, "2026-10-20", "2026-11-05")]
        days = [day("m", "1111", "2026-09", "A", 10, 0, 10, 0, 500),
                day("t", "1111", "2026-10-20", "Z", 8, 0, 8, 0, 300)]
        res = IB.build(rows, days)
        lv = res["live"][0]
        self.assertEqual(lv["known"], [["A", "分點A", 400, 1]])
        self.assertEqual(lv["prog"], 0.4)
        self.assertEqual([e[0] for e in lv["sus"]], ["Z"])
        rc = IB.recent(res["known"], [{"code": "1111", "bid": "A", "broker": "分點A", "net": "-30", "date": "2026-11-04"},
                                      {"code": "1111", "bid": "Q", "broker": "x", "net": "9", "date": "2026-11-04"}])
        self.assertEqual(rc, {"1111": [["A", "分點A", -30, 1, "2026-11-04"]]})


if __name__ == "__main__":
    unittest.main()
