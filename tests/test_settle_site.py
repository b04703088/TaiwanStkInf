import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import settle_site as S  # noqa: E402
import fetch_futures as F  # noqa: E402


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)


PX = ["date", "market", "code", "name", "open", "high", "low", "close", "change", "volume", "value", "transactions"]
CH = ["date", "market", "code", "name", "f_net", "fd_net", "t_net", "d_net", "inst_net", "sbl_sell", "sbl_ret", "sbl_bal",
      "dt_vol", "dt_buy", "dt_sell"]
DAYS = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]


class SettleSiteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        write(d / "futures" / "stk_list.csv", ["product", "name", "code", "size"],
              [["CD", "台積電", "2330", "2000"], ["QF", "台積電", "2330", "100"]])
        stk, px = [], []
        for i, day in enumerate(DAYS):
            m = "202610" if day < "2026-10-21" else "202611"
            # 一般股期空單每天加 100 口（=200 張），小型 1000 口（=100 張）
            stk.append([day, "CD", m, "10", str(1000 + 100 * i), "2000"])
            stk.append([day, "QF", m, "0", "1000", "3000"])
            px.append([day, "CD", "CDF", "101", "101", "10", "2000"])   # 期貨 101 vs 現貨 100 → 正價差 1%
            ymd = day.replace("-", "")
            write(d / ymd[:4] / f"{ymd}.csv", PX, [[day, "TWSE", "2330", "台積電", "", "", "", "100", "1", "1100000", "", ""]])
            write(d / "chips" / ymd[:4] / f"{ymd}.csv", CH,
                  [[day, "TWSE", "2330", "台積電", "", "", "", "50000", "", "", "", "", "100000", "", ""]])
        write(d / "futures" / "stk" / "2026.csv", F.STK_COLS, stk)
        write(d / "futures" / "stk_px" / "2026.csv", F.PX_COLS, px)
        self.d = d

    def tearDown(self):
        self.tmp.cleanup()

    def test_build(self):
        p = S.build(self.d)
        self.assertEqual(p["date"], "2026-10-30")
        self.assertEqual(p["last_settle"], "2026-10-21")
        self.assertEqual(p["cycle_start"], "2026-10-22")
        r = dict(zip(p["cols"], p["rows"][0]))
        # 空單：一般 1600 口 × 2 張 + 小型 1000 口 × 0.1 張 = 3300 張；近 5 日量扣當沖 = 5 × 1000 張
        self.assertEqual(r["s10"], 3300)
        self.assertAlmostEqual(r["s_r"], 0.66)
        self.assertEqual(r["d_cum"], 250)        # 週期 5 天 × 50 張
        self.assertEqual(r["basis"], 1.0)
        self.assertEqual(r["pos_days"], 5)
        self.assertEqual(r["d_buy_pos"], r["d_buy"])
        self.assertEqual(r["s_add"], 1000)       # 10/21 → 10/30 空單加 500 口 = 1000 張
        self.assertEqual(r["s_add_pos"], 1000)
        self.assertEqual(len(p["detail"]["2330"]), 5)

    def test_parse_stk_px(self):
        def row(c, m, sess="一般", close="10"):
            return ["2026/10/30", c, m, "", "", "", close, "", "", "5", "10", "7", "", "", "", "", "", sess, ""]
        rows = [row("TX", "202611"), row("TX", "202612"), row("CDF", "202611"), row("CDF", "202612"),
                row("CD1", "202611"), row("CDF", "202611", "盤後"), row("QFF", "202611")]
        out = F.parse_stk_px(rows)
        self.assertEqual(sorted((r["product"], r["contract"]) for r in out), [("CD", "CDF"), ("QF", "QFF")])


if __name__ == "__main__":
    unittest.main()
