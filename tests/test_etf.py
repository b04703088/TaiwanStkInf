"""fetch_etf 各投信 adapter 的離線測試（用假的 HTTP 回應，格式取自 2026-09-29 實際回應）。"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import etf_adapters as A  # noqa: E402
import etf_common as C  # noqa: E402
import fetch_etf as fe  # noqa: E402


def fake_http(routes):
    """routes: [(url 片段, 回應)]，依序比對第一個符合的。"""
    def http(url, params=None, body=None, form=None, as_json=True, **kw):
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
        self._http = C.http
        A._cathay_map = A._capital_map = A._fh_map = A._kgi_map = None
        A.SOURCE_IDS.clear()

    def tearDown(self):
        C.http = self._http

    def test_yuanta_prefers_stockweights(self):
        C.http = fake_http([("bridge", {
            "PCF": {"trandate": "20260924", "osunit": 22078000000, "baseunit": 500000, "totalav": 2.48e12, "nav": 112.33},
            "InKind": {"FundComposition": [{"stkcd": "2330", "name": "台積電", "qty": 12724}]},
            "FundWeights": {"StockWeights": [{"code": "2330", "name": "台積電", "weights": 56.0, "qty": 560435745.0}],
                            "FutureWeights": [{"code": "TX", "name": "臺股期貨", "weights": 0.26, "qty": 658.0}]}})])
        d, rows, meta = A.yuanta("0050")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual(rows, [{"code": "2330", "name": "台積電", "shares": 560435745, "weight": 56.0}])
        self.assertEqual(meta["nav"], 112.33)

    def test_fubon_skips_futures_row(self):
        page = """<p>基金淨資產(新台幣)</p>
                            <p>478,793,858,229</p>
            資料日期：2026/09/24
            <tr><td class="tac">WTXV6F</td><td>2026/10台股指數期貨</td><td class="tar">180</td><td class="tar">1,234</td><td class="tar">0.3618</td></tr>
            <tr><td class="tac">2330</td><td>台積電</td><td class="tar">108,279,064</td><td class="tar">267,990,683,400</td><td class="tar">55.972</td></tr>"""
        C.http = fake_http([("Assets.aspx", page)])
        d, rows, meta = A.fubon("006208")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual([r["code"] for r in rows], ["2330"])
        self.assertEqual(rows[0]["shares"], 108279064)
        self.assertEqual(meta["aum"], 478793858229)

    def test_cathay_uses_actual_holdings(self):
        C.http = fake_http([
            ("GetETFList", {"success": True, "result": [{"stockCode": "00878", "fundCode": "CN"}]}),
            ("GetETFAssets", {"success": True, "result": {"preDate": "2026/09/29", "fundNav": "652,907,591,089",
                                                           "fundOutstandingShares": "18,799,290,000", "fundPerNav": "34.73"}}),
            ("GetETFDetailStockList", lambda p, b: {"success": True, "result": [
                {"stockCode": "2891", "stockName": "中信金", "volumn": "922,437,000", "weights": "9.71"},
                {"stockCode": "2382", "stockName": "廣達", "volumn": "179,341,000", "weights": "9.24"}]}
                if p.get("SearchDate") == "2026/09/29" else {"success": False, "result": None}),
        ])
        d, rows, meta = A.cathay("00878")
        self.assertEqual(d, "2026-09-29")
        self.assertEqual(rows[0], {"code": "2891", "name": "中信金", "shares": 922437000, "weight": 9.71})
        self.assertEqual((meta["units"], meta["nav"]), (18799290000, 34.73))

    def test_yuanta_without_stockweights_is_an_error(self):
        C.http = fake_http([("bridge", {
            "PCF": {"trandate": "20260924", "osunit": 1000000, "baseunit": 500000},
            "InKind": {"FundComposition": [{"stkcd": "2330", "name": "台積電", "qty": 100}]},
            "FundWeights": {"StockWeights": []}})])
        with self.assertRaises(C.AdapterError):
            A.yuanta("0050")

    def test_capital(self):
        C.http = fake_http([
            ("etf/items", {"data": [{"stockNo": "00919", "fundNo": "195"}]}),
            ("etf/buyback", {"data": {"pcf": {"date2": "2026-09-24", "nav": 6.0e11, "totUnit": 1.9e10, "pUnit": 31.76},
                                      "stocks": [{"stocNo": "2881", "stocName": "富邦金", "weight": 15.0291, "share": 608720000.0}]}}),
        ])
        d, rows, meta = A.capital("00919")
        self.assertEqual((d, rows[0]["shares"], rows[0]["weight"], meta["nav"]), ("2026-09-24", 608720000, 15.0291, 31.76))

    def test_fuhhwa_walks_back_to_data_day(self):
        def assets(p, b):
            if p["qDate"].endswith("09/24") or p["qDate"] < "2026/09/24":
                return {"result": [{"dDate": "2026/09/24", "pcf_Fundpnav": "29.23", "detail": [
                    {"ftype": "股票", "stockid": "2357", "stockname": "華碩電腦", "qshare": "6,445,000", "prate_addaccint": "3.954%"},
                    {"ftype": "期貨", "stockid": "TXF", "stockname": "期貨", "qshare": "1", "prate_addaccint": "3%"}]}]}
            return {"result": [{"dDate": None, "detail": []}]}
        C.http = fake_http([("fundList", {"result": [{"etf002": "00929", "fundID": "ETF21"}]}), ("api/assets", assets)])
        d, rows, _ = A.fuhhwa("00929")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual(rows, [{"code": "2357", "name": "華碩電腦", "shares": 6445000, "weight": 3.954}])


class NewSourcesTest(unittest.TestCase):
    def setUp(self):
        self._http = C.http
        A._kgi_map = None

    def tearDown(self):
        C.http = self._http

    def test_isin(self):
        self.assertEqual(C.isin_for("00404A"), "TW00000404A5")
        self.assertEqual(C.isin_for("00980D"), "TW00000980D8")

    def test_code_normalization(self):
        self.assertEqual(C.code_of("2330 TT"), "2330")
        self.assertEqual(C.code_of(" 6669 "), "6669")
        self.assertEqual(C.code_of("nvda us"), "NVDA US")
        self.assertTrue(C.is_security("NVDA US"))
        self.assertFalse(C.is_security("TXF"))
        self.assertFalse(C.is_security("現金"))

    def test_html_rows_stops_at_duplicate_table(self):
        tbl = "".join(f"<tr><td>{c} </td><td>n</td><td>1,000</td><td>1.5</td></tr>" for c in ("2330", "2454"))
        rows = A._html_rows("<table>" + tbl + "</table><table>" + tbl + "</table>")
        self.assertEqual([r["code"] for r in rows], ["2330", "2454"])

    def test_taishin_strips_tt_keeps_foreign(self):
        page = ('<input id="PUB_DATE" value="2026-09-25"> 資料日期：2026/09/24 <th>股數</th>'
                '<tr><td>2330 TT</td><td>台積電</td><td>90,000</td><td>8.0505%</td></tr>'
                '<tr><td>MU US</td><td>美光</td><td>1,000</td><td>2.5%</td></tr><th>口數</th>'
                '<tr><td>TXF</td><td>台指期</td><td>3</td><td>1%</td></tr>')
        C.http = fake_http([("tsit.com.tw", page)])
        d, rows, _ = A.taishin("00987A")
        self.assertEqual(d, "2026-09-24")
        self.assertEqual([(r["code"], r["weight"]) for r in rows], [("2330", 8.0505), ("MU US", 2.5)])

    def test_kgi_matches_name_and_first_table(self):
        lst = '<option value="J024">主動凱基台灣</option><option value="J010">凱基優選高股息30ETF基金</option>'
        tbl = '<tr name="content"><td>2330</td><td>&#x53F0;&#x7A4D;&#x96FB;</td><td>991,000</td><td>7.98</td></tr>'
        C.http = fake_http([("RedemptionList", lst), ("J010", f"持股比重 (2026/09/25) {tbl}{tbl}")])
        d, rows, _ = A.kgi("00915", "凱基優選高股息30")
        # 凱基標公告日 9/25 → 換算回持股基準日 9/24（前一個有行情的交易日）
        self.assertEqual((d, len(rows), rows[0]["name"]), ("2026-09-24", 1, "台積電"))

    def test_xlsx_rows(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/sharedStrings.xml", "<sst><si><t>股票代碼</t></si><si><t>台積電</t></si></sst>")
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                       '<row r="2"><c r="A2"><v>2330</v></c><c r="B2" t="s"><v>1</v></c><c r="D2"><v>5.5</v></c></row>'
                       '</sheetData></worksheet>')
        rows = C.xlsx_rows(buf.getvalue())
        self.assertEqual(rows, [["股票代碼"], ["2330", "台積電", "", "5.5"]])


class IdCacheTest(unittest.TestCase):
    def setUp(self):
        self._http = C.http
        A._fh_map = None
        A.SOURCE_IDS.clear()

    def tearDown(self):
        C.http = self._http
        A.SOURCE_IDS.clear()

    def test_uses_cached_id_when_list_endpoint_fails(self):
        A.SOURCE_IDS["fuhhwa"] = {"00929": "ETF21"}
        def fail(*a, **k):
            raise C.AdapterError("RemoteDisconnected")
        C.http = fake_http([("fundList", fail), ("api/assets", {"result": [{"dDate": "2026/09/24", "detail": [
            {"ftype": "股票", "stockid": "2357", "stockname": "華碩", "qshare": "1", "prate_addaccint": "1%"}]}]})])
        d, rows, _ = A.fuhhwa("00929")
        self.assertEqual((d, rows[0]["code"]), ("2026-09-24", "2357"))

    def test_list_result_is_cached(self):
        C.http = fake_http([("fundList", {"result": [{"etf002": "00929", "fundID": "ETF21"}]}),
                            ("api/assets", {"result": [{"dDate": "2026/09/24", "detail": [
                                {"ftype": "股票", "stockid": "2357", "stockname": "華碩", "qshare": "1", "prate_addaccint": "1%"}]}]})])
        A.fuhhwa("00929")
        self.assertEqual(A.SOURCE_IDS["fuhhwa"]["00929"], "ETF21")


class HelpersTest(unittest.TestCase):
    def test_iso(self):
        for s in ("20260924", "2026/09/24", "2026-09-24", "1150924"):
            self.assertEqual(C.iso(s), "2026-09-24")

    def test_validate(self):
        ok = [C.holding(c, c, 100, 10) for c in stocks(6)]
        fe.validate("X", ok)
        with self.assertRaises(C.AdapterError):
            fe.validate("X", ok[:3])
        with self.assertRaises(C.AdapterError):
            fe.validate("X", ok + [C.holding("1101", "dup", 1, 1)])
        with self.assertRaises(C.AdapterError):
            fe.validate("X", [C.holding(c, c, 100, 30) for c in stocks(6)])

    def test_names_and_weights_from_market(self):
        rows = [C.holding("2357", "華碩電腦", 100, None), C.holding("2330", "台積電", 10, None)]
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
            out = fe.write_day("0050", "2026-09-24", [C.holding("2454", "聯發科", 1, 7.2), C.holding("2330", "台積電", 2, 56.0)])
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
