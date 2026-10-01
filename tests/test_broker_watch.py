import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_broker_watch as W  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return (FIX / name).read_bytes().decode("cp950", errors="replace")


class WatchTest(unittest.TestCase):
    def test_branch_list_and_resolve(self):
        br = W.parse_branch_list(load("zbrokerjs.djjs"))
        self.assertGreater(len(br), 800)
        ok, missing = W.resolve([{"label": "康和總公司", "branch": "康和總公司"},
                                 {"label": "永豐金內湖", "branch": "永豐金-內湖"},
                                 {"label": "x", "branch": "不存在-分點"}], br)
        self.assertEqual([(b["hq"], b["bid"]) for b in ok], [("8450", "8450"), ("9A00", "9A9g")])
        self.assertEqual(len(missing), 1)
        self.assertEqual(W.enc("9A9g"), "0039004100390067")
        self.assertEqual(W.dec("0039004100390067"), "9A9g")

    def test_parse_amount_and_shares(self):
        d, amt = W.parse_zgb(load("zgb_9801_B.html"))
        self.assertEqual(d, "2026-09-30")
        self.assertEqual(len(amt), 100)
        self.assertEqual(amt["1301"], ("台塑", 171817, 1656))
        self.assertEqual(amt["00631L"][0], "元大台灣50正2")
        _, sh = W.parse_zgb(load("zgb_9801_E.html"))
        rows = W.branch_rows("2026-09-30", {"bid": "9801", "branch": "元大-松江"}, amt, sh)
        r = next(x for x in rows if x["code"] == "1301")
        self.assertEqual((r["net_amt"], r["net_sh"]), (170161, 2503))

    def test_not_ready(self):
        d, rows = W.parse_zgb(load("zgb_nodata.html"))
        self.assertIsNone(d)
        self.assertEqual(rows, {})

    def test_backfill_only_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            old = (W.DATA, W.OUT, W.CONFIG, W.BRANCHES, W.fetch, W.load_branches, W.DELAY)
            W.DATA, W.OUT = tmp, tmp / "broker" / "watch"
            W.CONFIG = tmp / "watch.csv"
            W.CONFIG.write_text("label,branch\n元大松江,元大-松江\n", encoding="utf-8")
            (tmp / "2026").mkdir()
            for d in ("20260929", "20260930"):
                (tmp / "2026" / f"{d}.csv").write_text("code\n", encoding="utf-8")
            calls = []
            amt = W.parse_zgb(load("zgb_9801_B.html"))[1]

            def fake(hq, bid, kind, date):
                calls.append((bid, kind, date))
                return date, amt
            W.fetch, W.DELAY = fake, 0
            W.load_branches = lambda refresh=True: W.parse_branch_list(load("zbrokerjs.djjs"))
            try:
                self.assertEqual(W.main(["--days", "2"]), 0)
                self.assertEqual(len(calls), 4)
                W.CONFIG.write_text("label,branch\n元大松江,元大-松江\n凱基三多,凱基-三多\n", encoding="utf-8")
                calls.clear()
                self.assertEqual(W.main(["--days", "2"]), 0)
                self.assertEqual({c[0] for c in calls}, {"9275"})  # 只回補新加的分點
            finally:
                W.DATA, W.OUT, W.CONFIG, W.BRANCHES, W.fetch, W.load_branches, W.DELAY = old


if __name__ == "__main__":
    unittest.main()


class WatchSiteTest(unittest.TestCase):
    def test_config_order_and_filter(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import broker_site as S
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "config").mkdir()
            (tmp / "config" / "broker_watch.csv").write_text("label,branch\n凱基三多,凱基-三多\n康和總公司,康和\n", encoding="utf-8")
            d = tmp / "data" / "broker" / "watch" / "2026"
            d.mkdir(parents=True)
            (d / "20260930.csv").write_text(
                "date,bid,branch,code,name,buy_amt,sell_amt,net_amt,buy_sh,sell_sh,net_sh\n"
                "2026-09-30,8450,康和,2330,台積電,100,50,50,1,0,1\n"
                "2026-09-30,9275,凱基-三多,1709,和益,200,0,200,,,\n"
                "2026-09-30,9801,元大-松江,1301,台塑,300,0,300,3,0,3\n", encoding="utf-8")
            j = S.build_watch(tmp / "data", tmp)
            self.assertEqual([b["label"] for b in j["branches"]], ["凱基三多", "康和總公司"])
            self.assertEqual(len(j["rows"]), 2)  # 元大松江已從設定刪除，不輸出
            self.assertIn([0, 0, "1709", 200, 0, None, None], j["rows"])
