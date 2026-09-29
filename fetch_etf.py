#!/usr/bin/env python3
"""抓取台股 ETF 每日持股明細（成分股、股數、權重），存成 CSV。

用法:
    python fetch_etf.py                 # 抓 ETF_LIST 全部
    python fetch_etf.py 0050 00878      # 只抓指定 ETF

輸出:
    data/etf/<ETF代號>/<YYYYMMDD>.csv   欄位見 COLUMNS；檔名日期是「持股基準日」（投信公告的資料日）
    data/etf/summary.csv                每檔每日一列：基金規模、流通單位數、淨值、持股檔數

各投信格式不同，每家一個 adapter，都回傳 (資料日, 持股清單, 基本面)。
重複執行只會覆寫同一天的檔案；遇到假日投信仍回前一個交易日的資料，不會產生重複日期。
"""
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
ETF_DIR = ROOT / "data" / "etf"
COLUMNS = ["date", "etf", "code", "name", "shares", "weight"]
SUMMARY_COLUMNS = ["date", "etf", "aum", "units", "nav", "holdings", "fetched_at"]

# 第一階段：熱門市值型 + 高股息。之後加 ETF 只要在這裡加一行（同一家投信不用改程式）。
ETF_LIST = [
    # (代號, 名稱, 投信)
    ("0050", "元大台灣50", "yuanta"),
    ("0056", "元大高股息", "yuanta"),
    ("00713", "元大台灣高息低波", "yuanta"),
    ("00940", "元大台灣價值高息", "yuanta"),
    ("006208", "富邦台50", "fubon"),
    ("00878", "國泰永續高股息", "cathay"),
    ("00919", "群益台灣精選高息", "capital"),
    ("00929", "復華台灣科技優息", "fuhhwa"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class AdapterError(Exception):
    pass


# ---------------- HTTP ----------------
def http(url, params=None, body=None, as_json=True, retries=3, headers=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if data is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            return json.loads(text) if as_json else text
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise AdapterError(f"{url[:120]}: {e!r}") from e
            time.sleep(5 * (attempt + 1))


def num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def iso(s):
    """'20260924' / '2026/09/24' / '2026-09-24' / '1150924' → '2026-09-24'"""
    s = str(s).strip().replace("/", "").replace("-", "")[:8]
    if len(s) == 7:  # 民國
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def holding(code, name, shares, weight):
    return {"code": str(code).strip(), "name": str(name).strip(),
            "shares": None if shares is None else int(round(shares)),
            "weight": None if weight is None else round(float(weight), 4)}


# ---------------- 元大 ----------------
# 前端經 etfapi.yuantaetfs.com 的 bridge 呼叫 PCF/Daily；參數取自官網 __NUXT__.globalSetting。
# FundWeights.StockWeights 有官方的「總持股股數」與權重，優先使用。
# 沒有時才用 InKind.FundComposition（每申購基數股數）× 流通單位數 / 基數單位數 還原。
YUANTA_BRIDGE = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"
_yuanta_device = str(uuid.uuid4())


def yuanta(code):
    d = http(YUANTA_BRIDGE, {
        "APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS",
        "PageName": f"/product/detail/{code}/ratio", "DeviceId": _yuanta_device,
        "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3", "Platform": "ETF", "ticker": code,
    }, headers={"Referer": f"https://www.yuantaetfs.com/product/detail/{code}/ratio"})
    if isinstance(d, dict) and "Data" in d and "PCF" not in d:
        d = d["Data"]
    d = d or {}
    pcf = d.get("PCF") or {}
    if not pcf.get("trandate"):
        raise AdapterError(f"yuanta {code}: 回應沒有 PCF（keys={list(d.keys())[:8]}）")
    stock_w = ((d.get("FundWeights") or {}).get("StockWeights")) or []
    rows = [holding(x["code"], x.get("name", ""), num(x.get("qty")), num(x.get("weights")))
            for x in stock_w if re.match(r"^\d{4}", str(x.get("code", "")))]
    if not rows:
        comp = (d.get("InKind") or {}).get("FundComposition") or []
        units, base = num(pcf.get("osunit")), num(pcf.get("baseunit"))
        mult = units / base if units and base else None
        rows = [holding(x["stkcd"], x.get("name", ""),
                        num(x.get("qty")) * mult if mult and num(x.get("qty")) is not None else None, None)
                for x in comp if re.match(r"^\d{4}", str(x.get("stkcd", "")))]
    if not rows:
        raise AdapterError(f"yuanta {code}: 沒有持股資料")
    meta = {"aum": num(pcf.get("totalav")), "units": num(pcf.get("osunit")), "nav": num(pcf.get("nav"))}
    return iso(pcf["trandate"]), rows, meta


# ---------------- 富邦 ----------------
FUBON_ASSETS = "https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx"
FUBON_ROW = re.compile(
    r'<tr>\s*<td class="tac">([0-9A-Z]{4,6})</td>\s*<td>([^<]+)</td>'
    r'\s*<td class="tar">([\d,]+)</td>\s*<td class="tar">[\d,.-]+</td>\s*<td class="tar">([\d.]+)</td>')


def _fubon_meta(page, label):
    m = re.search(r"<p>\s*" + re.escape(label) + r"[^<]*</p>\s*<p>\s*([\d,.]+)\s*</p>", page)
    return num(m.group(1)) if m else None


def fubon(code):
    page = http(FUBON_ASSETS, {"stkId": code, "lan": "TW"}, as_json=False)
    m = re.search(r"資料日期：\s*(\d{4}/\d{2}/\d{2})", page)
    rows = [holding(c, n, num(s), num(w)) for c, n, s, w in FUBON_ROW.findall(page)
            if c[0].isdigit()]  # 期貨列代號是英文開頭（如 WTXV6F），排除
    if not m or not rows:
        raise AdapterError(f"fubon {code}: 找不到資料日期或持股表")
    meta = {"aum": _fubon_meta(page, "基金淨資產"), "units": _fubon_meta(page, "基金在外流通單位數"),
            "nav": _fubon_meta(page, "基金每單位淨值")}
    return iso(m.group(1)), rows, meta


# ---------------- 國泰 ----------------
# 內部 FundCode 是兩碼代號（00878 = CN），參數名大小寫要對，SearchDate 必填。
# 同元大：公告的是每基數股數，總股數 = basketShares × totUnit / basketUnit。
CATHAY = "https://cwapi.cathaysite.com.tw/api/"
_cathay_map = None


def _cathay(path, params):
    d = http(CATHAY + path, params)
    if not d.get("success"):
        raise AdapterError(f"cathay {path}: {d.get('returnMessage')}")
    return d.get("result")


def cathay(code):
    global _cathay_map
    if _cathay_map is None:
        res = _cathay("ETF/GetETFList", {"FundType": "", "PerPageCount": 9999, "status": 1})
        rows = res if isinstance(res, list) else (res or {}).get("list") or []
        _cathay_map = {r.get("stockCode"): r.get("fundCode") for r in rows if r.get("stockCode")}
    fc = _cathay_map.get(code)
    if not fc:
        raise AdapterError(f"cathay {code}: ETF 清單找不到這檔")
    bs = _cathay("BuySale/GetBuySale", {"FundCode": fc, "IsTest": "false", "status": 1})
    stocks = _cathay("BuySale/GetStocksList", {"FundCode": fc, "SearchDate": bs["date"],
                                               "IsTest": "false", "status": 1}) or []
    try:
        w = _cathay("ETF/GetIndexStockWeights", {"fundCode": fc, "status": 1}) or {}
        wmap = {r["stockCode"]: num(r.get("weights")) for r in (w.get("stockWeights") or [])}
    except AdapterError:
        wmap = {}
    tot, basket = num(bs.get("totUnit")), num(bs.get("basketUnit"))
    mult = tot / basket if tot and basket else None
    rows = [holding(r["prod"], r.get("prodName", ""),
                    num(r.get("basketShares")) * mult if mult else None, wmap.get(str(r["prod"]).strip()))
            for r in stocks if re.match(r"^\d{4}", str(r.get("prod", "")))]
    if not rows:
        raise AdapterError(f"cathay {code}: 成分股為空")
    meta = {"aum": num(bs.get("aum")), "units": tot, "nav": num(bs.get("nav"))}
    return iso(bs.get("preDateC") or bs["date"]), rows, meta


# ---------------- 群益 ----------------
CAPITAL = "https://www.capitalfund.com.tw/CFWeb/api/etf/"
_capital_map = None


def capital(code):
    global _capital_map
    if _capital_map is None:
        items = http(CAPITAL + "items", body={})
        _capital_map = {f.get("stockNo"): f.get("fundNo") for f in items.get("data", []) if f.get("stockNo")}
    fid = _capital_map.get(code)
    if not fid:
        raise AdapterError(f"capital {code}: ETF 清單找不到這檔")
    d = (http(CAPITAL + "buyback", body={"fundId": fid}) or {}).get("data") or {}
    pcf, stocks = d.get("pcf") or {}, d.get("stocks") or []
    if not pcf.get("date2") or not stocks:
        raise AdapterError(f"capital {code}: 沒有 PCF 或成分股")
    rows = [holding(x["stocNo"], x.get("stocName", ""), num(x.get("share")), num(x.get("weight")))
            for x in stocks if re.match(r"^\d{4}", str(x.get("stocNo", "")))]
    meta = {"aum": num(pcf.get("nav")), "units": num(pcf.get("totUnit")), "nav": num(pcf.get("pUnit"))}
    return iso(pcf["date2"]), rows, meta


# ---------------- 復華 ----------------
FH = "https://www.fhtrust.com.tw/api/"
_fh_map = None


def fuhhwa(code):
    global _fh_map
    if _fh_map is None:
        fl = http(FH + "fundList?ec001=3")
        _fh_map = {f.get("etf002"): f.get("fundID") for f in fl.get("result", []) if f.get("etf002")}
    fid = _fh_map.get(code)
    if not fid:
        raise AdapterError(f"fuhhwa {code}: ETF 清單找不到這檔")
    today = datetime.now(TPE).date()
    for back in range(0, 12):  # 假日/尚未公布回空資料 → 往前找
        q = (today - timedelta(days=back)).strftime("%Y/%m/%d")
        res = ((http(FH + "assets", {"fundID": fid, "qDate": q}) or {}).get("result") or [{}])[0]
        detail = [x for x in (res.get("detail") or []) if x.get("ftype") == "股票" and x.get("stockid")]
        if res.get("dDate") and detail:
            rows = [holding(x["stockid"], x.get("stockname", ""), num(x.get("qshare")),
                            num(x.get("prate_addaccint"))) for x in detail]
            meta = {"aum": num(res.get("pcf_FundNav")), "units": num(res.get("pcf_FundQissue")),
                    "nav": num(res.get("pcf_Fundpnav"))}
            return iso(res["dDate"]), rows, meta
    raise AdapterError(f"fuhhwa {code}: 最近 12 天都沒有資料")


ADAPTERS = {"yuanta": yuanta, "fubon": fubon, "cathay": cathay, "capital": capital, "fuhhwa": fuhhwa}


# ---------------- 輸出 ----------------
def validate(code, rows):
    if len(rows) < 5:
        raise AdapterError(f"{code}: 只有 {len(rows)} 檔成分股，資料可能不完整")
    codes = [r["code"] for r in rows]
    if len(set(codes)) != len(codes):
        raise AdapterError(f"{code}: 成分股代號重複")
    tw = sum(r["weight"] for r in rows if r["weight"] is not None)
    if tw > 105:
        raise AdapterError(f"{code}: 權重加總 {tw:.1f}% 不合理")


def fill_weights(rows, market):
    """投信沒給權重時，用股數 × 當日收盤價換算股票部位內的權重（%）。"""
    if all(r["weight"] is not None for r in rows):
        return False
    mv = {r["code"]: r["shares"] * market[r["code"]][0] for r in rows
          if r["shares"] is not None and r["code"] in market}
    total = sum(mv.values())
    if not total:
        return False
    for r in rows:
        if r["weight"] is None and r["code"] in mv:
            r["weight"] = round(mv[r["code"]] / total * 100, 4)
    return True


def load_market(d):
    """當日收盤行情：{代號: (收盤價, 交易所簡稱)}；用來換算缺少的權重、統一股票名稱。"""
    f = ROOT / "data" / d[:4] / f"{d.replace('-', '')}.csv"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8") as fp:
        return {r["code"]: (float(r["close"]), r["name"]) for r in csv.DictReader(fp) if r.get("close")}


def normalize_names(rows, market):
    """各投信對同一檔股票的寫法不同（華碩 / 華碩電腦），統一用交易所簡稱。"""
    for r in rows:
        if r["code"] in market:
            r["name"] = market[r["code"]][1]


def write_day(etf, d, rows):
    out = ETF_DIR / etf / f"{d.replace('-', '')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (-(r["weight"] or 0), r["code"]))
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({"date": d, "etf": etf, **r})
    return out


def update_summary(entries):
    path = ETF_DIR / "summary.csv"
    existing = {}
    if path.exists():
        with path.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                existing[(r["date"], r["etf"])] = r
    for e in entries:
        existing[(e["date"], e["etf"])] = e
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=SUMMARY_COLUMNS)
        w.writeheader()
        for k in sorted(existing):
            w.writerow({c: existing[k].get(c, "") for c in SUMMARY_COLUMNS})


def main(argv):
    wanted = set(argv)
    targets = [t for t in ETF_LIST if not wanted or t[0] in wanted]
    if wanted - {t[0] for t in ETF_LIST}:
        print(f"未知的 ETF：{sorted(wanted - {t[0] for t in ETF_LIST})}（請先加到 ETF_LIST）", file=sys.stderr)
    now = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    summary, failed = [], []
    for code, name, issuer in targets:
        try:
            d, rows, meta = ADAPTERS[issuer](code)
            market = load_market(d)
            normalize_names(rows, market)
            derived = fill_weights(rows, market)
            validate(code, rows)
            out = write_day(code, d, rows)
            summary.append({"date": d, "etf": code, "aum": meta.get("aum") or "", "units": meta.get("units") or "",
                            "nav": meta.get("nav") or "", "holdings": len(rows), "fetched_at": now})
            print(f"{code} {name}: {d} {len(rows)} 檔{'（權重由股數×收盤價換算）' if derived else ''} -> {out.relative_to(ROOT)}")
        except Exception as e:  # noqa: BLE001  一檔失敗不影響其他
            print(f"{code} {name}: 失敗 {e}", file=sys.stderr)
            failed.append(code)
    if summary:
        update_summary(summary)
    print(f"完成：成功 {len(summary)}、失敗 {len(failed)}{'：' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
