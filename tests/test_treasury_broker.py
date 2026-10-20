import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_treasury_broker as F  # noqa: E402
import treasury_broker as T  # noqa: E402


def prog(code, board, start, end, bought, done="Y"):
    return {"market": "sii", "code": code, "name": code, "board_date": board, "start": start, "end": end,
            "done": done, "bought_shares": str(bought) if bought != "" else "", "plan_shares": "1000000"}


def rows(code, board, win, d1, d2, items):
    out = []
    for i, (bid, name, buy, sell) in enumerate(items, 1):
        out.append({"market": "sii", "code": code, "board_date": board, "win": win, "d1": d1, "d2": d2,
                    "rank": str(i), "bid": bid, "broker": name, "buy": str(buy), "sell": str(sell), "net": str(buy - sell)})
    return out


def day(code, board, bid, n, b, s):
    return {"market": "sii", "code": code, "board_date": board, "bid": bid, "days": str(n), "buy_days": str(b),
            "sell_days": str(s)}


class MatchTest(unittest.TestCase):
    def test_daily_consistency(self):
        # 兩個分點買超都夠，但 A 買賣日交錯（一般客戶），B 天天買（公司派）
        p = [prog("1111", "2026-05-01", "2026-05-04", "2026-07-03", 1000000)]
        b = rows("1111", "2026-05-01", "in", "2026-05-04", "2026-07-03", [("A", "交錯", 1500, 300), ("B", "天天買", 1000, 20)])
        d = [day("1111", "2026-05-01", "A", 40, 20, 18), day("1111", "2026-05-01", "B", 40, 37, 2)]
        m = T.build(p, b, d)[0]["1111|2026-05-01"]
        self.assertEqual([x[1] for x in m["m"]], ["天天買"])
        self.assertEqual((m["conf"], m["m"][0][5:]), ("高", [40, 37, 2]))

    def test_over_bought_still_counts(self):
        # 買超 1,400 張 > 實際買回 1,000 張也算「高」（同分點還有其他買盤）
        p = [prog("1111", "2026-05-01", "2026-05-04", "2026-07-03", 1000000)]
        b = rows("1111", "2026-05-01", "in", "2026-05-04", "2026-07-03", [("B", "公司派", 1450, 50)])
        m = T.build(p, b, [day("1111", "2026-05-01", "B", 40, 36, 3)])[0]["1111|2026-05-01"]
        self.assertEqual((m["conf"], m["cov"]), ("高", 1.4))

    def test_two_branches(self):
        # 可成 2026-08：實際買回 32,145 張（富邦網站實測的區間買超）
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 32145000)]
        b = rows("2474", "2026-08-07", "in", "2026-08-10", "2026-10-06",
                 [("9800", "元大證券", 26477, 4815), ("700I", "兆豐-北高雄", 9960, 84),
                  ("9268", "凱基-台北", 8006, 5725), ("1470", "台灣摩根士丹利", 6565, 4482)])
        brk, co = T.build(p, b)
        m = brk["2474|2026-08-07"]
        self.assertEqual([x[1] for x in m["m"]], ["元大證券", "兆豐-北高雄"])
        self.assertEqual(m["conf"], "中")  # 還沒有每日資料，最高只到「中」
        self.assertAlmostEqual(m["cov"], 31538 / 32145, places=3)
        self.assertEqual([a[1] for a in co["2474"]], ["元大證券", "兆豐-北高雄"])

    def test_stops_when_enough(self):
        # 力成：群益金鼎-新竹 9,977 張 ≈ 10,000，已經夠了，大和國泰不納入
        p = [prog("6239", "2026-08-07", "2026-08-10", "2026-09-30", 10000000)]
        b = rows("6239", "2026-08-07", "in", "2026-08-10", "2026-09-30",
                 [("9186", "群益金鼎-新竹", 10234, 257), ("8890", "大和國泰", 4608, 754), ("9200", "凱基", 7473, 4867)])
        m = T.build(p, b)[0]["6239|2026-08-07"]
        self.assertEqual([x[1] for x in m["m"]], ["群益金鼎-新竹"])

    def test_pre_window_excludes_regular_buyer(self):
        p = [prog("1111", "2026-05-01", "2026-05-04", "2026-07-03", 1000000)]
        b = rows("1111", "2026-05-01", "in", "2026-05-04", "2026-07-03", [("A", "常客", 1000, 10)]) + \
            rows("1111", "2026-05-01", "pre", "2026-03-05", "2026-05-03", [("A", "常客", 900, 10)])
        self.assertEqual(T.build(p, b)[0], {})

    def test_pre_window_kept_when_back_to_back(self):
        # 連續買回：前 60 天落在上一次買回期間，公司派分點本來就在買，不能排除
        p = [prog("1111", "2026-05-01", "2026-05-04", "2026-07-03", 1000000),
             prog("1111", "2026-02-20", "2026-02-23", "2026-04-22", 900000)]
        b = rows("1111", "2026-05-01", "in", "2026-05-04", "2026-07-03", [("A", "公司派", 1000, 10)]) + \
            rows("1111", "2026-05-01", "pre", "2026-03-05", "2026-05-03", [("A", "公司派", 900, 10)])
        brk, co = T.build(p, b, [day("1111", "2026-05-01", "A", 40, 38, 1)])
        self.assertEqual(brk["1111|2026-05-01"]["conf"], "高")

    def test_live_uses_known_branches(self):
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 10000000),
             prog("2474", "2026-10-15", "2026-10-16", "2026-12-15", "", done="N")]
        b = rows("2474", "2026-08-07", "in", "2026-08-10", "2026-10-06", [("700I", "兆豐-北高雄", 10000, 10)]) + \
            rows("2474", "2026-10-15", "in", "2026-10-16", "2026-10-19",
                 [("X", "某分點", 500, 50), ("700I", "兆豐-北高雄", 300, 0), ("Y", "疑似", 200, 0)])
        d = [day("2474", "2026-10-15", b_, 2, 2, 0) for b_ in ("X", "700I", "Y")]
        live = T.build(p, b, d)[0]["2474|2026-10-15"]["live"]
        self.assertEqual(live[0], ["700I", "兆豐-北高雄", 300, 300, 0, 2, 2, 0, 1])
        self.assertEqual([x[1] for x in live[1:]], ["某分點", "疑似"])


class DailyTest(unittest.TestCase):
    def test_parse_and_summarize(self):
        page = ("<table><tr><td class='t3n0'>2026/10/06</td><td>469</td><td>30</td><td>499</td><td>439</td></tr>"
                "<tr><td>2026/10/05</td><td>1,729</td><td>64</td><td>1,793</td><td>1,665</td></tr>"
                "<tr><td>2026/10/02</td><td>3</td><td>73</td><td>76</td><td>-70</td></tr>"
                "<tr><td>2026/10/01</td><td>0</td><td>0</td><td>0</td><td>0</td></tr></table>")
        d = F.parse_daily(page)
        self.assertEqual(d[1], ("2026-10-05", 1729, 64))
        self.assertEqual(F.summarize(d), {"days": 3, "buy_days": 2, "sell_days": 1, "buy": 2201, "sell": 167, "net": 2034})

    def test_day_jobs(self):
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 10000000)]
        b = rows("2474", "2026-08-07", "in", "2026-08-10", "2026-10-06", [("A", "a", 5000, 10), ("B", "b", 500, 10)])
        j = F.day_jobs(p, b, {})
        self.assertEqual([r["bid"] for _, r in j], ["A"])  # B 買超不到實際張數 10%
        self.assertEqual(F.day_jobs(p, b, {("sii", "2474", "2026-08-07", "A"): "2026-10-06"}), [])


class JobsTest(unittest.TestCase):
    def test_jobs(self):
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 10000000),
             prog("1111", "2026-08-01", "2026-08-03", "2026-10-02", 0),
             prog("2222", "2026-10-15", "2026-10-16", "2026-12-15", "", done="N")]
        have = {("sii", "2474", "2026-08-07", "in"): "2026-10-06"}
        j = [(x[0]["code"], x[1], x[2], x[3]) for x in F.jobs(p, have, "2026-10-19")]
        self.assertEqual(j, [("2222", "in", "2026-10-16", "2026-10-19"), ("2222", "pre", "2026-08-17", "2026-10-15"),
                             ("2474", "pre", "2026-06-11", "2026-08-09")])


if __name__ == "__main__":
    unittest.main()
