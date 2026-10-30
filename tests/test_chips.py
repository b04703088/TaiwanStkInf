import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import chips_site as C  # noqa: E402
import fetch_chips as F  # noqa: E402
import fetch_futures as FF  # noqa: E402
import fetch_tdcc as TD  # noqa: E402
import futures_site as FS  # noqa: E402
import screen_site as SC  # noqa: E402

T86 = {"stat": "OK", "fields": ["證券代號"] + ["x"] * 18,
       "data": [["2330", "台積電          ", "44,651,940", "12,114,783", "32,537,157", "0", "0", "0", "1,197,044", "35,000",
                 "1,162,044", "2,133,536", "2,265,074", "512,179", "1,752,895", "465,641", "85,000", "380,641", "35,832,737"]]}
TPEX_INST = {"tables": [{"fields": ["代號"] + ["x"] * 23,
                         "data": [["6488", "環球晶", "100", "0", "100", "0", "0", "0", "100", "0", "100", "0", "50", "-50",
                                   "10", "0", "10", "0", "5", "-5", "10", "5", "5", "55"],
                                  ["712345", "權證", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
                                   "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]]}]}
SBL = {"stat": "OK", "fields": ["代號"] + ["x"] * 14,
       "data": [["00400A", "主動國泰動能高息", "0", "3,000", "0", "0", "3,000", "522,035,000",
                 "41,103,000", "1,011,000", "2,673,000", "0", "39,441,000", "10,578,714", " "],
                ["", "合計", "1", "1", "1", "1", "1", "0", "1", "1", "1", "0", "1", "0", " "]]}
DT = {"tables": [{"fields": ["當日沖銷交易總成交股數"] + ["x"] * 5, "data": [["1", "2", "3", "4", "5", "6"]]},
                 {"fields": ["證券代號", "證券名稱", "註記", "股數", "買", "賣"],
                  "data": [["2330", "台積電", "", "8,392,000", "123,839,380", "124,107,840"]]}]}


class FetchChipsTest(unittest.TestCase):
    def test_t86(self):
        r = F.parse_t86(T86)["2330"]
        self.assertEqual((r["name"], r["f_net"], r["fd_net"], r["t_net"], r["d_net"], r["inst_net"]),
                         ("台積電", "32537157", "0", "1162044", "2133536", "35832737"))

    def test_tpex_inst_skips_warrants_and_checks_sum(self):
        out = F.parse_tpex_inst(TPEX_INST)
        self.assertEqual(list(out), ["6488"])
        self.assertEqual((out["6488"]["t_net"], out["6488"]["d_net"], out["6488"]["inst_net"]), ("-50", "5", "55"))
        bad = {"tables": [{"fields": TPEX_INST["tables"][0]["fields"], "data": [TPEX_INST["tables"][0]["data"][0][:23] + ["999"]]}]}
        with self.assertRaises(RuntimeError):
            F.parse_tpex_inst(bad)

    def test_sbl_and_daytrade(self):
        s = F.parse_sbl(SBL)
        self.assertEqual(list(s), ["00400A"])  # 合計列略過
        self.assertEqual((s["00400A"]["sbl_sell"], s["00400A"]["sbl_ret"], s["00400A"]["sbl_bal"]), ("1011000", "2673000", "39441000"))
        d = F.parse_daytrade(DT)
        self.assertEqual(d, {"2330": {"name": "台積電", "dt_vol": "8392000", "dt_buy": "123839380", "dt_sell": "124107840"}})
        rows = F.merge(date(2026, 10, 22), "TWSE", F.parse_t86(T86), d)
        self.assertEqual((rows[0]["code"], rows[0]["inst_net"], rows[0]["dt_vol"], rows[0]["sbl_bal"]), ("2330", "35832737", "8392000", ""))


class FuturesTest(unittest.TestCase):
    def test_parsers(self):
        fut = FF.parse_fut([["2026/10/01", "臺股期貨", "外資及陸資", "35309", "1", "36698", "1", "-1389", "-13378149",
                             "12373", "1", "91927", "1", "-79554", "-774905393"],
                            ["2026/10/01", "電子期貨", "外資及陸資"] + ["0"] * 12])
        self.assertEqual(fut, [{"date": "2026-10-01", "product": "TX", "who": "foreign", "net_vol": "-1389", "net_val": "-13378149",
                                "oi_long": "12373", "oi_short": "91927", "oi_net": "-79554", "oi_net_val": "-774905393"}])
        opt = FF.parse_opt([["2026/10/01", "臺指選擇權", "PUT", "外資及陸資", "52596", "1", "52272", "1", "324", "-6977",
                             "7124", "1", "6130", "1", "994", "19835"]])
        self.assertEqual((opt[0]["product"], opt[0]["oi_net_val"]), ("TXO_P", "19835"))
        large = FF.parse_large([["2026/10/20", "TX", "臺股期貨", "202610", "0", "1", "2", "3", "4", "9"],
                                ["2026/10/20", "TX", "臺股期貨", "202611", "0", "1", "2", "3", "4", "9"],
                                ["2026/10/20", "TX", "臺股期貨", "999999", "1", "5", "6", "7", "8", "9"],
                                ["2026/10/20", "CD", "台積電期貨", "999999", "0", "1", "1", "1", "1", "1"]])
        self.assertEqual([(r["month"], r["kind"]) for r in large], [("near", "all"), ("all", "inst")])
        tx = FF.parse_tx([["2026/10/22", "TX", "202611  ", "1", "1", "1", "46272", "-741", "-1.58%", "55226", "46234", "115258",
                           "", "", "", "", "", "一般"],
                          ["2026/10/22", "TX", "202612  ", "1", "1", "1", "46362", "-797", "", "676", "", "2460", "", "", "", "", "", "一般"],
                          ["2026/10/22", "TX", "202611  ", "1", "1", "1", "47482", "469", "", "1", "-", "-", "", "", "", "", "", "盤後"]])
        self.assertEqual((tx[0]["contract"], tx[0]["close"], tx[0]["oi"], tx[0]["oi_all"]), ("202611", "46272", "115258", "117718"))

    def test_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "inst.csv").write_text("date,product,who,net_vol,net_val,oi_long,oi_short,oi_net,oi_net_val\n"
                                        "2026-10-01,TX,foreign,-4,0,0,0,-100,0\n2026-10-01,MTX,foreign,0,0,0,0,40,0\n"
                                        "2026-10-01,TXO_C,foreign,0,0,0,0,0,500000\n"
                                        "2026-10-02,TX,foreign,0,0,0,0,-50,0\n", encoding="utf-8")
            p = FS.build(d)
            rows = [dict(zip(p["cols"], r)) for r in p["rows"]]
            self.assertEqual((rows[0]["f_oi"], rows[0]["f_net"], rows[0]["f_call"]), (-90, -4, 5.0))
            self.assertEqual(rows[1]["f_oi_d"], 40)


class SettleTest(unittest.TestCase):
    def test_third_wed(self):
        self.assertEqual(FS.third_wed(2026, 10).isoformat(), "2026-10-21")
        self.assertEqual(FS.third_wed(2026, 7).isoformat(), "2026-07-15")

    def test_shift_on_closed_day(self):
        # 2026/2/18 春節休市：資料裡沒有 2/18～2/20，順延到 2/23
        days = ["2026-02-10", "2026-02-11", "2026-02-23", "2026-02-24"]
        out, nxt = FS.settle_dates(days, {})
        self.assertIn("2026-02-23", out)
        self.assertEqual(nxt["date"], "2026-03-18")
        # 未來的結算日遇休市也順延
        out, nxt = FS.settle_dates(["2026-11-17"], {"2026-11-18"})
        self.assertEqual(nxt, {"date": "2026-11-19", "tdays": 1})


class TdccTest(unittest.TestCase):
    def test_parse(self):
        lines = ["﻿資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%"]
        lines += [f"20261022,2330,{k},{10 if k < 15 else 2},{100},{p}" for k, p in
                  [(1, 1.0), (2, 2.0), (8, 3.0), (9, 4.0), (12, 5.0), (15, 80.0)]]
        lines += ["20261022,2330,17,52,600,100.00", "20261022,000218,17,0,0,0"]
        d, rows = TD.parse("\n".join(lines))
        self.assertEqual(d, "20261022")
        self.assertEqual(rows, [{"date": "2026-10-22", "code": "2330", "holders": 52, "shares": 600, "p1000": 80.0, "n1000": 2,
                                 "p400": 85.0, "p_retail": 6.0, "p_lt1": 1.0}])


class ChipsSiteTest(unittest.TestCase):
    def test_streak(self):
        self.assertEqual((C.streak([1, -2, 3, 4]), C.streak([5, -1, -2]), C.streak([1, 0]), C.streak([])), (2, -2, 0, 0))

    def test_build(self):
        def day(d, f, sbl, dt):
            return (d, {"2330": {"name": "台積電", "market": "TWSE", "f_net": str(f), "fd_net": "0", "t_net": "1000",
                                 "d_net": "-1000", "inst_net": str(f), "sbl_bal": str(sbl), "dt_vol": str(dt)}},
                    {"2330": (100.0, 10000)})
        days = [day(f"2026-10-{i:02d}", 1000 * i, 5000 + i * 1000, 2000) for i in range(1, 8)]
        weeks = [("20261016", {"2330": {"p1000": "80", "holders": "100", "p400": "85"}}),
                 ("20261023", {"2330": {"p1000": "81.5", "holders": "90", "p400": "86"}})]
        payload, per, screen = C.build(days, weeks)
        r = dict(zip(payload["cols"], payload["rows"][0]))
        self.assertEqual((r["f1"], r["f5"], r["fs"], r["ts"], r["ds"]), (7, 25, 7, 7, -7))
        self.assertEqual((r["sbl"], r["sbl1"], r["sbl5"]), (12, 1, 5))
        self.assertEqual((r["dt"], r["big_d"], r["hold_d"]), (20.0, 1.5, -10.0))
        self.assertEqual(r["fv5"], round(25000 * 100 / 1e8, 2))
        self.assertEqual(screen["2330"]["big_d"], 1.5)
        self.assertEqual(per["2330"]["f"][-1], 7)
        self.assertEqual(payload["market"][-1][1], round(7000 * 100 / 1e8, 1))


class ScreenSiteTest(unittest.TestCase):
    def test_tech(self):
        rows = [(20260100 + i, 10, 10, 10, 10, 100) for i in range(1, 30)] + [(20260201, 10, 12, 10, 12, 500)]
        t = SC.tech(rows, None)
        self.assertEqual((t["close"], t["chg"], t["bo"], t["vr"]), (12, 20.0, 1, 5.0))
        # 除權息：還原後之前的價格往下調，不會變成大跌
        rows2 = [(20260100 + i, 10, 10, 10, 10, 100) for i in range(1, 30)] + [(20260201, 9, 9, 9, 9, 100)]
        t2 = SC.tech(rows2, [[20260201, 0.9, "除息", "", 1.0]])
        self.assertEqual(t2["chg"], 0.0)

    def test_dividends_fill(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = Path(tmp) / "events.csv"
            ev.write_text("date,market,code,name,kind,prev_close,ref_price,factor,cash,note,source\n"
                          "2026-07-01,TWSE,2330,台積電,除息,100,95,0.95,5,,TWT49U\n"
                          "2026-08-01,TWSE,1101,台泥,除息,30,29,0.966,1,,TWT49U\n", encoding="utf-8")
            prices = {"2330": {"name": "台積電", "rows": [(20260630, 0, 0, 0, 100, 1), (20260701, 0, 0, 0, 96, 1),
                                                          (20260702, 0, 0, 0, 99, 1), (20260703, 0, 0, 0, 101, 1)]},
                      "1101": {"name": "台泥", "rows": [(20260801, 0, 0, 0, 29, 1), (20260802, 0, 0, 0, 29.5, 1)]}}
            d = SC.dividends(prices, ev, date(2026, 8, 10))
            rows = {r[1]: dict(zip(d["cols"], r)) for r in d["rows"]}
            self.assertEqual((rows["2330"]["fill_days"], rows["2330"]["fill_date"], rows["2330"]["yield"]), (3, 20260703, 5.0))
            self.assertEqual((rows["1101"]["fill_days"], rows["1101"]["days_since"]), (None, 2))


if __name__ == "__main__":
    unittest.main()
