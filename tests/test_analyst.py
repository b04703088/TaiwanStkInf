import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_analyst as A  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "analyst"
NAMES = {"台積電": "2330", "台塑": "1301", "國巨": "2327", "聯亞": "3081", "前鼎": "4908", "台達電": "2308", "台光電": "2383", "台燿": "6274", "南亞": "1303", "友達": "2409", "聯電": "2303",
         "緯創": "3231", "鴻海": "2317", "仁寶": "2324", "華通": "2313", "台化": "1326", "世界": "5347",
         "兆豐金": "2886", "新興": "2605", "群創": "3481", "台塑化": "6505", "頎邦": "6147", "臻鼎-KY": "4958"}


class Fixture:
    @classmethod
    def setUpClass(cls):
        cls.items = {x["newsId"]: x for x in json.loads((FIX / "news.json").read_text(encoding="utf-8"))}

    def reports(self, nid):
        return [(r["broker"], r["code"], r["action"], r["rating"], r["target"], r["prev_target"])
                for r in A.parse_reports(self.items[nid], NAMES)]


class ReportTest(Fixture, unittest.TestCase):
    def test_tp_raise_with_previous(self):
        # 「目標價由3100元新台幣調升至3300元」「重申台積電「買進」投資評等」
        self.assertEqual(self.reports(6622317), [("高盛", "2330", "up", "買進", 3300.0, 3100.0)])
        self.assertEqual(self.reports(6622299), [("高盛", "2330", "up", "買進", 3300.0, 3100.0)])

    def test_two_stocks_two_targets(self):
        # 「高盛維持台光電與台燿「買進」評等，並進一步調升目標價至10,200元及3,010元」
        self.assertEqual(sorted(self.reports(6620346)), [("高盛", "2383", "up", "買進", 10200.0, None),
                                                         ("高盛", "6274", "up", "買進", 3010.0, None)])

    def test_generic_foreign_with_target_skips_eps(self):
        # 同句先講 EPS 數字再講目標價：只取「目標價」之後的價格
        self.assertEqual(self.reports(6622648), [("外資", "2383", "up", "", 10000.0, None)])

    def test_flows_are_not_ratings(self):
        # 外資買賣超新聞（加碼、減碼 N 張）不是評等
        for nid in (6621785, 6620533, 6618794):
            self.assertEqual(self.reports(nid), [], nid)

    def test_non_taiwan_or_non_report(self):
        self.assertEqual(self.reports(6620238), [])   # 高盛是 ETF 成分股（公司債發行人）
        self.assertEqual(self.reports(6623451), [])   # 花旗建議買三星（韓股）
        self.assertEqual(self.reports(6622587), [])   # 大摩「增持」輝達（美股）

    def test_group_targets_paired_by_name(self):
        # 「目標價定為台塑 60 元、台化 60 元、台塑化 65 元、南亞 200 元」，標題「小摩調升」
        self.assertEqual(sorted(self.reports(6532284)), [
            ("摩根大通", "1301", "up", "加碼", 60.0, None), ("摩根大通", "1303", "up", "加碼", 200.0, None),
            ("摩根大通", "1326", "up", "加碼", 60.0, None), ("摩根大通", "6505", "up", "加碼", 65.0, None)])

    def test_stock_price_after_target_is_not_target(self):
        # 「外資調高目標價至 3,165 元激勵下…股價觸及 2,600 元新天價，也領前鼎…」
        self.assertEqual(self.reports(6422903), [("外資", "3081", "up", "", 3165.0, None)])

    def test_broker_summary_article(self):
        self.assertEqual(sorted(self.reports(6537278)), [("美銀", "2330", "up", "買進", 3100.0, None),
                                                         ("花旗", "2330", "up", "", 3800.0, 2875.0)])

    def test_vague_scenario_and_columns(self):
        self.assertEqual(self.reports(6193906), [])   # 八大外資「目標價最高喊到 1800 元」
        self.assertEqual(self.reports(6532794), [])   # 【量大強漲股整理】專欄
        self.assertEqual(self.reports(6225388), [])   # 專家觀點
        # 「最樂觀情境下目標價上看 2075 元，維持優於大盤」：只留評等
        self.assertEqual(self.reports(6545955), [("美系外資", "2327", "maintain", "加碼", None, None)])

    def test_factset_excluded_from_reports(self):
        self.assertEqual(self.reports(6623548), [])


class FactsetTest(Fixture, unittest.TestCase):
    def test_eps(self):
        r = A.parse_factset(self.items[6623551])
        self.assertEqual((r["code"], r["name"], r["kind"], r["year"], r["analysts"]), ("4958", "臻鼎-KY", "eps", "2026", "8"))
        self.assertEqual((r["prev"], r["value"], r["high"], r["low"], r["target"]), (14.05, 13.79, 16.18, 11.51, 644.0))
        self.assertEqual(r["chg_pct"], -1.85)

    def test_eps_negative_low(self):
        r = A.parse_factset(self.items[6621407])
        self.assertEqual(r["kind"], "eps")
        self.assertLess(r["low"], 0)

    def test_target_price(self):
        r = A.parse_factset(self.items[6623548])
        self.assertEqual((r["code"], r["kind"], r["prev"], r["value"], r["chg_pct"], r["high"], r["low"]),
                         ("6147", "tp", 260.0, 270.0, 3.85, 290.0, 225.0))
        self.assertEqual((r["bull"], r["neutral"], r["bear"], r["close"]), ("5", "1", "0", 234.5))
        r = A.parse_factset(self.items[6623176])
        self.assertEqual((r["code"], r["prev"], r["value"]), ("1303", 295.0, 320.0))

    def test_all_factset_parse(self):
        for nid, it in self.items.items():
            if A.is_factset(it):
                self.assertIsNotNone(A.parse_factset(it), nid)


class HelperTest(unittest.TestCase):
    def test_brokers(self):
        self.assertEqual(A.find_brokers("大摩與小摩同步調升"), ["摩根士丹利", "摩根大通"])
        self.assertEqual(A.find_brokers("美銀美林重申買進"), ["美銀"])
        self.assertEqual(A.find_brokers("野村投信旗下ETF"), [])
        self.assertEqual(A.find_brokers("外資今天買超台積電"), [])
        self.assertEqual(A.find_brokers("美系外資高盛指出"), ["高盛"])
        self.assertEqual(A.find_brokers("美系外資最新報告"), ["美系外資"])

    def test_rating(self):
        self.assertEqual(A.find_rating("維持「優於大盤」評等"), "加碼")
        self.assertEqual(A.find_rating("評級調降至「中立」"), "中立")
        self.assertEqual(A.find_rating("外資加碼1.3萬張"), "")
        self.assertEqual(A.find_rating("給予 Overweight 評級"), "加碼")

    def test_targets(self):
        tp = lambda s: (lambda p, v: (p, [x for _, x in v]))(*A.find_targets(s))
        self.assertEqual(tp("目標價由新台幣3,100元上調至3,300元"), (3100.0, [3300.0]))
        self.assertEqual(tp("目標價350美元"), (None, []))
        self.assertEqual(tp("EPS 20元，目標價上看800元"), (None, [800.0]))
        self.assertEqual(tp("目標價調高至3,165元激勵下，今日股價觸及2,600元新天價"), (None, [3165.0]))
        self.assertEqual(tp("目標價定為台塑 60 元、 台化 60 元、台塑化 65 元、南亞 200 元"), (None, [60.0, 60.0, 65.0, 200.0]))

    def test_pairing_by_nearest_name(self):
        s = "小摩目標價定為台塑 60 元、 台化 60 元、台塑化 65 元、南亞 200 元"
        st = A.find_stocks(s, set(), {"台塑": "1301", "台化": "1326", "台塑化": "6505", "南亞": "1303"})
        prev, vals = A.find_targets(s)
        got = {x[1]: v for x, v in A.pair_targets(st, vals, s, prev)}
        self.assertEqual(got, {"1301": 60.0, "1326": 60.0, "6505": 65.0, "1303": 200.0})

    def test_multi_broker_sentence(self):
        it = {"newsId": 1, "publishAt": 1791000000, "title": "測試", "market": [{"code": "2330", "symbol": "TWS:2330:STOCK"}],
              "content": "<p>花旗證券及大摩將台積電目標價從1388元上調到1588元，甚至高盛證券將目標價從1370元調高到1600元。</p>"
                         "<p>包括摩根士丹利、瑞銀等外資全數喊買台積電，目標價最高喊到1800元。</p>"}
        got = sorted((r["broker"], r["target"], r["prev_target"], r["action"]) for r in A.parse_reports(it, NAMES))
        self.assertEqual(got, [("摩根士丹利", 1588.0, 1388.0, "up"), ("花旗", 1588.0, 1388.0, "up"), ("高盛", 1600.0, 1370.0, "up")])

    def test_two_char_name_boundary(self):
        self.assertEqual([c for _, c, _ in A.find_stocks("布局東南亞，外資目標價350元", set(), NAMES)], [])
        self.assertEqual([c for _, c, _ in A.find_stocks("外資將南亞目標價調升至350元", set(), NAMES)], ["1303"])


class MergeTest(unittest.TestCase):
    def test_refetch_replaces_same_day(self):
        with tempfile.TemporaryDirectory() as d:
            old = A.OUT
            A.OUT = Path(d)
            try:
                row = {"date": "2026-10-06", "time": "10:00", "news_id": 1, "code": "2330", "broker": "高盛", "target": 3300.0}
                self.assertEqual(A.merge("reports", A.REPORT_COLS, [row], lambda r: (str(r["news_id"]), r["code"], r["broker"])), 1)
                self.assertEqual(A.merge("reports", A.REPORT_COLS, [row], lambda r: (str(r["news_id"]), r["code"], r["broker"])), 0)
                rows = A.load_csv(Path(d) / "reports_2026.csv")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["target"], "3300")
                # 重抓同一天、這次沒有任何一列（例如規則改了被排除）→ 舊列要拿掉
                A.merge("reports", A.REPORT_COLS, [], lambda r: (str(r["news_id"]), r["code"], r["broker"]), ["2026-10-06"])
                self.assertEqual(A.load_csv(Path(d) / "reports_2026.csv"), [])
            finally:
                A.OUT = old


if __name__ == "__main__":
    unittest.main()
