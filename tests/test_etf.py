"""fetch_etf 各投信 adapter 的離線測試（用假的 HTTP 回應，格式取自 2026-09-29 實際回應）。"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_etf as fe  # noqa: E402


def fake_http(routes):
    """routes: [(url 片段, 回應)]，依序比對第一個符合的。"""
    def http(url, params=None, body=None, as_json=True, **kw):
        full = url + (str(sorted(params.items())) if params else "") + (str(body) if body else "")
        for frag, resp in routes:
            if frag in full:
                return resp(params, body) if callable(resp) else resp
        raise AssertionError(f"unexpected request: {full}")
    return http


def stocks(n, start=1101):
    return [str(start + i) for i in range(n)]


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self._http = fe.http
        fe._cathay_map = fe._capital_map = fe._fh_map = None

    def tearDown(self):
        fe.http = self._http

    def test_yuanta_prefers_stockweights(self):
        fe.http = fake_http([("bridge", {
            "PCF": {"trandate": "20260924", "osunit": 22078000000, "baseunit": 500000, "totalav": 2.48e12, "nav": 112.33},
            "InKind": {"FundComposition": [{"stkcd": "2330", "name": "台積電", "qty": 12724}]},
            "FundWeights": {"StockWeights": [{"code": "2330", "name": "台積電", "weights": 56.0, "qty": 560435745.0}],
                            "FutureWeights": [{"code": "TX", "name": "臺股期貨", "weights": 0.26, "qty": 658.0}]}})])
        d, rows, meta = fe.yuanta("0050")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual(rows, [{"code": "2330", "name": "台積電", "shares": 560435745, "weight": 56.0}])
        self.assertEqual(meta["nav"], 112.33)

    def test_yuanta_falls_back_to_basket(self):
        fe.http = fake_http([("bridge", {
            "PCF": {"trandate": "20260924", "osunit": 1000000, "baseunit": 500000},
            "InKind": {"FundComposition": [{"stkcd": "2330", "name": "台積電", "qty": 100}]},
            "FundWeights": {"StockWeights": []}})])
        _, rows, _ = fe.yuanta("0050")
        self.assertEqual(rows[0]["shares"], 200)  # 100 股/基數 × 2 基數
        self.assertIsNone(rows[0]["weight"])

    def test_fubon_skips_futures_row(self):
        page = """<p>基金淨資產(新台幣)</p>
                            <p>478,793,858,229</p>
            資料日期：2026/09/24
            <tr><td class="tac">WTXV6F</td><td>2026/10台股指數期貨</td><td class="tar">180</td><td class="tar">1,234</td><td class="tar">0.3618</td></tr>
            <tr><td class="tac">2330</td><td>台積電</td><td class="tar">108,279,064</td><td class="tar">267,990,683,400</td><td class="tar">55.972</td></tr>"""
        fe.http = fake_http([("Assets.aspx", page)])
        d, rows, meta = fe.fubon("006208")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual([r["code"] for r in rows], ["2330"])
        self.assertEqual(rows[0]["shares"], 108279064)
        self.assertEqual(meta["aum"], 478793858229)

    def test_cathay_basket_to_total_shares(self):
        fe.http = fake_http([
            ("GetETFList", {"success": True, "result": [{"stockCode": "00878", "fundCode": "CN"}]}),
            ("GetBuySale", {"success": True, "result": {"date": "2026/09/29", "preDateC": "2026/09/24",
                                                         "totUnit": "18,796,790,000", "basketUnit": "500,000",
                                                         "aum": "655,644,874,925", "nav": "34.88"}}),
            ("GetStocksList", lambda p, b: {"success": True, "result": [
                {"prod": "2891", "prodName": "中信金", "basketShares": "24,773"}]} if p.get("SearchDate") == "2026/09/29"
                else {"success": True, "result": []}),
            ("GetIndexStockWeights", {"success": True, "result": {"stockWeights": [{"stockCode": "2891", "weights": "9.64"}]}}),
        ])
        d, rows, _ = fe.cathay("00878")
        self.assertEqual(d, "2026-09-24")  # 用持股基準日，不是公告日
        self.assertEqual(rows[0]["shares"], round(24773 * 37593.58))
        self.assertEqual(rows[0]["weight"], 9.64)

    def test_capital(self):
        fe.http = fake_http([
            ("etf/items", {"data": [{"stockNo": "00919", "fundNo": "195"}]}),
            ("etf/buyback", {"data": {"pcf": {"date2": "2026-09-24", "nav": 6.0e11, "totUnit": 1.9e10, "pUnit": 31.76},
                                      "stocks": [{"stocNo": "2881", "stocName": "富邦金", "weight": 15.0291, "share": 608720000.0}]}}),
        ])
        d, rows, meta = fe.capital("00919")
        self.assertEqual((d, rows[0]["shares"], rows[0]["weight"], meta["nav"]), ("2026-09-24", 608720000, 15.0291, 31.76))

    def test_fuhhwa_walks_back_to_data_day(self):
        def assets(p, b):
            if p["qDate"].endswith("09/24") or p["qDate"] < "2026/09/24":
                return {"result": [{"dDate": "2026/09/24", "pcf_Fundpnav": "29.23", "detail": [
                    {"ftype": "股票", "stockid": "2357", "stockname": "華碩電腦", "qshare": "6,445,000", "prate_addaccint": "3.954%"},
                    {"ftype": "期貨", "stockid": "TXF", "stockname": "期貨", "qshare": "1", "prate_addaccint": "3%"}]}]}
            return {"result": [{"dDate": None, "detail": []}]}
        fe.http = fake_http([("fundList", {"result": [{"etf002": "00929", "fundID": "ETF21"}]}), ("api/assets", assets)])
        d, rows, _ = fe.fuhhwa("00929")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual(rows, [{"code": "2357", "name": "華碩電腦", "shares": 6445000, "weight": 3.954}])


class HelpersTest(unittest.TestCase):
    def test_iso(self):
        for s in ("20260924", "2026/09/24", "2026-09-24", "1150924"):
            self.assertEqual(fe.iso(s), "2026-09-24")

    def test_validate(self):
        ok = [fe.holding(c, c, 100, 10) for c in stocks(6)]
        fe.validate("X", ok)
        with self.assertRaises(fe.AdapterError):
            fe.validate("X", ok[:3])
        with self.assertRaises(fe.AdapterError):
            fe.validate("X", ok + [fe.holding("1101", "dup", 1, 1)])
        with self.assertRaises(fe.AdapterError):
            fe.validate("X", [fe.holding(c, c, 100, 30) for c in stocks(6)])

    def test_names_and_weights_from_market(self):
        rows = [fe.holding("2357", "華碩電腦", 100, None), fe.holding("2330", "台積電", 10, None)]
        market = {"2357": (1000.0, "華碩"), "2330": (3000.0, "台積電")}
        fe.normalize_names(rows, market)
        self.assertEqual(rows[0]["name"], "華碩")
        self.assertTrue(fe.fill_weights(rows, market))
        self.assertAlmostEqual(rows[0]["weight"], 76.9231, places=3)  # 100000 / 130000

    def test_write_and_summary(self):
        orig = fe.ETF_DIR
        self.addCleanup(setattr, fe, "ETF_DIR", orig)
        with tempfile.TemporaryDirectory() as tmp:
            fe.ETF_DIR = Path(tmp)
            out = fe.write_day("0050", "2026-09-24", [fe.holding("2454", "聯發科", 1, 7.2), fe.holding("2330", "台積電", 2, 56.0)])
            rows = list(csv.DictReader(out.open(encoding="utf-8")))
            self.assertEqual([r["code"] for r in rows], ["2330", "2454"])  # 依權重排序
            e = {"date": "2026-09-24", "etf": "0050", "aum": 1, "units": 2, "nav": 3, "holdings": 2, "fetched_at": "x"}
            fe.update_summary([e])
            fe.update_summary([{**e, "nav": 4}])  # 同一天重跑 → 覆寫不重複
            s = list(csv.DictReader((Path(tmp) / "summary.csv").open(encoding="utf-8")))
            self.assertEqual(len(s), 1)
            self.assertEqual(s[0]["nav"], "4")


if __name__ == "__main__":
    unittest.main()
