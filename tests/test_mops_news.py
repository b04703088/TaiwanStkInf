import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_mops_news as F  # noqa: E402
import mops_site as S  # noqa: E402

# 觀測站 t05st02_detail 回傳的內容欄（2026-03-09 實際資料節錄）
SHM_8112 = ("1.董事會決議日期：115/03/09\r\n2.股東會召開日期：115/05/26\r\n3.股東會召開地點：宏匯瑞光廣場\r\n"
            "4.股東會召開方式(實體股東會/視訊輔助股東會/視訊股東會)：實體股東會\r\n5.召集事由一：報告事項\r\n"
            "(1)：114年度營業報告。\r\n8.停止過戶起始日期：115/03/28\r\n9.停止過戶截止日期：115/05/26\r\n")
SHM_VIDEO = ("1.董事會決議日期:115/10/08\n2.股東會召開日期:115/11/20\n3.股東會召開地點:不適用\n"
             "4.股東會召開方式(實體股東會/視訊輔助股東會/視訊股東會):視訊輔助股東會\n")
CALL = ("1.召開法人說明會之日期:115/10/20\n2.召開法人說明會之時間:14 時 00 分\n"
        "3.召開法人說明會之地點:台北君悅酒店3樓凱悅廳\n4.法人說明會擇要訊息:說明本公司營運狀況")

LIST = {"data": [
    ["115/10/08", "17:30:17", "3711", "日月光投控", "代子公司日月光半導體製造(股)公司公告\r\n取得機器設備",
     {"apiName": "t05st02_detail", "parameters": {"companyId": "3711", "marketKind": "sii", "enterDate": "1151008", "serialNumber": 4}}],
    ["115/10/08", "17:31:00", "8112", "至上", "公告本公司董事會決議召開115年股東臨時會",
     {"apiName": "t05st02_detail", "parameters": {"companyId": "8112", "marketKind": "otc", "enterDate": "1151008", "serialNumber": 1}}],
    ["115/10/08", "17:32:00", "2330", "台積電", "本公司受邀參加摩根士丹利證券舉辦之法人說明會",
     {"apiName": "t05st02_detail", "parameters": {"companyId": "2330", "marketKind": "sii", "enterDate": "1151008", "serialNumber": 2}}],
    ["115/10/08", "17:33:00", "7777", "興櫃股", "公告本公司董事會決議召開股東臨時會",
     {"apiName": "t05st02_detail", "parameters": {"companyId": "7777", "marketKind": "rotc", "enterDate": "1151008", "serialNumber": 1}}],
], "titles": []}


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        cases = {
            "公告本公司董事會決議召開115年股東常會": "shm",
            "公告本公司115年股東常會重要決議事項": "shm",
            "董事會決議召開&#11936;國115年股東常會": "shm",
            "本公司受邀參加元大證券舉辦之法人說明會": "call",
            "公告本公司董事會決議買回本公司股份": "buyback",
            "公告本公司董事會決議股利分派": "div",
            "公告本公司董事會通過114年度第3季合併財務報告": "fin",
            "泰金寶科技股份有限公司2026年02月自結合併營收公告": "fin",
            "公告本公司董事長異動": "hr",
            "本公司董事會決議不繼續辦理114年股東常會通過之私募有價證券案": "capital",
            "公告本公司董事會決議發行國內第三次無擔保轉換公司債": "capital",
            "代子公司日月光半導體製造(股)公司公告取得佳宸科技股份有限公司供營業用之機器設備": "ma",
            "澄清媒體報導": "clarify",
            "本公司董事會決議通過資本支出案": "board",
            "翌日披露報表": "other",
            "公告本公司2026年9月合併營業額": "fin",
            "發佈本公司115年09月份業績資料": "fin",
            "本公司受邀參加寬量國際主辦之「20th QIC CEO Week」,向投資人說明本公司之營運概況、財務及業務相關資訊": "call",
            "補充說明-本公司配合檢調單位執行搜索調查之重訊,已獲不起訴處分。": "legal",
            "說明本公司總經理裁定羈押一事": "legal",
            "公告本公司董事會依115年股東會授權決議辦理私募普通股之定價及其他相關事宜": "capital",
            "公告本公司擬取得位於台南市不動產": "ma",
            "公告本公司處分有價證券": "ma",
            "本公司接獲授權夥伴通知新藥取得中國國家藥品監督管理局上市許可": "other",
            "公告本公司內部稽核主管異動": "hr",
            "公告本公司法人董事改派代表人": "hr",
            "公告本公司買回公司股份執行完畢": "buyback",
            "係因本公司有價證券於集中交易市場達公布注意交易資訊標準,故公布相關財務業務等重大訊息": "attn",
            "本公司訂購機器設備公告": "ma",
        }
        for s, want in cases.items():
            self.assertEqual(F.classify(s), want, s)

    def test_sub_and_notice(self):
        self.assertEqual(F.is_sub("代子公司日月光半導體製造(股)公司公告取得機器設備"), "1")
        self.assertEqual(F.is_sub("代重要子公司東森新媒體控股(股)公司公告董事會決議召開115年股東常會事宜"), "1")
        self.assertEqual(F.is_sub("公告本公司董事會決議召開115年股東常會"), "")
        self.assertEqual(F.is_sub("代世越銀行公告董事會(代行股東會職權)重要決議事項"), "1")
        self.assertEqual(F.is_sub("代理發言人異動公告"), "")
        self.assertFalse(F.call_notice("公告本公司今日法人說明會摘要"))
        self.assertTrue(F.shm_notice("公告本公司董事會決議召開115年股東常會相關事宜(召開方式：視訊輔助股東會)"))
        self.assertTrue(F.shm_notice("董事會決議股東會召開日期、事由及停止變更股東名簿記載日期"))
        self.assertFalse(F.shm_notice("公告本公司115年股東常會重要決議事項"))
        self.assertFalse(F.shm_notice("公告本公司115年股東常會通過解除董事競業禁止之限制"))
        self.assertTrue(F.call_notice("公告本公司115/03/18召開法人說明會之相關訊息。"))
        self.assertFalse(F.call_notice("公告本公司法人說明會簡報檔"))


class ParseTest(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(F.roc_date("115/05/26"), "2026-05-26")
        self.assertEqual(F.roc_date("1150526"), "2026-05-26")
        self.assertEqual(F.roc_date("115年5月6日"), "2026-05-06")
        self.assertEqual(F.roc_date("2026/05/26"), "2026-05-26")
        self.assertEqual(F.roc_date("不適用"), "")

    def test_shm(self):
        self.assertEqual(F.parse_shm("公告本公司董事會決議召開115年股東常會", SHM_8112), ("常會", "2026-05-26", ""))
        self.assertEqual(F.parse_shm("董事會決議召開股東臨時會", SHM_VIDEO), ("臨時會", "2026-11-20", "視訊輔助"))

    def test_call(self):
        self.assertEqual(F.parse_call(CALL), ("2026-10-20", "14:00 台北君悅酒店3樓凱悅廳"))

    def test_fetch_days(self):
        details = {"8112": SHM_VIDEO, "2330": CALL}

        def fake(api, body):
            if api == "t05st02":
                return LIST
            return {"data": [[1, "", "", "", "", "", "", "17", "115/10/08", details[body["companyId"]]]]}
        with mock.patch.object(F, "mops", side_effect=fake), mock.patch.object(F, "DELAY", 0):
            evs, done, errs = F.fetch_days([date(2026, 10, 8)], 60, {})
        self.assertEqual((done, errs), (["2026-10-08"], []))
        self.assertEqual([e["code"] for e in evs], ["3711", "8112", "2330"])  # 興櫃不收
        by = {e["code"]: e for e in evs}
        self.assertEqual((by["3711"]["cat"], by["3711"]["sub"], by["3711"]["subject"]), ("ma", "1", "代子公司日月光半導體製造(股)公司公告 取得機器設備"))
        self.assertEqual((by["8112"]["ev_kind"], by["8112"]["ev_date"], by["8112"]["market"]), ("臨時會", "2026-11-20", "otc"))
        self.assertEqual((by["2330"]["ev_kind"], by["2330"]["ev_date"]), ("法說會", "2026-10-20"))

    def test_merge_and_write(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            old = [dict.fromkeys(F.COLS, ""), dict.fromkeys(F.COLS, "")]
            old[0].update(date="2026-10-07", code="1101", enter_date="1151007", serial="1", subject="a")
            old[1].update(date="2026-10-08", code="1102", enter_date="1151008", serial="1", subject="old")
            new = [dict(old[1], subject="new")]
            rows = F.merge(old, new)
            self.assertEqual(sorted(r["subject"] for r in rows), ["a", "new"])
            F.write_months(rows, ["2026-10"], out)
            self.assertEqual([r["subject"] for r in F.read_all(out)], ["a", "new"])


def row(**kw):
    r = dict.fromkeys(F.COLS, "")
    r.update({"market": "sii", "cat": "other", "time": "17:00:00", **kw})
    return r


class SiteTest(unittest.TestCase):
    def test_meetings(self):
        rows = [
            row(date="2026-03-09", code="8112", name="至上", cat="shm", subject="董事會決議召開115年股東常會", ev_kind="常會", ev_date="2026-05-26"),
            row(date="2026-03-20", code="8112", name="至上", cat="shm", subject="更正股東常會日期", ev_kind="常會", ev_date="2026-05-28"),
            row(date="2026-09-01", code="1234", name="甲", cat="shm", subject="董事會決議召開股東臨時會", ev_kind="臨時會", ev_date="2026-10-30"),
            row(date="2026-09-05", code="1234", name="甲", cat="shm", subject="董事會決議股東臨時會延期", ev_kind="臨時會", ev_date="2026-11-10"),
            row(date="2026-10-01", code="2330", name="台積電", cat="call", subject="法說會", ev_kind="法說會", ev_date="2026-10-16", ev_note="14:00"),
            row(date="2026-10-02", code="2330", name="台積電", cat="call", subject="受邀參加法說會", ev_kind="法說會", ev_date="2026-11-03"),
            row(date="2026-10-08", code="2317", name="鴻海", cat="board", subject="董事會決議"),
        ]
        m = S.meetings(rows, "2026-01-01")
        self.assertEqual([(r["code"], r["ev_date"]) for r in m],
                         [("8112", "2026-05-28"), ("2330", "2026-10-16"), ("2330", "2026-11-03"), ("1234", "2026-11-10")])
        p = S.build(rows, today=date(2026, 10, 9))
        self.assertEqual(p["generated"], "2026-10-08")
        news = [dict(zip(p["news"]["cols"], r)) for r in p["news"]["rows"]]
        self.assertEqual([r["code"] for r in news], ["2317", "2330", "2330"])  # 近 30 天、新到舊
        meets = [dict(zip(p["meets"]["cols"], r)) for r in p["meets"]["rows"]]
        self.assertEqual([r["ev_date"] for r in meets], ["2026-10-16", "2026-11-03", "2026-11-10"])  # 30 天前以前的不放

    def test_write(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(S.write_mops(d, Path(d) / "x.json"))
            F.write_months([row(date="2026-10-08", code="2317", subject="x")], ["2026-10"], Path(d) / "mops")
            p = S.write_mops(d, Path(d) / "out" / "mops.json", today=date(2026, 10, 9))
            self.assertEqual(json.loads((Path(d) / "out" / "mops.json").read_text(encoding="utf-8")), json.loads(json.dumps(p)))


DIV_TEXT = ("1.董事會、股東會決議或公司決定日期:115/09/30\n2.除權、息類別(請填入「除權」、「除息」或「除權息」):除息\n"
            "3.發放股利種類及金額:現金股利每股新台幣2.5元\n6.除權(息)交易日:115/10/16\n"
            "10.現金股利發放日期:115/11/06\n")
CALLS_HTML = ("<table><tr class='even' data-type='body'><td>2330</td><td>台積電</td><td>115/10/16</td><td>14:00</td>"
              "<td>台北君悅</td><td>第三季營運</td><td><input onclick='fileName.value=\"233020261016M001.pdf\"'></td><td></td>"
              "<td></td><td><a href='https://example.com/v'>影音</a></td><td></td></tr>"
              "<tr data-type='body'><td>1101</td><td>台泥</td><td>115/10/20</td><td>15:00</td><td>台北</td><td></td>"
              "<td></td><td></td><td></td><td></td><td></td></tr></table>")


class SummaryTest(unittest.TestCase):
    def test_parse_div(self):
        self.assertEqual(F.parse_div(DIV_TEXT), {"kind": "除息", "ex_date": "2026-10-16", "cash": "2.5", "stock": "", "pay_date": "2026-11-06"})
        self.assertEqual(F.summarize("div", "公告除息基準日", DIV_TEXT), "現金 2.5 元・除息交易日 2026-10-16・發放 2026-11-06")

    def test_summarize(self):
        t = "1.董事會決議日期:115/10/08\n2.買回股份目的:轉讓股份予員工\n3.預定買回之期間:115/10/09~115/12/08\n4.預定買回之數量:5,000,000股\n"
        self.assertEqual(F.summarize("buyback", "董事會決議買回股份", t), "股數：5,000,000股；期間：115/10/09~115/12/08；目的：轉讓股份予員工")
        self.assertEqual(F.summarize("board", "x", ""), "")
        hr = ("1.董事會決議日期:115/10/08\n3.舊任者姓名及簡歷:王昭卿\n4.新任者姓名及簡歷:謝凱安\n"
              "5.異動情形(請輸入「辭職」、「職務調整」、\n「退休」或「解任」):職務調整\n6.異動原因:職務調整\n")
        self.assertEqual(F.summarize("hr", "x", hr), "舊任：王昭卿；新任：謝凱安；原因：職務調整")  # 標籤跨行
        cap = "1.事實發生日:115/10/08\n2.公司名稱:振樺電子\n5.發生緣由:私募特別股申請轉換\n"
        self.assertEqual(F.summarize("capital", "x", cap), "私募特別股申請轉換")

    def test_exright_and_calls(self):
        tw = [{"Date": "1151016", "Code": "2330", "Name": "台積電", "Exdividend": "息", "StockDividendRatio": "", "CashDividend": "5.0"}]
        tp = [{"ExRrightsExDividendDate": "115/10/20", "SecuritiesCompanyCode": "8112", "CompanyName": "至上",
               "ExRrightsExDividend": "除權息", "StockDividendRatio": "0.05", "CashDividend": "1.2"}]
        self.assertEqual(F.parse_exright(tw, "sii"), [{"ex_date": "2026-10-16", "code": "2330", "name": "台積電", "market": "sii",
                                                       "kind": "除息", "cash": "5", "stock": ""}])
        self.assertEqual(F.parse_exright(tp, "otc")[0][["kind", "cash", "stock"][0]], "除權息")
        self.assertEqual((F.parse_exright(tp, "otc")[0]["stock"], F.parse_exright(tp, "otc")[0]["cash"]), ("0.5", "1.2"))
        calls = F.parse_calls(CALLS_HTML, "sii")
        self.assertEqual([(c["code"], c["date"], c["file"], c["video"]) for c in calls],
                         [("2330", "2026-10-16", "233020261016M001.pdf", "https://example.com/v"), ("1101", "2026-10-20", "", "")])

    def test_site_divs_and_calls(self):
        rows = [row(date="2026-10-01", code="2330", name="台積電", cat="div", ev_kind="除息", ev_date="2026-10-16",
                    ev_note="現金 2.5・發放 2026-11-06"),
                row(date="2026-10-01", code="2330", name="台積電", cat="call", subject="法說會", ev_kind="法說會", ev_date="2026-10-16", ev_note="14:00")]
        exr = [{"ex_date": "2026-10-16", "code": "2330", "name": "台積電", "market": "sii", "kind": "除息", "cash": "5", "stock": ""}]
        calls = F.parse_calls(CALLS_HTML, "sii")
        p = S.build(rows, today=date(2026, 10, 9), exright=exr, calls=calls)
        divs = [dict(zip(p["divs"]["cols"], r)) for r in p["divs"]["rows"]]
        self.assertEqual(divs, [{"ex_date": "2026-10-16", "code": "2330", "name": "台積電", "market": "sii", "kind": "除息",
                                 "cash": 5.0, "stock": None, "pay_date": "2026-11-06"}])
        meets = {r[1]: dict(zip(p["meets"]["cols"], r)) for r in p["meets"]["rows"]}
        self.assertEqual(meets["2330"]["link"], "https://mopsov.twse.com.tw/nas/STR/233020261016M001.pdf")
        self.assertEqual((meets["1101"]["ev_date"], meets["1101"]["ev_note"]), ("2026-10-20", "15:00 台北"))


if __name__ == "__main__":
    unittest.main()
