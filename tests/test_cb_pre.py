import json
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_cb as F  # noqa: E402
import fetch_cb_pre as P  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "cb"


def detail(name):
    row = json.loads((FIX / f"mops_detail_board_{name}.json").read_text(encoding="utf-8"))["result"]["data"][0]
    return P.parse_board(row[9], row[8])


class MoneyTest(unittest.TestCase):
    def test_parse_money(self):
        cases = {"發行總面額為新台幣參億伍仟萬元": 350_000_000, "發行總面額上限為新台幣25億元整": 2_500_000_000,
                 "發行總面額上限新臺幣陸億元": 600_000_000, "新台幣500,000仟元": 500_000_000,
                 "新台幣壹拾億元整": 1_000_000_000, "以新台幣1,500,000,000元為上限": 1_500_000_000,
                 "新台幣一百五十億元": 15_000_000_000, "新臺幣貳億伍仟萬元整": 250_000_000}
        for text, want in cases.items():
            self.assertEqual(P.parse_money(text), want, text)
        self.assertIsNone(P.parse_money("授權董事長決定"))

    def test_roc_date(self):
        self.assertEqual([P.roc_date(x) for x in ("1150917", "115/09/17", "115/9/7", "")],
                         ["2026-09-17", "2026-09-17", "2026-09-07", ""])


class SfbTest(unittest.TestCase):
    def setUp(self):
        self.rows = P.parse_sfb(P.read_ods((FIX / "sfb115.ods").read_bytes()))
        self.by = {(r["code"], r["amount"]): r for r in self.rows}

    def test_only_domestic_cb(self):
        self.assertTrue(all("海外" not in r["kind"] for r in self.rows))
        self.assertNotIn(("2303", "1800000000"), self.by)  # 聯電海外 CB（美元）

    def test_pending_and_effective(self):
        r = self.by[("5381", "500000000")]  # 光譜：審查中，預計 10/19 生效
        self.assertEqual((r["status"], r["filed"], r["effective"], r["stop"]), ("審查中", "2026-09-30", "2026-10-19", ""))
        r = self.by[("6285", "6000000000")]  # 啟碁：已生效
        self.assertEqual((r["status"], r["filed"], r["effective"]), ("生效", "2026-09-03", "2026-09-21"))
        r = self.by[("3033", "4000000000")]  # 威健：停止生效，沒有生效日
        self.assertEqual((r["status"], r["stop"], r["effective"]), ("審查中", "2026-10-02", ""))

    def test_withdrawn(self):
        r = self.by[("8916", "200000000")]
        self.assertEqual((r["status"], r["withdrawn"]), ("自行撤回", "2026-08-12"))


class MopsTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(P.classify("公告本公司董事會決議發行國內第六次無擔保轉換公司債"), "board")
        self.assertEqual(P.classify("本公司董事會決議發行國內第一次暨第二次\r\n無擔保轉換公司債(變更發行額度)"), "board")
        self.assertEqual(P.classify("本公司自行撤回115年度現金增資發行新股暨國內第二次無擔保轉換公司債"), "withdraw")
        self.assertEqual(P.classify("公告本公司轉換公司債代收價款行庫及存儲專戶行庫"), "bank")
        for s in ("本公司董事會決議發行海外第一次無擔保轉換公司債", "公告本公司轉換公司債轉換價格調整",
                  "代子公司公告董事會決議轉讓某公司發行之可轉換公司債", "公告本公司決議買回並註銷國內第一次無擔保轉換公司債",
                  "本公司董事會決議除權除息基準日暨可轉換公司債停止轉換期間", "公告本公司董事會決議私募無擔保轉換公司債"):
            self.assertIsNone(P.classify(s), s)

    def test_parse_list(self):
        res = json.loads((FIX / "mops_t05st02.json").read_text(encoding="utf-8"))["result"]
        evs = P.parse_list(res)
        mitac = [e for e in evs if e["code"] == "3706"]
        self.assertEqual([e["kind"] for e in mitac], ["board"])
        self.assertEqual((mitac[0]["date"], mitac[0]["market"], mitac[0]["enter_date"]), ("2026-09-29", "sii", "1150929"))

    def test_board_detail(self):
        self.assertEqual(detail("3016_1150630"), {
            "board_date": "2026-06-30", "series": "6", "secured": "無擔保", "amount": 350_000_000,
            "method": "詢價圈購", "lead": "凱基證券股份有限公司", "issue_price": "票面金額之100%~101%發行", "parsed": "1"})
        b = detail("8422_1150630")
        self.assertEqual((b["board_date"], b["series"], b["amount"], b["method"]), ("2026-07-02", "3", 2_500_000_000, "競價拍賣"))
        b = detail("3219_1150701")
        self.assertEqual((b["amount"], b["method"], b["lead"]), (600_000_000, "競價拍賣", "群益金鼎證券股份有限公司"))


class AttachTest(unittest.TestCase):
    def case(self, **kw):
        c = {k: "" for k in F.CASE_COLS}
        c.update(kw)
        return c

    def test_attach(self):
        today = date(2026, 10, 5)
        cases = [self.case(id="bb1", code="8422", company="可寧衛", units=25000, bb_start="2026-09-17", method="競價拍賣")]
        sfb = [{"code": "8422", "status": "生效", "name": "可寧衛", "lead": "中國信託證券", "kind": "轉換公司債(無擔保)",
                "amount": "2500000000", "filed": "2026-08-10", "effective": "2026-08-26", "stop": "", "unstop": "",
                "withdrawn": "", "returned": "", "revoked": ""},
               {"code": "5381", "status": "審查中", "name": "光譜電工", "lead": "富邦證券", "kind": "轉換公司債(有擔保)",
                "amount": "500000000", "filed": "2026-09-30", "effective": "2026-10-19", "stop": "", "unstop": "",
                "withdrawn": "", "returned": "", "revoked": ""}]
        events = [{"kind": "board", "code": "8422", "name": "可寧衛*", "date": "2026-07-02", "time": "18:00",
                   "board_date": "2026-07-02", "series": "3", "amount": "2500000000", "method": "競價拍賣", "lead": "中信",
                   "secured": "無擔保", "subject": "董事會決議發行國內第三次無擔保轉換公司債"},
                  {"kind": "board", "code": "5381", "name": "光譜", "date": "2026-08-20", "time": "17:00",
                   "board_date": "2026-08-20", "series": "3", "amount": "500000000", "method": "詢價圈購", "lead": "",
                   "secured": "有擔保", "subject": ""},
                  {"kind": "board", "code": "1234", "name": "測試", "date": "2026-09-01", "time": "17:00",
                   "board_date": "2026-09-01", "series": "1", "amount": "300000000", "method": "詢價圈購", "lead": "",
                   "secured": "無擔保", "subject": ""},
                  {"kind": "board", "code": "9999", "name": "太舊", "date": "2025-08-01", "time": "17:00",
                   "board_date": "2025-08-01", "series": "1", "amount": "", "method": "", "lead": "", "secured": "",
                   "subject": ""}]
        out = {c["code"]: c for c in F.attach_pipeline(cases, sfb, events, today)}
        k = out["8422"]  # 既有案件接上送件、生效、董事會
        self.assertEqual((k["id"], k["filed_date"], k["eff_date"], k["board_date"]), ("bb1", "2026-08-10", "2026-08-26", "2026-07-02"))
        g = out["5381"]  # 審查中：新案件，也接上董事會
        self.assertEqual((g["sfb_status"], g["eff_date"], g["board_date"], g["units"], g["type"]),
                         ("審查中", "2026-10-19", "2026-08-20", 5000, "有擔保轉換公司債"))
        t = out["1234"]  # 只有董事會決議
        self.assertEqual((t["board_date"], t["filed_date"], t["board_amount"], t["method"]), ("2026-09-01", "", 300_000_000, "詢價圈購"))
        self.assertNotIn("9999", out)  # 超過一年未送件不列


if __name__ == "__main__":
    unittest.main()
