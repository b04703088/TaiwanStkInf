"""各投信 ETF 持股 adapter。每個函式 adapter(code, name) 回傳 (資料日 'YYYY-MM-DD', 持股 list, 基本面 dict)。

資料日一律用「持股基準日」（T），不是 PCF 公告生效日（T+1），各家才能對齊比較。
持股只取股票部位（台股 + 海外），期貨、選擇權、現金不列入。
"""
import html
import json
import re
from datetime import datetime, timedelta

import etf_common as C
from etf_common import AdapterError, holding, num, iso, code_of, is_security

ADAPTERS = {}
SOURCE_IDS = {}  # 需要掃描才能查到的內部代碼（第一金），由 fetch_etf 讀寫快取


def adapter(name):
    def deco(fn):
        ADAPTERS[name] = fn
        return fn
    return deco


def _lookup_id(issuer, code, loader):
    """投信內部代碼對照：先試線上清單（成功就存進快取），清單端點失敗時退回上次的快取。"""
    cache = SOURCE_IDS.setdefault(issuer, {})
    try:
        fresh = loader()
        cache.update({k: v for k, v in fresh.items() if k and v})
    except AdapterError:
        if code not in cache:
            raise
    fid = cache.get(code)
    if not fid:
        raise AdapterError(f"{issuer} {code}: 基金清單找不到這檔")
    return fid


def _meta(aum=None, units=None, nav=None):
    return {"aum": num(aum), "units": num(units), "nav": num(nav)}


def _rows(items, code_k, name_k, shares_k, weight_k):
    out = []
    for x in items or []:
        h = holding(x.get(code_k), x.get(name_k), num(x.get(shares_k)), num(x.get(weight_k)))
        if is_security(h["code"]):
            out.append(h)
    return out


def _html_rows(segment, ncols=4):
    """從 HTML 片段抓 <tr> 裡前 ncols 個 <td>：[代號, 名稱, 股數, 權重]；代號重複出現就停（手機版重複表格）。"""
    out, seen = [], set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", segment, re.S):
        tds = [re.sub(r"<[^>]+>", "", html.unescape(td)).strip()
               for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) < ncols:
            continue
        h = holding(tds[0], tds[1], num(tds[2]), num(tds[3]))
        if not is_security(h["code"]):
            continue
        if h["code"] in seen:
            break
        seen.add(h["code"])
        out.append(h)
    return out


# ---------------- 元大 ----------------
# etfapi.yuantaetfs.com 的 bridge（參數取自官網 __NUXT__.globalSetting）。
# FundWeights.StockWeights 是官方總持股股數與權重。
YUANTA_BRIDGE = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"


@adapter("yuanta")
def yuanta(code, name=""):
    import uuid
    d = C.http(YUANTA_BRIDGE, {
        "APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS", "PageName": f"/product/detail/{code}/ratio",
        "DeviceId": str(uuid.uuid4()), "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3",
        "Platform": "ETF", "ticker": code,
    }, headers={"Referer": f"https://www.yuantaetfs.com/product/detail/{code}/ratio"})
    if isinstance(d, dict) and "Data" in d and "PCF" not in d:
        d = d["Data"]
    d = d or {}
    pcf = d.get("PCF") or {}
    if not pcf.get("trandate"):
        raise AdapterError(f"yuanta {code}: 回應沒有 PCF（keys={list(d.keys())[:8]}）")
    rows = _rows((d.get("FundWeights") or {}).get("StockWeights"), "code", "name", "qty", "weights")
    if not rows:  # 只有每基數股數時不推算總股數，當作沒有資料
        raise AdapterError(f"yuanta {code}: 沒有 StockWeights 持股資料")
    return iso(pcf["trandate"]), rows, _meta(pcf.get("totalav"), pcf.get("osunit"), pcf.get("nav"))


# ---------------- 富邦 ----------------
FUBON_ASSETS = "https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx"


def _p_pair(page, label):
    m = re.search(r"<p>\s*" + re.escape(label) + r"[^<]*</p>\s*<p>\s*([\d,.]+)\s*</p>", page)
    return m.group(1) if m else None


@adapter("fubon")
def fubon(code, name=""):
    page = C.http(FUBON_ASSETS, {"stkId": code, "lan": "TW"}, as_json=False)
    m = re.search(r"資料日期：\s*(\d{4}/\d{1,2}/\d{1,2})", page)
    rows = []
    for c, n, s, w in re.findall(
            r'<tr>\s*<td class="tac">([^<]+)</td>\s*<td>([^<]+)</td>\s*<td class="tar">([\d,]+)</td>'
            r'\s*<td class="tar">[\d,.-]+</td>\s*<td class="tar">([\d.]+)</td>', page):
        h = holding(c, n, num(s), num(w))
        if is_security(h["code"]):  # 期貨列代號如 WTXV6F 會被排除
            rows.append(h)
    if not m:
        raise AdapterError(f"fubon {code}: 找不到資料日期")
    return iso(m.group(1)), rows, _meta(_p_pair(page, "基金淨資產"), _p_pair(page, "基金在外流通單位數"),
                                        _p_pair(page, "基金每單位淨值"))


# ---------------- 國泰 ----------------
# 內部 FundCode 是兩碼（00878 = CN）。
# 持股：ETF/GetETFDetailStockList {fundCode, SearchDate} → 代號、名稱、持有股數（volumn）、權重，
#       即官網 ETF 詳情頁「持股權重」分頁（tab=etf3）的資料；SearchDate 必填，可查歷史。
# 資料日與規模：ETF/GetETFAssets → preDate（持股基準日）、基金淨資產、流通單位數、單位淨值。
# （不要用 PCF 的每基數股數 × 單位數推算總股數：會把申購贖回誤當成買賣，數字也不準。）
CATHAY = "https://cwapi.cathaysite.com.tw/api/"
_cathay_map = None


def _cathay(path, params):
    d = C.http(CATHAY + path, params)
    if not d.get("success"):
        raise AdapterError(f"cathay {path}: {d.get('returnMessage')}")
    return d.get("result")


def _cathay_fund(code):
    def load():
        global _cathay_map
        if _cathay_map is None:
            res = _cathay("ETF/GetETFList", {"FundType": "", "PerPageCount": 9999, "status": 1})
            rows = res if isinstance(res, list) else (res or {}).get("list") or []
            _cathay_map = {r.get("stockCode"): r.get("fundCode") for r in rows if r.get("stockCode")}
        return _cathay_map
    return _lookup_id("cathay", code, load)


def cathay_holdings(fc, date):
    """指定持股基準日（'YYYY-MM-DD'）的持股；該日沒有資料回空 list。"""
    d = C.http(CATHAY + "ETF/GetETFDetailStockList", {"fundCode": fc, "SearchDate": date.replace("-", "/")})
    rows = []
    for r in (d.get("result") or []) if d.get("success") else []:
        h = holding(r.get("stockCode"), r.get("stockName"), num(r.get("volumn")), num(r.get("weights")))
        if is_security(h["code"]):
            rows.append(h)
    return rows


@adapter("cathay")
def cathay(code, name=""):
    fc = _cathay_fund(code)
    assets = _cathay("ETF/GetETFAssets", {"fundCode": fc}) or {}
    meta = _meta(assets.get("fundNav"), assets.get("fundOutstandingShares"), assets.get("fundPerNav"))
    dates = [iso(assets["preDate"])] if assets.get("preDate") else []
    dates += [d.isoformat() for d in C.recent_days(8) if d.isoformat() not in dates]
    for d in dates:
        rows = cathay_holdings(fc, d)
        if rows:
            return d, rows, (meta if dates and d == dates[0] else _meta())
    raise AdapterError(f"cathay {code}: 最近幾個工作天都查無持股")


# ---------------- 群益 ----------------
CAPITAL = "https://www.capitalfund.com.tw/CFWeb/api/etf/"
_capital_map = None


@adapter("capital")
def capital(code, name=""):
    def load():
        global _capital_map
        if _capital_map is None:
            items = C.http(CAPITAL + "items", body={})
            _capital_map = {f.get("stockNo"): f.get("fundNo") for f in items.get("data", []) if f.get("stockNo")}
        return _capital_map
    fid = _lookup_id("capital", code, load)
    d = (C.http(CAPITAL + "buyback", body={"fundId": fid}) or {}).get("data") or {}
    pcf = d.get("pcf") or {}
    if not pcf.get("date2"):
        raise AdapterError(f"capital {code}: 沒有 PCF")
    rows = _rows(d.get("stocks"), "stocNo", "stocName", "share", "weight")
    return iso(pcf["date2"]), rows, _meta(pcf.get("nav"), pcf.get("totUnit"), pcf.get("pUnit"))


# ---------------- 復華 ----------------
FH = "https://www.fhtrust.com.tw/api/"
_fh_map = None


@adapter("fuhhwa")
def fuhhwa(code, name=""):
    def load():
        global _fh_map
        if _fh_map is None:
            fl = C.http(FH + "fundList?ec001=3")
            _fh_map = {f.get("etf002"): f.get("fundID") for f in fl.get("result", []) if f.get("etf002")}
        return _fh_map
    fid = _lookup_id("fuhhwa", code, load)
    for d in C.recent_days(10):
        res = ((C.http(FH + "assets", {"fundID": fid, "qDate": d.strftime("%Y/%m/%d")}) or {}).get("result") or [{}])[0]
        detail = [x for x in (res.get("detail") or []) if x.get("ftype") == "股票"]
        if res.get("dDate") and detail:
            rows = _rows(detail, "stockid", "stockname", "qshare", "prate_addaccint")
            return iso(res["dDate"]), rows, _meta(res.get("pcf_FundNav"), res.get("pcf_FundQissue"), res.get("pcf_Fundpnav"))
    raise AdapterError(f"fuhhwa {code}: 最近 10 個工作天都沒有資料")


# ---------------- 統一 ----------------
# PCF 頁的 #DataFundList data-content 是 html-escaped JSON（代號 ↔ 內部 fundCode）；
# GetPCF 帶未來日 + specificDate=false 回最新一份。
EZ = "https://www.ezmoney.com.tw/ETF/Transaction/"
_ez_map = None


@adapter("president")
def president(code, name=""):
    global _ez_map
    if _ez_map is None:
        page = C.http(EZ + "PCF", as_json=False)
        m = re.search(r'id="DataFundList"[^>]*data-content="([^"]*)"', page)
        if not m:
            raise AdapterError("president: PCF 頁找不到基金清單")
        lst = json.loads(html.unescape(m.group(1)))
        _ez_map = {str(f.get("sStockNo")).strip(): f.get("sFundCode") for f in lst if f.get("sStockNo")}
    fc = _ez_map.get(code)
    if not fc:
        raise AdapterError(f"president {code}: 基金清單找不到這檔")
    future = datetime.now(C.TPE).date() + timedelta(days=30)
    roc = f"{future.year - 1911}/{future.month:02d}/{future.day:02d}"
    d = C.http(EZ + "GetPCF", body={"fundCode": fc, "date": roc, "specificDate": False},
               headers={"Referer": EZ + "PCF", "X-Requested-With": "XMLHttpRequest"})
    assets = C.find_key(d, "asset") or []
    stocks = next((a.get("Details") for a in assets if a.get("AssetCode") == "ST"), None) or []
    pcf = (C.find_key(d, "pcf") or [{}])
    pcf = pcf[0] if isinstance(pcf, list) and pcf else (pcf if isinstance(pcf, dict) else {})
    if not pcf.get("TranDate"):
        raise AdapterError(f"president {code}: 回應沒有 TranDate（keys={list(d.keys())[:8] if isinstance(d, dict) else type(d)}）")
    rows = _rows(stocks, "DetailCode", "DetailName", "Share", "NavRate")
    return iso(pcf["TranDate"]), rows, _meta(pcf.get("TotalNav") or pcf.get("NetAsset"),
                                            pcf.get("TotalUnit") or pcf.get("OutstandingUnits"), pcf.get("Nav"))


# ---------------- 中信 ----------------
# 先取 token；API 回應可能是雙層 JSON（C.http 會自動再 parse）。StartDate 必填，逐日往回試。
CTBC = "https://www.ctbcinvestments.com.tw/API/"
_ctbc = {}


@adapter("ctbc")
def ctbc(code, name=""):
    if "token" not in _ctbc:
        t = C.http(CTBC + "home/AuthToken?token=www.ctbcinvestments.com", body={})
        _ctbc["token"] = C.find_key(t, "token")
        lst = C.http(CTBC + "etf/ETFList", {"token": _ctbc["token"]}, body={})
        data = C.find_key(lst, "Data")
        data = data.get("Data") if isinstance(data, dict) else data
        _ctbc["map"] = {str(x.get("ETF_ID")).strip(): x.get("FID") for x in (data or []) if x.get("ETF_ID")}
    fid = _ctbc["map"].get(code)
    if not fid:
        raise AdapterError(f"ctbc {code}: ETF 清單找不到這檔")
    for d in C.recent_days(10):
        r = C.http(CTBC + "etf/ETFHoldingWeight", {"token": _ctbc["token"]},
                   body={"FID": fid, "StartDate": d.strftime("%Y/%m/%d")})
        data = r.get("Data") if isinstance(r, dict) else None
        if not data or (isinstance(r, dict) and str(r.get("ResultCode")) == "1"):
            continue
        fa = (data.get("FundAssets") or [{}])[0]
        stock = next((x.get("Data") for x in (data.get("FundAssetsDetail") or []) if x.get("Code") == "STOCK"), None)
        if fa.get("資料日期") and stock:
            rows = _rows(stock, "code_", "name_", "qty_", "weights_")
            return iso(fa["資料日期"]), rows, _meta(fa.get("基金淨資產價值") or fa.get("淨資產"),
                                                   fa.get("已發行受益權單位總數"), fa.get("每受益權單位淨資產價值"))
    raise AdapterError(f"ctbc {code}: 最近 10 個工作天都沒有資料")


# ---------------- 野村 ----------------
# Date 必須恰好是 PCF 公告日，逐日往回試；CNavDtStr 才是持股基準日。
NOMURA = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundTradeInfo"


@adapter("nomura")
def nomura(code, name=""):
    for d in C.recent_days(10, datetime.now(C.TPE).date() + timedelta(days=1)):
        r = C.http(NOMURA, body={"Type": 1, "Keyword": "", "FundNo": code, "Date": d.isoformat()})
        e = C.find_key(r, "Entries")
        if isinstance(e, list):
            e = e[0] if e else None
        if not e or not e.get("Stocks"):
            continue
        rows = _rows(e["Stocks"], "CStockCode", "CStockName", "CQuantity", "CWeightsPct")
        return iso(e.get("CNavDtStr") or e.get("CNavDt")), rows, _meta(
            e.get("CAnceTotalAv"), e.get("CAnceTotalIssues"), e.get("CAnceNav"))
    raise AdapterError(f"nomura {code}: 最近 10 個工作天都沒有資料")


# ---------------- 安聯 ----------------
# 與野村同一套供應商，但要 session + X-XSRF-TOKEN，持股在 DynamicTableData（標題「股票 (xx%)」）。
ALLIANZ = "https://etf.allianzgi.com.tw"
_allianz = {}


def _allianz_post(path, body):
    return C.http(ALLIANZ + "/webapi/api/" + path, body=body,
                  headers={"X-XSRF-TOKEN": _allianz["token"], "Referer": ALLIANZ + "/list-trade"})


@adapter("allianz")
def allianz(code, name=""):
    if "token" not in _allianz:
        C.http(ALLIANZ + "/list-trade", as_json=False)
        t = C.http(ALLIANZ + "/webapi/api/AntiForgery/GetAntiForgeryToken")
        _allianz["token"] = t if isinstance(t, str) else (C.find_key(t, "token") or C.find_key(t, "Token")
                                                            or C.find_key(t, "Entries"))
        types = C.find_key(_allianz_post("Category/GetFundTypeDropdownOptions", {}), "Entries") or []
        m = {}
        for ty in types:
            opts = C.find_key(_allianz_post("Category/GetFundDropdownOptions", {"TypeId": ty.get("Id")}), "Entries") or []
            for o in opts:
                if o.get("SecuritiesCode"):
                    m[str(o["SecuritiesCode"]).strip()] = o.get("FundNo")
        _allianz["map"] = m
    fno = _allianz["map"].get(code)
    if not fno:
        raise AdapterError(f"allianz {code}: 基金清單找不到這檔")
    for d in C.recent_days(10, datetime.now(C.TPE).date() + timedelta(days=1)):
        r = _allianz_post("Fund/GetFundTradeInfo", {"Type": 1, "Keyword": "", "FundNo": fno, "Date": d.isoformat()})
        tables = C.find_key(r, "DynamicTableData") or []
        stock = next((t for t in tables if str(t.get("TableTitle", "")).startswith("股票")), None)
        if not stock or not stock.get("Rows"):
            continue
        rows = []
        for row in stock["Rows"]:
            if len(row) >= 5:
                h = holding(row[1], row[2], num(row[3]), num(row[4]))
                if is_security(h["code"]):
                    rows.append(h)
        e = C.find_key(r, "Entries") or {}
        e = e if isinstance(e, dict) else {}
        base = e.get("CNavDtStr") or e.get("CNavDt")
        if not base:
            raise AdapterError(f"allianz {code}: 回應沒有持股基準日 CNavDt")
        return iso(base), rows, _meta(e.get("CAnceTotalAv"), e.get("CAnceTotalIssues"), e.get("CAnceNav"))
    raise AdapterError(f"allianz {code}: 最近 10 個工作天都沒有資料")


# ---------------- 交易日曆 ----------------
def previous_trading_day(announce):
    """公告日（T+1）→ 持股基準日（T）：往前找最近一個有收盤行情檔的交易日；
    若那天就是今天（行情還沒抓），今天是平日且不在已知假日表也算。"""
    from pathlib import Path
    root = Path(__file__).resolve().parent / "data"
    holidays = set()
    hp = root / "no_trading_days.txt"
    if hp.exists():
        holidays = set(hp.read_text().split())
    today = datetime.now(C.TPE).date()
    d = datetime.strptime(announce, "%Y-%m-%d").date()
    for _ in range(15):
        d -= timedelta(days=1)
        if (root / f"{d:%Y}" / f"{d:%Y%m%d}.csv").exists():
            return d.isoformat()
        if d == today and d.weekday() < 5 and d.isoformat() not in holidays:
            return d.isoformat()
    return None


# ---------------- 凱基 ----------------
# 純 HTML：RedemptionList 下拉選單「名稱 ↔ fundID」，Detail 頁有持股表（桌機/手機重複兩份，只取第一份）。
# 凱基標的是公告日（比各家 PCF 的持股基準日新一個交易日），換算回基準日才能與其他家對齊。
KGI = "https://www.kgifund.com.tw/Fund/"
_kgi_map = None


def _match_name(options, name, code):
    """選單文字對應：完全相同 > 包含 > 去掉「主動」前綴後包含。"""
    for v, t in options:
        if t == name or code in t:
            return v
    for v, t in options:
        if name in t or t in name:
            return v
    base = name.replace("主動", "")
    for v, t in options:
        if base and base in t:
            return v
    return None


@adapter("kgi")
def kgi(code, name=""):
    global _kgi_map
    if _kgi_map is None:
        page = html.unescape(C.http(KGI + "RedemptionList", as_json=False))
        _kgi_map = [(v, re.sub(r"\s+", "", t)) for v, t in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', page)]
    fid = _match_name(_kgi_map, name, code)
    if not fid:
        raise AdapterError(f"kgi {code}: 選單找不到「{name}」")
    page = html.unescape(C.http(KGI + "Detail", {"fundID": fid}, as_json=False))
    m = re.search(r"持股比重\s*(?:</div>\s*<p[^>]*>)?\s*[（(]\s*(\d{4}/\d{1,2}/\d{1,2})", page)
    if not m:
        raise AdapterError(f"kgi {code}: 找不到持股比重日期")
    rows = _html_rows(page[m.end():])
    base = previous_trading_day(iso(m.group(1)))
    if not base:
        raise AdapterError(f"kgi {code}: 無法由公告日 {m.group(1)} 推回持股基準日")
    return base, rows, _meta()


# ---------------- 台新 ----------------
# 代號是網址參數；只掃「股數」表頭之後（期貨表頭是「口數」）。代號是 '2330 TT' 格式。
# 隱藏欄位 NAV_DATE 是持股基準日；PUB_DATE / DATA_DATE 是公告日（T+1），不能用。
@adapter("taishin")
def taishin(code, name=""):
    page = C.http(f"https://www.tsit.com.tw/ETF/Home/ETFSeriesDetail/{code}", as_json=False)
    m = re.search(r'id="NAV_DATE"[^>]*value="([^"]+)"', page) or \
        re.search(r"資料日期[：:\s]*(\d{4}[/-]\d{1,2}[/-]\d{1,2})", page)
    i = page.find("股數")
    if not m or i < 0:
        raise AdapterError(f"taishin {code}: 找不到日期或持股表")
    seg = page[i:]
    j = seg.find("口數")
    rows = _html_rows(seg[:j] if j > 0 else seg)
    return iso(m.group(1)), rows, _meta()


# ---------------- 永豐 ----------------
# 單檔頁仍留著全系列空表格模板：只掃第一個「證券代碼」到第二個之間。
@adapter("sinopac")
def sinopac(code, name=""):
    page = C.http(f"https://sitc.sinopac.com/SinopacEtfs/Etfs/SinglePcf/{code}", as_json=False)
    m = re.search(r"資料日期[：:\s]*(\d{4}/\d{1,2}/\d{1,2})", page)
    i = page.find("證券代碼")
    if not m or i < 0:
        raise AdapterError(f"sinopac {code}: 找不到日期或持股表")
    j = page.find("證券代碼", i + 4)
    rows = _html_rows(page[i:j if j > 0 else None])
    return iso(m.group(1)), rows, _meta()


# ---------------- 兆豐 ----------------
# ASP.NET WebForms：GET 取 hidden 欄位 → 整包原封帶回 POST（加 fund_id、button1）。
# 「查詢日期」是公告日（T+1），其後第一個日期才是持股基準日。
MEGA = "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx"
BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8", "Upgrade-Insecure-Requests": "1"}


@adapter("mega")
def mega(code, name=""):
    page = C.http(MEGA, as_json=False, headers=BROWSER)
    hidden = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page))
    opts = [(v, re.sub(r"\s+", "", html.unescape(t)))
            for v, t in re.findall(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>', page)]
    fid = _match_name(opts, name, code)
    if not fid:
        raise AdapterError(f"mega {code}: 選單找不到「{name}」")
    btn = re.search(r'<input[^>]*name="(button1)"[^>]*value="([^"]*)"', page)
    form = {**{k: html.unescape(v) for k, v in hidden.items()}, "fund_id": fid}
    if btn:
        form[btn.group(1)] = html.unescape(btn.group(2))
    page = html.unescape(C.http(MEGA, form=form, as_json=False, headers={**BROWSER, "Referer": MEGA, "Origin": "https://www.megafunds.com.tw"}))
    if code not in page:
        raise AdapterError(f"mega {code}: 回傳頁面不是這檔基金")
    q = page.find("查詢日期")
    dates = re.findall(r"(\d{4}/\d{1,2}/\d{1,2})", page[q:] if q >= 0 else page)
    if not dates:
        raise AdapterError(f"mega {code}: 找不到日期")
    data_date = dates[1] if q >= 0 and len(dates) > 1 else dates[0]
    i = page.find("股票代號", q if q >= 0 else 0)
    rows = _html_rows(page[i:] if i >= 0 else page)
    return iso(data_date), rows, _meta()


# ---------------- 第一金 ----------------
# WebMethod Get_hd {pStrFundID, pStrDate:""} 回最新一份（雙層 JSON），sdate 就是基準日。
# 沒有基金清單端點：掃 FundDetail.aspx?ID=n 的「股票代號」反查，結果快取在 SOURCE_IDS。
FSITC = "https://www.fsitc.com.tw/"
FSITC_IDS = {"00728": "D90"}  # 內部 ID 不一定是數字（掃描找不到的先寫死）


def _fsitc_find_id(code, budget_s=400):
    """掃 FundDetail.aspx?ID=n 找「股票代號</td><td…>代號」。已知 00408A = 183，其他 ETF 多在附近。"""
    import time
    t0 = time.time()
    near = sorted(range(1, 320), key=lambda i: abs(i - 183))
    for i in near:
        if time.time() - t0 > budget_s:
            break
        if str(i) in SOURCE_IDS.get("firstsec", {}).values():
            continue
        try:
            head = C.http(FSITC + "FundDetail.aspx", {"ID": i}, raw=True, max_bytes=200_000, retries=1)
        except AdapterError:
            continue
        m = re.search(r"股票代號</td>\s*<td[^>]*>\s*(00\d{3,4}[A-Z]?)\s*<", head.decode("utf-8", errors="ignore"))
        if m:
            SOURCE_IDS.setdefault("firstsec", {})[m.group(1)] = str(i)
            if m.group(1) == code:
                return str(i)
    return None


@adapter("firstsec")
def firstsec(code, name=""):
    fid = SOURCE_IDS.get("firstsec", {}).get(code) or FSITC_IDS.get(code) or _fsitc_find_id(code)
    if not fid:
        raise AdapterError(f"firstsec {code}: 找不到基金 ID")
    d = C.http(FSITC + "WebAPI.aspx/Get_hd", body={"pStrFundID": fid, "pStrDate": ""})
    rows_raw = d.get("d") if isinstance(d, dict) else d
    if isinstance(rows_raw, str):  # {"d": "<JSON 字串>"} 雙層編碼
        rows_raw = json.loads(rows_raw) if rows_raw.strip() else []
    rows_raw = rows_raw if isinstance(rows_raw, list) else []
    stocks = [x for x in rows_raw if str(x.get("group", "1")) == "1"]
    if not stocks or not stocks[0].get("sdate"):
        raise AdapterError(f"firstsec {code}: 沒有持股資料")
    rows = _rows(stocks, "A", "B", "D", "C")
    return iso(stocks[0]["sdate"]), rows, _meta()


# ---------------- 聯博 ----------------
# 以 ISIN 當基金識別（由代號算出）；先取 basket 的 asOfDate 再帶進 holdings，只取 equity 段。
AB = "https://webapi.alliancebernstein.com/v2/funds/tw/zh-tw/investor/"


@adapter("ab")
def ab(code, name=""):
    isin = C.isin_for(code)
    basket = C.http(AB + f"{isin}/basket")
    as_of = C.find_key(basket, "asOfDate")
    if not as_of:
        raise AdapterError(f"ab {code}: basket 沒有 asOfDate")
    h = C.http(AB + f"{isin}/holdings", {"date": str(as_of)[:10]})
    sections = C.find_key(h, "domesticHoldings") or []
    items = []
    for s in sections:
        cat = s.get("holdingCategory", "")
        if "equity" in cat:
            items += s.get("holdings") or s.get("items") or ([s] if s.get("holdingCode") else [])
    rows = _rows(items, "holdingCode", "holding", "holdingShares", "holdingPerc")
    return iso(as_of), rows, _meta(C.find_key(basket, "aum"), C.find_key(basket, "shares"), C.find_key(basket, "nav"))


# ---------------- 摩根 ----------------
# 只提供 Excel：holding_pcf 以 ISIN + 持股基準日查詢（locale、date 必填），逐日往回試。
JPM = "https://am.jpmorgan.com/FundsMarketingHandler/excel"
JPM_ISIN = {}  # 代號 → ISIN（算出來的對不上時才需要）


@adapter("jpmorgan")
def jpmorgan(code, name=""):
    isin = JPM_ISIN.get(code) or C.isin_for(code)
    for d in C.recent_days(15):
        try:
            content = C.http(JPM, {"type": "holding_pcf", "cusip": isin, "country": "tw", "role": "twetf",
                                   "locale": "zh-TW", "date": d.isoformat()}, raw=True, retries=1)
        except AdapterError:
            continue
        if content[:2] != b"PK":
            continue
        table = C.xlsx_rows(content, 1)
        title = next((" ".join(r) for r in table if "股票" in " ".join(r) and re.search(r"\d{4}-\d{2}-\d{2}", " ".join(r))), "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})", title)
        hdr = next((i for i, r in enumerate(table) if any("股票代碼" in c for c in r)), None)
        if hdr is None:
            continue
        cols = table[hdr]
        ci = {k: next((i for i, c in enumerate(cols) if k in c), None) for k in ("股票代碼", "股票名稱", "股數", "權重")}
        rows = []
        for r in table[hdr + 1:]:
            if len(r) <= max(v for v in ci.values() if v is not None):
                break
            raw_code = str(r[ci["股票代碼"]]).strip().upper()
            if re.match(r"^[A-Z][A-Z.\-]{0,6}$", raw_code):  # 美股基金只給裸代號（NVDA）→ 補市場別，與他家 'NVDA US' 一致
                raw_code += " US"
            h = holding(raw_code, r[ci["股票名稱"]], num(r[ci["股數"]]), num(r[ci["權重"]]))
            if not is_security(h["code"]):
                if h["code"] == "":
                    break
                continue
            rows.append(h)
        if rows:
            return (m.group(1) if m else d.isoformat()), rows, _meta()
    raise AdapterError(f"jpmorgan {code}: 最近 15 個工作天都沒有 Excel（ISIN {isin}）")


# ---------------- 富蘭克林華美 ----------------
# /official/api/etf：ETF 清單（StockCode ↔ FundID）；
# /official/api/etf/shares/{FundID}?date=YYYYMMDD（空白 = 最新）：Secs[] 實際持股、AssetDate（UTC，需轉台北日期）。
FTFT = "https://www.ftft.com.tw/official/api/"


def _utc_to_tpe_date(s):
    d = datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=8)
    return d.strftime("%Y-%m-%d")


@adapter("franklin")
def franklin(code, name=""):
    fid = _lookup_id("franklin", code, lambda: {
        str(x.get("StockCode")).strip(): str(x.get("FundID")) for x in (C.http(FTFT + "etf") or []) if x.get("StockCode")})
    d = C.http(FTFT + f"etf/shares/{fid}", {"date": ""})
    if not d or not d.get("AssetDate"):
        raise AdapterError(f"franklin {code}: 沒有持股資料")
    secs = [x for x in (d.get("Secs") or []) if x.get("SecuritiesType", "S") == "S"]
    rows = _rows(secs, "SecuritiesCode", "SecuritiesName", "Shares", "WeightingPercentage")
    return _utc_to_tpe_date(d["AssetDate"]), rows, _meta(d.get("FundNetAssetValue"), d.get("TotalUnitsOutstanding"),
                                                         d.get("NetAssetValuePerUnit"))


# ---------------- 大華銀 ----------------
# /api/WebSite/pcf?fundID=<數字代碼>&pcfDate=YYYY/MM/DD：result[] 中 kind=stock 為實際持股（qty 股數、weight 權重），
# datadate 為持股基準日。網站憑證鏈不完整（缺中繼憑證），用 insecure 連線讀公開資料。
UOB = "https://www.uobam.com.tw/api/WebSite/pcf"
UOB_IDS = {"00918": "88329556"}  # 官網 ETF 頁連結中的 fundID


@adapter("uob")
def uob(code, name=""):
    fid = SOURCE_IDS.get("uob", {}).get(code) or UOB_IDS.get(code)
    if not fid:
        raise AdapterError(f"uob {code}: 沒有基金代碼")
    for d in C.recent_days(8, datetime.now(C.TPE).date()):
        try:
            r = C.http(UOB, {"fundID": fid, "pcfDate": d.strftime("%Y/%m/%d")}, insecure=True, retries=2)
        except AdapterError:
            continue
        stocks = [x for x in (r.get("result") or []) if x.get("kind") == "stock"]
        if r.get("etf002") == code and stocks:
            rows = _rows(stocks, "code", "cName", "qty", "weight")
            return iso(r["datadate"]), rows, _meta(r.get("totalAV"), r.get("totalIssues"), r.get("nav"))
    raise AdapterError(f"uob {code}: 最近 8 個工作天都沒有資料")


# ---------------- 玉山 ----------------
# 與野村／安聯同一套系統，但 API 在 /ETFAPI/ 之下、FundNo 是內部編號（009803 = "50"），
# GetETFFundSelectList 取清單後用名稱對應。GetFundTradeInfo 的 Date 要是 PCF 公告日，CNavDt 才是持股基準日。
ESUN = "https://www.esunam.com/ETFAPI/"


def _esun_map():
    out = []
    for t in C.find_key(C.http(ESUN + "GetETFFundTypes", body={}), "Entries") or []:
        for f in C.find_key(C.http(ESUN + "GetETFFundSelectList", body={"TypeID": t.get("Id")}), "Entries") or []:
            if f.get("FundNo"):
                out.append((str(f["FundNo"]), re.sub(r"\s+", "", f.get("FundShortName") or "")))
    return out


@adapter("esun")
def esun(code, name=""):
    fno = SOURCE_IDS.get("esun", {}).get(code) or _match_name(_esun_map(), name, code)
    if not fno:
        raise AdapterError(f"esun {code}: 基金清單找不到「{name}」")
    SOURCE_IDS.setdefault("esun", {})[code] = fno
    for d in C.recent_days(10, datetime.now(C.TPE).date() + timedelta(days=1)):
        r = C.http(ESUN + "GetFundTradeInfo", body={"Type": 1, "Keyword": "", "FundNo": fno, "Date": d.isoformat()})
        e = C.find_key(r, "Entries")
        if not isinstance(e, dict):
            continue
        stock = next((t for t in (e.get("DynamicTableData") or []) if str(t.get("TableTitle", "")).startswith("股票")), None)
        if not stock or not stock.get("Rows"):
            continue
        rows = []
        for row in stock["Rows"]:
            if len(row) >= 4:
                h = holding(row[0], row[1], num(row[2]), num(row[3]))
                if is_security(h["code"]):
                    rows.append(h)
        return iso(e.get("CNavDt")), rows, _meta(e.get("CAnceTotalAv"), e.get("CAnceTotalIssues"), e.get("CAnceNav"))
    raise AdapterError(f"esun {code}: 最近 10 個工作天都沒有資料")


# ---------------- 聯邦 ----------------
# /CustCenter/BuyBackList：server-rendered，預設顯示聯邦台灣精彩50（009804）；
# 「基金資產 資料日期」為持股基準日，「股票投資比例」表為實際持股（股票代號／名稱／股數／權重）。
UNION = "https://www.usitc.com.tw/CustCenter/BuyBackList"


@adapter("union")
def union(code, name=""):
    page = html.unescape(C.http(UNION, as_json=False))
    if f"( {code} )" not in page and f"({code})" not in page:
        raise AdapterError(f"union {code}: 頁面預設基金不是 {code}")
    m = re.search(r"基金資產\s*(?:<[^>]+>\s*)*資料日期[：:]\s*(\d{4}-\d{1,2}-\d{1,2})", page) or \
        re.search(r"資料日期[：:]\s*(?:<[^>]+>\s*)*(\d{4}-\d{1,2}-\d{1,2})", page)
    i = page.find("股票投資比例")
    if not m or i < 0:
        raise AdapterError(f"union {code}: 找不到資料日期或持股表")
    return iso(m.group(1)), _html_rows(page[i:]), _meta()


# ---------------- 華南永昌 ----------------
# 新網域 hnfunds.com.tw，API 基底 /WEB_API/HN_OW_PROD。需先 POST /Auth/SysLogin（Client_Id: WFPAPIPublicClient）
# 取得匿名 system token，其後以 Bearer 呼叫。持股 GET /ETF/FundDtl/AssetSet/{ETF 代號}。
HN = "https://www.hnfunds.com.tw/WEB_API/HN_OW_PROD"
_hn = {}


def _hn_call(path, body=None, method_get=False):
    if "token" not in _hn:
        t = C.http(HN + "/Auth/SysLogin", body={}, headers={
            "Client_Id": "WFPAPIPublicClient", "Accept-Language": "zh-TW",
            "X-Origin-Time": datetime.now(C.TPE).strftime("%Y-%m-%dT%H:%M:%S+08:00")})
        _hn["token"] = C.find_key(t, "access_token")
        if not _hn["token"]:
            raise AdapterError("hnitc: 取得 token 失敗")
    h = {"Authorization": f"Bearer {_hn['token']}", "Client_Id": "WFPAPIPublicClient", "Accept-Language": "zh-TW",
         "X-Origin-Time": datetime.now(C.TPE).strftime("%Y-%m-%dT%H:%M:%S+08:00")}
    return C.http(HN + path, body=None if method_get else (body or {}), headers=h)


@adapter("hnitc")
def hnitc(code, name=""):
    """AssetSet 直接吃 ETF 代號：Data.StockList[{StockNo, StockName, Share, Weight(小數)}]；
    AssetSet 沒有日期，基準日取 FundDtl/{代號} 的 NavDate。"""
    d = C.find_key(_hn_call(f"/ETF/FundDtl/AssetSet/{code}", method_get=True), "Data") or {}
    stocks = d.get("StockList") or []
    info = C.find_key(_hn_call(f"/ETF/FundDtl/{code}", method_get=True), "Data") or {}
    date = info.get("NavDate") or d.get("NavDate")
    if not stocks or not date:
        raise AdapterError(f"hnitc {code}: 沒有持股或日期")
    for x in stocks:
        w = num(x.get("Weight"))
        x["_w"] = None if w is None else round(w * 100, 4)
    rows = _rows(stocks, "StockNo", "StockName", "Share", "_w")
    units, nav = num(d.get("OsUnit")), num(d.get("Punit"))
    return iso(str(date)[:10]), rows, _meta(d.get("FundSize"), units, nav)
