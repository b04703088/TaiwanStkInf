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


class MatchTest(unittest.TestCase):
    def test_two_branches(self):
        # 可成 2026-08：實際買回 32,145 張（富邦網站實測的區間買超）
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 32145000)]
        b = rows("2474", "2026-08-07", "in", "2026-08-10", "2026-10-06",
                 [("9800", "元大證券", 26477, 4815), ("700I", "兆豐-北高雄", 9960, 84),
                  ("9268", "凱基-台北", 8006, 5725), ("1470", "台灣摩根士丹利", 6565, 4482)])
        brk, co = T.build(p, b)
        m = brk["2474|2026-08-07"]
        self.assertEqual([x[1] for x in m["m"]], ["元大證券", "兆豐-北高雄"])
        self.assertEqual(m["conf"], "高")
        self.assertAlmostEqual(m["cov"], 31538 / 32145, places=3)
        self.assertEqual([a[1] for a in co["2474"]], ["元大證券", "兆豐-北高雄"])

    def test_cap_skips_too_big(self):
        # 力成：群益金鼎-新竹 9,977 張 ≈ 10,000；大和國泰再加就超過 115%，不納入
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
        brk, co = T.build(p, b)
        self.assertEqual(brk["1111|2026-05-01"]["conf"], "高")

    def test_live_uses_known_branches(self):
        p = [prog("2474", "2026-08-07", "2026-08-10", "2026-10-06", 10000000),
             prog("2474", "2026-10-15", "2026-10-16", "2026-12-15", "", done="N")]
        b = rows("2474", "2026-08-07", "in", "2026-08-10", "2026-10-06", [("700I", "兆豐-北高雄", 10000, 10)]) + \
            rows("2474", "2026-10-15", "in", "2026-10-16", "2026-10-19",
                 [("X", "某分點", 500, 50), ("700I", "兆豐-北高雄", 300, 0), ("Y", "疑似", 200, 0)])
        live = T.build(p, b)[0]["2474|2026-10-15"]["live"]
        self.assertEqual(live[0], ["700I", "兆豐-北高雄", 300, 300, 0, 1])
        self.assertEqual([x[1] for x in live[1:]], ["某分點", "疑似"])


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
