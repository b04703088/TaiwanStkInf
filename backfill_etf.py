#!/usr/bin/env python3
"""回補主動式 ETF 的歷史每日持股（給持股成本頁用：起始部位越早、成本估計越準）。

只處理官網 API 能「指定日期」查詢的投信；只給最新一份的（富邦、凱基、台新、永豐、元大）無法回補。
從每檔現有最早一份往回逐個工作日查，查到的存成 data/etf/<代號>/<基準日>.csv（與 fetch_etf.py 同格式）；
連續 STOP_EMPTY 個工作日都查不到就當作已到上市日（或 API 不再提供）停止。已存在的日期不重抓，可分次續跑。

用法:
    python backfill_etf.py                 # 全部可回補的主動式 ETF
    python backfill_etf.py 00981A 00980A   # 指定 ETF
    python backfill_etf.py --probe         # 每檔只試幾天，看各家 API 能不能查歷史
    python backfill_etf.py --since 2025-05-01 --budget 300   # 最早日期、每檔最多查幾天
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import etf_adapters as A
import etf_common as C
from etf_common import AdapterError, holding, is_security, iso
from fetch_etf import ETF_DIR, ETF_LIST, load_source_ids, save_source_ids, write_day

STOP_EMPTY = 12


def _roc(d):
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


# 每個函式 (code, name, d) → (持股基準日 'YYYY-MM-DD', rows) 或 None（這天查不到）
def cathay(code, name, d):
    rows = A.cathay_holdings(A._cathay_fund(code), d.isoformat())
    return (d.isoformat(), rows) if rows else None


def president(code, name, d):
    if A._ez_map is None:
        A.president(code, name)
    fc = A._ez_map.get(code)
    r = C.http(A.EZ + "GetPCF", body={"fundCode": fc, "date": _roc(d), "specificDate": True},
               headers={"Referer": A.EZ + "PCF", "X-Requested-With": "XMLHttpRequest"})
    assets = C.find_key(r, "asset") or []
    stocks = next((a.get("Details") for a in assets if a.get("AssetCode") == "ST"), None) or []
    pcf = C.find_key(r, "pcf") or [{}]
    pcf = pcf[0] if isinstance(pcf, list) and pcf else (pcf if isinstance(pcf, dict) else {})
    if not pcf.get("TranDate") or not stocks:
        return None
    return iso(pcf["TranDate"]), A._rows(stocks, "DetailCode", "DetailName", "Share", "NavRate")


def ctbc(code, name, d):
    if "token" not in A._ctbc:
        A.ctbc(code, name)
    fid = A._ctbc["map"].get(code)
    r = C.http(A.CTBC + "etf/ETFHoldingWeight", {"token": A._ctbc["token"]},
               body={"FID": fid, "StartDate": d.strftime("%Y/%m/%d")})
    data = r.get("Data") if isinstance(r, dict) else None
    if not data or str(r.get("ResultCode")) == "1":
        return None
    fa = (data.get("FundAssets") or [{}])[0]
    stock = next((x.get("Data") for x in (data.get("FundAssetsDetail") or []) if x.get("Code") == "STOCK"), None)
    if not fa.get("資料日期") or not stock:
        return None
    return iso(fa["資料日期"]), A._rows(stock, "code_", "name_", "qty_", "weights_")


def nomura(code, name, d):
    r = C.http(A.NOMURA, body={"Type": 1, "Keyword": "", "FundNo": code, "Date": d.isoformat()})
    e = C.find_key(r, "Entries")
    e = (e[0] if e else None) if isinstance(e, list) else e
    if not e or not e.get("Stocks"):
        return None
    return iso(e.get("CNavDtStr") or e.get("CNavDt")), A._rows(e["Stocks"], "CStockCode", "CStockName", "CQuantity", "CWeightsPct")


def allianz(code, name, d):
    if "token" not in A._allianz:
        A.allianz(code, name)
    fno = A._allianz["map"].get(code)
    r = A._allianz_post("Fund/GetFundTradeInfo", {"Type": 1, "Keyword": "", "FundNo": fno, "Date": d.isoformat()})
    tables = C.find_key(r, "DynamicTableData") or []
    stock = next((t for t in tables if str(t.get("TableTitle", "")).startswith("股票")), None)
    e = C.find_key(r, "Entries") or {}
    e = e if isinstance(e, dict) else {}
    base = e.get("CNavDtStr") or e.get("CNavDt")
    if not stock or not stock.get("Rows") or not base:
        return None
    rows = [h for h in (holding(x[1], x[2], C.num(x[3]), C.num(x[4])) for x in stock["Rows"] if len(x) >= 5)
            if is_security(h["code"])]
    return iso(base), rows


def fuhhwa(code, name, d):
    if A._fh_map is None:
        A.fuhhwa(code, name)
    fid = A._fh_map.get(code)
    res = ((C.http(A.FH + "assets", {"fundID": fid, "qDate": d.strftime("%Y/%m/%d")}) or {}).get("result") or [{}])[0]
    detail = [x for x in (res.get("detail") or []) if x.get("ftype") == "股票"]
    if not res.get("dDate") or not detail:
        return None
    return iso(res["dDate"]), A._rows(detail, "stockid", "stockname", "qshare", "prate_addaccint")


def ab(code, name, d):
    h = C.http(A.AB + f"{C.isin_for(code)}/holdings", {"date": d.isoformat()})
    items = []
    for s in C.find_key(h, "domesticHoldings") or []:
        if "equity" in s.get("holdingCategory", ""):
            items += s.get("holdings") or s.get("items") or ([s] if s.get("holdingCode") else [])
    rows = A._rows(items, "holdingCode", "holding", "holdingShares", "holdingPerc")
    return (d.isoformat(), rows) if rows else None


def jpmorgan(code, name, d):
    try:
        base, rows, _ = A.jpmorgan(code, name, days=[d])  # 沿用 adapter 的 Excel 解析，只試這一天
    except AdapterError:
        return None
    return base, rows


def capital(code, name, d):
    if A._capital_map is None:
        A.capital(code, name)
    fid = A._capital_map.get(code)
    r = (C.http(A.CAPITAL + "buyback", body={"fundId": fid, "date": d.strftime("%Y/%m/%d")}) or {}).get("data") or {}
    pcf = r.get("pcf") or {}
    if not pcf.get("date2"):
        return None
    return iso(pcf["date2"]), A._rows(r.get("stocks"), "stocNo", "stocName", "share", "weight")


def firstsec(code, name, d):
    fid = A.SOURCE_IDS.get("firstsec", {}).get(code) or A.FSITC_IDS.get(code)
    if not fid:
        return None
    r = C.http(A.FSITC + "WebAPI.aspx/Get_hd", body={"pStrFundID": fid, "pStrDate": d.strftime("%Y/%m/%d")})
    raw = r.get("d") if isinstance(r, dict) else r
    if isinstance(raw, str):
        import json
        raw = json.loads(raw) if raw.strip() else []
    stocks = [x for x in (raw if isinstance(raw, list) else []) if str(x.get("group", "1")) == "1"]
    if not stocks or not stocks[0].get("sdate"):
        return None
    return iso(stocks[0]["sdate"]), A._rows(stocks, "A", "B", "D", "C")


BY_ISSUER = {"cathay": cathay, "president": president, "ctbc": ctbc, "nomura": nomura, "allianz": allianz,
             "fuhhwa": fuhhwa, "ab": ab, "jpmorgan": jpmorgan, "capital": capital, "firstsec": firstsec}


def holidays():
    p = ETF_DIR.parent / "no_trading_days.txt"
    return set(p.read_text().split()) if p.exists() else set()


def existing(code):
    return {f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]}" for f in (ETF_DIR / code).glob("[0-9]*.csv")}


def backfill(code, name, issuer, since, budget, probe, hol):
    fn = BY_ISSUER[issuer]
    have = existing(code)
    if not have:
        return f"{code}: 沒有現有資料，先跑 fetch_etf.py"
    d = date.fromisoformat(min(have))
    found, empty, tried, seen_base, errors = 0, 0, 0, set(), 0
    latest_only = None
    while tried < budget and empty < STOP_EMPTY:
        d -= timedelta(days=1)
        if d < since:
            break
        if d.weekday() >= 5 or d.isoformat() in hol:
            continue
        tried += 1
        try:
            got = fn(code, name, d)
        except AdapterError as e:
            errors += 1
            got = None
            if errors <= 2:
                print(f"  {code} {d}: {str(e)[:160]}", flush=True)
            if errors >= 8 and found == 0:
                return f"{code}: 連續錯誤，放棄（{str(e)[:120]}）"
        if not got or not got[1]:
            empty += 1
            continue
        base, rows = got
        if base > min(have) and not seen_base:  # API 忽略日期、回最新一份
            latest_only = base
            empty += 1
            continue
        empty = 0
        if base in seen_base or base in have:
            continue
        seen_base.add(base)
        if probe:
            print(f"  {code} 查 {d} → 基準日 {base}，{len(rows)} 檔", flush=True)
        else:
            write_day(code, base, rows)
        found += 1
        if probe and found >= 3:
            break
        time.sleep(0.2)
    note = f"（API 只回最新 {latest_only}）" if latest_only and not found else ""
    return f"{code} {issuer}: 新增 {found} 天，試了 {tried} 天，最早 {min(seen_base) if seen_base else '-'}{note}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("etfs", nargs="*")
    ap.add_argument("--since", default="2025-05-01")
    ap.add_argument("--budget", type=int, default=400, help="每檔最多查幾個工作日")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    load_source_ids()
    hol, since = holidays(), date.fromisoformat(a.since)
    todo = [(c, n, i) for c, n, i, k in ETF_LIST if k == "active" and (not a.etfs or c in a.etfs)]
    skip = [c for c, _, i in todo if i not in BY_ISSUER]
    if skip:
        print("官網只給最新一份、無法回補：", " ".join(skip))
    todo = [t for t in todo if t[2] in BY_ISSUER]
    # 同一家投信排在同一條執行緒，避免共用 token／快取時打架、也不要同時打爆一家
    groups = {}
    for t in todo:
        groups.setdefault(t[2], []).append(t)

    def run(items):
        out = []
        for c, n, i in items:
            try:
                out.append(backfill(c, n, i, since, 3 if a.probe else a.budget, a.probe, hol))
            except Exception as e:  # noqa: BLE001 一檔失敗不影響其他
                out.append(f"{c} {i}: 失敗 {e!r}"[:200])
            print(out[-1], flush=True)
        return out

    t0 = datetime.now()
    with ThreadPoolExecutor(a.workers) as ex:
        results = [r for rs in ex.map(run, groups.values()) for r in rs]
    save_source_ids()
    print(f"\n完成（{(datetime.now() - t0).seconds} 秒）")
    print("\n".join(results))


if __name__ == "__main__":
    sys.exit(main())
