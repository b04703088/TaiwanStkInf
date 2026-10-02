#!/usr/bin/env python3
"""可轉債（CB）詢價圈購／競價拍賣：把每一檔從「開始圈購」到「掛牌」的關鍵時間點整理成一張表。

資料來源（都是公開頁面、免登入）
  1. 證券商業同業公會 承銷公告 https://web.twsa.org.tw/Edoc2/Default.aspx?Year=YYYY
     - 「詢價圈購」清單：圈購期間、溢價率區間、承銷／圈購張數（還在圈購、尚未訂價的案子只有這裡有）
     - 「競價拍賣」清單：投標期間、開標日（競拍案）
     - 「承銷公告」清單裡的 CB 案件 + 銷售辦法公告 PDF：訂價基準日、轉換價、溢價率、發行價、
       張數、繳款日、預定上櫃日（訂價完成後隔天左右公告）
  2. 櫃買中心 OpenAPI bond_ISSBD5_data（轉(交)換公司債發行資料）：債券代號、實際發行／上櫃日、發行轉換價

輸出 data/cb/
  cases.csv        每檔 CB 一列（見 CASE_COLS），網頁用這個
  bookbuilding.csv 詢價圈購清單原始資料
  auction.csv      競價拍賣清單原始資料（CB）
  notices.csv      承銷公告 CB 案件＋PDF 解析結果（已解析過的不會重抓 PDF）
  issued.csv       櫃買中心發行資料（公開發行、近兩年）
  companies.csv    公司全名 → 代號

用法：python fetch_cb.py [--years 2025 2026]   （預設：今年和去年）
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "cb"
EDOC = "https://web.twsa.org.tw/Edoc2/Default.aspx"
ISSBD5 = "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data"
CO_TWSE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
CO_TPEX = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
CO_EMG = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R"
DELAY = 0.6
RB = "ctl00$cphMain$rblReportType"
# 報表種類 → radio 按鈕順序（__EVENTTARGET 要帶 $index）
REPORTS = {"UnderwritingNotice": 0, "Auction": 1, "BookBuilding": 2}

BB_COLS = ["sn", "company", "lead", "type", "units", "bb_units", "bb_start", "bb_end", "premium_lo", "premium_hi"]
AU_COLS = ["sn", "company", "lead", "type", "units", "au_units", "bid_start", "bid_end", "open_date", "raw"]
NT_COLS = ["sn", "filed", "lead", "company", "type", "method", "status", "series", "issue_pct", "total_units",
           "done_date", "price_base_date", "conv_price", "premium", "pay_date", "list_expected", "parsed"]
IS_COLS = ["code", "name", "bond_code", "short", "series", "issue_date", "list_date", "maturity", "amount",
           "conv_price", "underwriter", "secured"]
CASE_COLS = ["id", "code", "company", "short", "series", "bond_code", "type", "method", "lead",
             "units", "bb_units", "bb_start", "bb_end", "premium_lo", "premium_hi", "done_date",
             "price_base_date", "conv_price", "premium", "issue_pct", "pay_date", "list_expected",
             "issue_date", "list_date", "bb_sn", "au_sn", "nt_sn"]


# ---------------- 小工具 ----------------
def _txt(cell):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell).replace("&nbsp;", " ")).strip()


def _int(s):
    s = re.sub(r"[^\d.]", "", str(s or ""))
    try:
        return int(float(s)) if s else ""
    except ValueError:
        return ""


def roc(y, m, d):
    y = int(y)
    try:
        return date(y + 1911 if y < 1911 else y, int(m), int(d)).isoformat()
    except ValueError:
        return ""


def ad(s):
    """2026/09/24、20260924 → 2026-09-24"""
    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", s or "")
    return roc(*m.groups()) if m else ""


_CN = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_num(s):
    """一 → 1、十二 → 12、二十一 → 21、12 → 12"""
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN.get(a, 1) if a else 1) * 10 + (_CN.get(b, 0) if b else 0)
    n = 0
    for ch in s:
        n = n * 10 + _CN.get(ch, 0)
    return n


def norm_company(s):
    s = re.sub(r"\s+", "", s or "").replace("臺", "台").replace("（", "(").replace("）", ")")
    return s


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


# ---------------- 公會承銷公告（ASP.NET postback） ----------------
def parse_grid(page):
    """回傳 (表頭, [[欄位...], 下載按鈕名稱])"""
    head = [_txt(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", page, re.S)]
    rows = []
    for r in re.findall(r'<tr style="color:#[0-9A-Fa-f]+;background-color:#[0-9A-Fa-f]+;font-size:12px;">(.*?)</tr>',
                        page, re.S):
        tds = [_txt(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        btn = re.search(r'name="([^"]+imgbtnFileName)"', r)
        rows.append((tds, btn.group(1) if btn else None))
    return head, rows


def _hidden(page):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', page))


class Edoc:
    """一個年度、一種報表的清單頁；保留 ASP.NET 隱藏欄位以便下載 PDF。"""

    def __init__(self, year, report):
        self.year, self.report = year, report
        self.url = f"{EDOC}?Year={year}"
        page = self._post(None)
        if report != "UnderwritingNotice":
            form = _hidden(page)
            form.update({"ctl00$cphMain$ddlYear": str(year), RB: report,
                         "__EVENTTARGET": f"{RB}${REPORTS[report]}"})
            page = self._post(form)
        self.page = page
        self.form = _hidden(page)
        self.head, self.rows = parse_grid(page)

    def _post(self, form):
        raw = C.http(self.url, form=form, raw=True, headers={"Referer": self.url, "Accept": "text/html,*/*"})
        return raw.decode("utf-8", errors="replace")

    def pdf(self, btn):
        form = dict(self.form)
        form.update({"ctl00$cphMain$ddlYear": str(self.year), RB: self.report, btn + ".x": "8", btn + ".y": "8"})
        body = C.http(self.url, form=form, raw=True, headers={"Referer": self.url, "Accept": "application/pdf,*/*"})
        if body[:4] != b"%PDF":
            raise C.AdapterError("回應不是 PDF")
        return body


def _col(head, *keys):
    for i, h in enumerate(head):
        if all(k in h for k in keys):
            return i
    return None


def parse_bookbuilding(head, rows):
    """詢價圈購清單 → BB_COLS（只留轉換／交換公司債）。"""
    out = []
    for tds, _ in rows:
        if len(tds) < 8 or "公司債" not in tds[3]:
            continue
        period = re.findall(r"\d{4}/\d{1,2}/\d{1,2}", tds[6])
        prem = re.findall(r"([\d.]+)\s*%", tds[7])
        out.append({"sn": tds[0], "company": norm_company(tds[1]), "lead": tds[2], "type": tds[3],
                    "units": _int(tds[4]), "bb_units": _int(tds[5]),
                    "bb_start": ad(period[0]) if period else "", "bb_end": ad(period[-1]) if period else "",
                    "premium_lo": prem[0] if prem else "", "premium_hi": prem[-1] if prem else ""})
    return out


def parse_auction(head, rows):
    """競價拍賣清單 → AU_COLS（欄位依表頭名稱對應；只留公司債）。"""
    ix = {"company": _col(head, "發行公司"), "lead": _col(head, "主辦"), "type": _col(head, "性質"),
          "units": _col(head, "承銷"), "au_units": _col(head, "競拍") or _col(head, "拍賣"),
          "bid": _col(head, "投標"), "open": _col(head, "開標")}
    out = []
    for tds, _ in rows:
        raw = "|".join(tds)
        if "公司債" not in raw:
            continue

        def g(k):
            i = ix[k]
            return tds[i] if i is not None and i < len(tds) else ""
        period = re.findall(r"\d{4}/\d{1,2}/\d{1,2}", g("bid"))
        out.append({"sn": tds[0], "company": norm_company(g("company")), "lead": g("lead"), "type": g("type"),
                    "units": _int(g("units")), "au_units": _int(g("au_units")),
                    "bid_start": ad(period[0]) if period else "", "bid_end": ad(period[-1]) if period else "",
                    "open_date": ad(g("open")), "raw": raw})
    return out


def parse_notice_list(head, rows):
    """承銷公告清單 → CB 案件（含下載按鈕）。"""
    out = []
    for tds, btn in rows:
        if len(tds) < 10 or not re.search(r"[轉交]換公司債", tds[6]):
            continue
        out.append({"sn": tds[0], "filed": ad(tds[1]), "lead": tds[2], "company": norm_company(tds[3]),
                    "type": tds[6], "method": tds[7], "status": tds[9], "_btn": btn})
    return out


# ---------------- 銷售辦法公告 PDF 解析 ----------------
_D = r"(\d{2,4})年(\d{1,2})月(\d{1,2})日"


def _find_date(t, *pats):
    for p in pats:
        m = re.search(p.replace("<D>", _D), t)
        if m:
            return roc(*m.groups()[-3:])
    return ""


def parse_notice(text):
    """銷售辦法公告全文 → 關鍵欄位（找不到的留空）。"""
    t = re.sub(r"\s+", "", text).replace("臺", "台").replace("（", "(").replace("）", ")").replace("：", ":")
    r = {}
    m = re.search(r"國內第([一二三四五六七八九十〇零\d]+)次", t)
    r["series"] = cn_num(m.group(1)) if m else ""
    m = re.search(r"(?:面額|票面金額)之?([\d.]+)%(?:發行|溢價發行)", t)
    if m:
        r["issue_pct"] = m.group(1)
    elif "十足發行" in t:
        r["issue_pct"] = "100"
    else:
        m = re.search(r"承銷價格為([\d.]+)元", t)
        r["issue_pct"] = m.group(1) if m else ""
    m = re.search(r"共計發行([\d,]+)張", t) or re.search(r"發行總張數為?([\d,]+)張", t)
    r["total_units"] = _int(m.group(1)) if m else ""
    r["done_date"] = _find_date(t, r"(?:詢價圈購|競價拍賣)作業(?:已)?於<D>完成")
    r["price_base_date"] = _find_date(t, r"以<D>為(?:訂價|轉換價格)基準日", r"訂價基準日(?:為|:)<D>")
    m = (re.search(r"轉換價格(?:訂)?為(?:每股)?(?:新台幣)?([\d,]+(?:\.\d+)?)元", t)
         or re.search(r"轉換價格(?:訂)?為(?:每股)?(?:新台幣)?([\d,]+(?:\.\d+)?)", t))
    r["conv_price"] = m.group(1).replace(",", "") if m else ""
    m = re.search(r"溢價率(?:為|訂為)?([\d.]+)%", t)
    r["premium"] = m.group(1) if m else ""
    r["pay_date"] = _find_date(t, r"繳款日[^()]{0,8}\(即<D>\)", r"繳款截止日(?:為|:)?<D>",
                               r"繳存往來銀行截止日為<D>", r"繳款期間[^。]{0,30}至<D>")
    r["list_expected"] = _find_date(t, r"預定(?:於|為)<D>(?:掛牌)?上櫃", r"上櫃日期預定為<D>",
                                    r"預定於<D>", r"預定上櫃日(?:期)?(?:為|:)<D>")
    return r


def pdf_text(content):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(pg.extract_text() or "" for pg in pdf.pages[:4])


# ---------------- 公司代號、櫃買發行資料 ----------------
def load_companies(refresh=True):
    p = OUT / "companies.csv"
    rows = []
    if refresh:
        for url, code_k, name_k, abbr_k in ((CO_TWSE, "公司代號", "公司名稱", "公司簡稱"),
                                           (CO_TPEX, "SecuritiesCompanyCode", "CompanyName", "CompanyAbbreviation"),
                                           (CO_EMG, "SecuritiesCompanyCode", "CompanyName", "CompanyAbbreviation")):
            try:
                for c in C.http(url):
                    if c.get(code_k) and c.get(name_k):
                        rows.append({"code": c[code_k].strip(), "name": norm_company(c[name_k]),
                                     "abbr": (c.get(abbr_k) or "").strip()})
            except Exception as e:  # noqa: BLE001
                print(f"公司基本資料抓取失敗 {url}：{e}", file=sys.stderr)
    if len(rows) > 1500:
        _write(p, ["code", "name", "abbr"], rows)
        return rows
    return _read(p) or rows


def company_mapper(companies, issued):
    full = {}
    for c in companies:
        full.setdefault(c["name"], c["code"])
    shorts = sorted(((re.sub(r"[-*].*$", "", i["name"]), i["code"]) for i in issued if i["name"]),
                    key=lambda x: -len(x[0]))
    shorts += sorted(((c["abbr"], c["code"]) for c in companies if len(c.get("abbr") or "") >= 2),
                     key=lambda x: -len(x[0]))

    def f(name):
        name = norm_company(name)
        if name in full:
            return full[name]
        base = name.replace("股份有限公司", "")
        for k, v in full.items():
            if k.replace("股份有限公司", "") == base:
                return v
        for s, code in shorts:
            if s and base.startswith(s):
                return code
        return ""
    return f


def parse_issbd5(data, since):
    out = []
    for x in data:
        if x.get("OfferingMethod") == "8" or (x.get("Underwriter") or "無") == "無":
            continue  # 私募
        if (x.get("IssueDate") or "") < since.replace("-", ""):
            continue
        cp = C.num(x.get("Conversion/ExchangePriceAtIssuance"))
        out.append({"code": x["IssuerCode"].strip(), "name": (x.get("IssuerName") or "").strip(),
                    "bond_code": x.get("BondCode", "").strip(), "short": (x.get("ShortName") or "").strip(),
                    "series": _int(x.get("SeriesNumber")), "issue_date": ad(x.get("IssueDate")),
                    "list_date": ad(x.get("ListingDate")), "maturity": ad(x.get("MaturityDate")),
                    "amount": _int(x.get("IssueAmount")), "conv_price": "" if cp is None else f"{cp:g}",
                    "underwriter": re.sub(r"^\w{3,4}T", "", x.get("Underwriter") or ""),
                    "secured": {"1": "有擔保", "2": "無擔保"}.get(x.get("Guaranteed"), "")})
    return out


# ---------------- 合併 ----------------
def _near(d1, d2, lo, hi):
    if not d1 or not d2:
        return False
    delta = (date.fromisoformat(d1) - date.fromisoformat(d2)).days
    return lo <= delta <= hi


def merge(bb, au, notices, issued, code_of):
    """把四個來源拼成一檔一列。"""
    cases = []
    nt_used, is_used = set(), set()
    by_code_series = {(i["code"], str(i["series"])): i for i in issued}

    def new_case(**kw):
        c = {k: "" for k in CASE_COLS}
        c.update(kw)
        cases.append(c)
        return c

    def attach_notice(c, n):
        nt_used.add(n["sn"])
        c["nt_sn"] = n["sn"]
        c["method"] = c["method"] or n["method"]
        c["type"] = c["type"] or n["type"]
        c["lead"] = c["lead"] or n["lead"]
        for k in ("series", "done_date", "price_base_date", "conv_price", "premium", "issue_pct",
                  "pay_date", "list_expected"):
            if n.get(k) not in (None, ""):
                c[k] = n[k]
        if n.get("total_units"):
            c["units"] = n["total_units"]

    notices = [n for n in notices if n.get("status") != "撤銷"]
    by_company = {}
    for n in notices:
        by_company.setdefault(n["company"], []).append(n)

    def find_notice(company, start, end):
        for n in sorted(by_company.get(company, []), key=lambda n: n["sn"]):
            if n["sn"] in nt_used:
                continue
            if n.get("done_date") and _near(n["done_date"], end, -1, 3):
                return n
            if not n.get("done_date") and _near(n["filed"], end, -20, 3):
                return n
        return None

    for b in sorted(bb, key=lambda b: b["bb_start"]):
        c = new_case(company=b["company"], code=code_of(b["company"]), type=b["type"], method="詢價圈購",
                     lead=b["lead"], units=b["units"], bb_units=b["bb_units"], bb_start=b["bb_start"],
                     bb_end=b["bb_end"], premium_lo=b["premium_lo"], premium_hi=b["premium_hi"], bb_sn=b["sn"])
        n = find_notice(b["company"], b["bb_start"], b["bb_end"])
        if n:
            attach_notice(c, n)

    for a in sorted(au, key=lambda a: a["bid_start"]):
        end = a["open_date"] or a["bid_end"]
        c = new_case(company=a["company"], code=code_of(a["company"]), type=a["type"], method="競價拍賣",
                     lead=a["lead"], units=a["units"], bb_units=a["au_units"], bb_start=a["bid_start"],
                     bb_end=end, au_sn=a["sn"])
        n = find_notice(a["company"], a["bid_start"], end)
        if n:
            attach_notice(c, n)

    for n in notices:
        if n["sn"] not in nt_used:
            c = new_case(company=n["company"], code=code_of(n["company"]))
            attach_notice(c, n)

    for c in cases:
        i = by_code_series.get((c["code"], str(c["series"])))
        if i:
            is_used.add(id(i))
            c.update(bond_code=i["bond_code"], short=i["short"], issue_date=i["issue_date"],
                     list_date=i["list_date"])
            c["conv_price"] = i["conv_price"] or c["conv_price"]
    for i in issued:
        if id(i) not in is_used:
            new_case(code=i["code"], company=i["name"], short=i["short"], series=i["series"],
                     bond_code=i["bond_code"], type=i["secured"] + "轉換公司債" if i["secured"] else "",
                     lead=i["underwriter"], units=(i["amount"] or 0) // 100000 or "", conv_price=i["conv_price"],
                     issue_date=i["issue_date"], list_date=i["list_date"])

    for c in cases:
        c["id"] = f"{c['code']}-{c['series']}" if c["code"] and c["series"] else (
            "bb" + c["bb_sn"] if c["bb_sn"] else "au" + c["au_sn"] if c["au_sn"] else "nt" + c["nt_sn"])
    cases.sort(key=lambda c: (c["bb_start"] or c["done_date"] or c["issue_date"] or "", c["id"]), reverse=True)
    return cases


# ---------------- 主程式 ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    this = datetime.now(C.TPE).year
    ap.add_argument("--years", type=int, nargs="*", default=[this - 1, this])
    ap.add_argument("--max-pdf", type=int, default=400, help="這次最多下載幾份 PDF")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    errors, log = [], {}

    old_bb = {r["sn"]: r for r in _read(OUT / "bookbuilding.csv")}
    old_au = {r["sn"]: r for r in _read(OUT / "auction.csv")}
    old_nt = {r["sn"]: r for r in _read(OUT / "notices.csv")}
    bb, au, nts = dict(old_bb), dict(old_au), dict(old_nt)
    pdf_budget = a.max_pdf
    today = datetime.now(C.TPE).date()

    for y in a.years:
        for report in ("BookBuilding", "Auction", "UnderwritingNotice"):
            try:
                ed = Edoc(y, report)
                time.sleep(DELAY)
            except C.AdapterError as e:
                errors.append(f"{y} {report}: {e}")
                continue
            log[f"{y}-{report}"] = {"head": ed.head, "rows": len(ed.rows)}
            if report == "BookBuilding":
                for r in parse_bookbuilding(ed.head, ed.rows):
                    bb[r["sn"]] = r
            elif report == "Auction":
                rows = parse_auction(ed.head, ed.rows)
                log[f"{y}-Auction"]["sample"] = rows[-2:]
                for r in rows:
                    au[r["sn"]] = r
            else:
                for n in parse_notice_list(ed.head, ed.rows):
                    btn = n.pop("_btn")
                    prev = old_nt.get(n["sn"])
                    recent = n["filed"] and (today - date.fromisoformat(n["filed"])).days <= 30
                    # 解析成功的不重抓；解析失敗的在申報後 30 天內重試（申報當下 PDF 可能還沒有訂價結果）
                    if prev and (prev.get("parsed") == "1" or (prev.get("parsed") == "0" and not recent)):
                        nts[n["sn"]] = {**prev, **n}
                        continue
                    if not btn or pdf_budget <= 0:
                        nts[n["sn"]] = {**(prev or {}), **n}
                        continue
                    pdf_budget -= 1
                    try:
                        info = parse_notice(pdf_text(ed.pdf(btn)))
                        ok = bool(info["series"] and info["conv_price"])
                        nts[n["sn"]] = {**n, **info, "parsed": "1" if ok else "0"}
                        if not ok:
                            print(f"  {n['sn']} {n['company']}：PDF 欄位不完整 {info}", file=sys.stderr)
                    except Exception as e:  # noqa: BLE001
                        if recent:  # 剛申報的案子 PDF 可能還沒上傳
                            print(f"  {n['sn']} {n['company']} PDF 尚未取得：{e}")
                        else:
                            errors.append(f"{n['sn']} {n['company']} PDF：{e}")
                        nts[n["sn"]] = {**(prev or {}), **n}
                    time.sleep(DELAY)

    since = f"{min(a.years)}-01-01"
    issued = []
    try:
        issued = parse_issbd5(C.http(ISSBD5), since)
        _write(OUT / "issued.csv", IS_COLS, issued)
    except C.AdapterError as e:
        errors.append(f"櫃買發行資料：{e}")
        issued = _read(OUT / "issued.csv")

    code_of = company_mapper(load_companies(), issued)
    bb_rows = sorted(bb.values(), key=lambda r: r["sn"])
    au_rows = sorted(au.values(), key=lambda r: r["sn"])
    nt_rows = sorted(nts.values(), key=lambda r: r["sn"])
    _write(OUT / "bookbuilding.csv", BB_COLS, bb_rows)
    _write(OUT / "auction.csv", AU_COLS, au_rows)
    _write(OUT / "notices.csv", NT_COLS, nt_rows)
    cases = merge(bb_rows, au_rows, nt_rows, issued, code_of)
    _write(OUT / "cases.csv", CASE_COLS, cases)
    log.update({"generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "errors": errors,
                "unmapped": sorted({c["company"] for c in cases if not c["code"]})})
    (OUT / "sources.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"詢圈 {len(bb_rows)}、競拍 {len(au_rows)}、承銷公告 {len(nt_rows)}、櫃買發行 {len(issued)} → {len(cases)} 檔")
    for e in errors:
        print("錯誤：" + e, file=sys.stderr)
    if log["unmapped"]:
        print("對不到代號：" + "、".join(log["unmapped"]), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
