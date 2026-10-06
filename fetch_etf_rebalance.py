#!/usr/bin/env python3
"""ETF 指數調整（換股）時長：用歷史持股找出每次換股從開始到完成花了幾個交易日。

做法
  1. 粗掃：過去 --days 天，每 --step 個工作天查一次持股（投信網站可帶日期查歷史）。
  2. 成分股名單有變動的區間，前後各多抓幾天、逐日補齊。
  3. 每次換股（事件）：
       刪除股：權重跌到調整前的 80% 以下＝開始賣；持股歸零＝賣完
       新增股：第一次出現＝開始買；權重到調整後的 90%＝買完
     事件開始＝最早的開始，事件結束＝最晚的完成；時長＝開始到結束的交易日數（含頭尾）。
     用權重判斷，申購／贖回造成的股數變動不會被當成換股。
  4. 有指數生效日（臺灣指數公司、MSCI）時，另外算開始／結束相對生效日差幾個交易日。

可查歷史持股的投信：元大、國泰、群益、復華、中信、統一、野村、大華、第一金、安聯、玉山。
富邦、凱基等只能查最新，無法回推。

輸出 data/etf/rebalance/
  holdings/<ETF>.csv   抓到的歷史持股（date, code, name, shares, weight）
  asked.json           已查過的日期（避免重抓）
  events.csv           每次換股事件
用法：python fetch_etf_rebalance.py [--etfs 0056 00878] [--days 400] [--step 5] [--max-minutes 40]
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_adapters as A
import etf_common as C

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "etf" / "rebalance"
HIST_ISSUERS = {"yuanta", "cathay", "capital", "fuhhwa", "ctbc", "president", "nomura", "uob", "firstsec", "allianz", "esun"}
HOLD_DATE = {"cathay", "fuhhwa", "ctbc"}  # 這幾家帶的是「持股基準日」；其他家帶的是「公告日」（＝基準日的下一個工作天）
EV_COLS = ["etf", "name", "issuer", "index", "pre_date", "post_date", "start", "end", "days", "effective",
           "start_off", "end_off", "n_add", "n_del", "adds", "dels", "resolution"]
_lock = threading.Lock()
_patch_lock = threading.Lock()


def _next_weekday(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ---------------- 查某一天的持股 ----------------
def holdings_on(issuer, code, name, d):
    """查持股基準日約為 d 的持股 → (實際基準日 'YYYY-MM-DD', rows) 或 None（那天沒資料）。"""
    ask = d if issuer in HOLD_DATE else _next_weekday(d)
    try:
        if issuer == "yuanta":
            import uuid
            r = C.http(A.YUANTA_BRIDGE, {
                "APIType": "ETFAPI", "CompanyName": "YUANTAFUNDS", "PageName": f"/product/detail/{code}/ratio",
                "DeviceId": str(uuid.uuid4()), "FuncId": "PCF/Daily", "AppName": "ETF", "Device": "3",
                "Platform": "ETF", "ticker": code, "date": ask.strftime("%Y%m%d")},
                headers={"Referer": f"https://www.yuantaetfs.com/product/detail/{code}/ratio"})
            if isinstance(r, dict) and "Data" in r and "PCF" not in r:
                r = r["Data"]
            pcf = (r or {}).get("PCF") or {}
            rows = A._rows(((r or {}).get("FundWeights") or {}).get("StockWeights"), "code", "name", "qty", "weights")
            return (C.iso(pcf["trandate"]), rows) if pcf.get("trandate") and rows else None
        if issuer == "cathay":
            rows = A.cathay_holdings(A._cathay_fund(code), d.isoformat())
            return (d.isoformat(), rows) if rows else None
        if issuer == "capital":
            if A._capital_map is None:
                A.capital(code, name)
            fid = A._capital_map.get(code)
            r = (C.http(A.CAPITAL + "buyback", body={"fundId": fid, "date": ask.strftime("%Y/%m/%d")}) or {}).get("data") or {}
            pcf = r.get("pcf") or {}
            rows = A._rows(r.get("stocks"), "stocNo", "stocName", "share", "weight")
            return (C.iso(pcf["date2"]), rows) if pcf.get("date2") and rows else None
        if issuer == "president":
            if A._ez_map is None:
                A.president(code, name)
            fc = A._ez_map.get(code)
            r = C.http(A.EZ + "GetPCF", body={"fundCode": fc, "date": f"{ask.year - 1911}/{ask.month:02d}/{ask.day:02d}",
                                                "specificDate": True},
                       headers={"Referer": A.EZ + "PCF", "X-Requested-With": "XMLHttpRequest"})
            assets = C.find_key(r, "asset") or []
            stocks = next((a.get("Details") for a in assets if a.get("AssetCode") == "ST"), None) or []
            pcf = C.find_key(r, "pcf") or [{}]
            pcf = pcf[0] if isinstance(pcf, list) and pcf else (pcf if isinstance(pcf, dict) else {})
            rows = A._rows(stocks, "DetailCode", "DetailName", "Share", "NavRate")
            return (C.iso(pcf["TranDate"]), rows) if pcf.get("TranDate") and rows else None
        if issuer == "firstsec":
            fid = A.SOURCE_IDS.get("firstsec", {}).get(code) or A.FSITC_IDS.get(code)
            r = C.http(A.FSITC + "WebAPI.aspx/Get_hd", body={"pStrFundID": fid, "pStrDate": ask.strftime("%Y/%m/%d")})
            raw = r.get("d") if isinstance(r, dict) else r
            raw = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw if isinstance(raw, list) else [])
            stocks = [x for x in raw if str(x.get("group", "1")) == "1"]
            rows = A._rows(stocks, "A", "B", "D", "C")
            return (C.iso(stocks[0]["sdate"]), rows) if stocks and stocks[0].get("sdate") and rows else None
        # 其餘：原本就逐日往回試的 adapter，把「往回試的日期」換成指定那天
        with _patch_lock:
            real = C.recent_days
            C.recent_days = lambda n=10, start=None: [ask]
            try:
                got, rows, _ = A.ADAPTERS[issuer](code, name)
            finally:
                C.recent_days = real
        return (got, rows) if rows else None
    except (C.AdapterError, KeyError, ValueError, TypeError):
        return None


# ---------------- 儲存 ----------------
def load_hist(code):
    p = OUT / "holdings" / f"{code}.csv"
    out = defaultdict(dict)
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                out[r["date"]][r["code"]] = (r["name"], C.num(r["shares"]), C.num(r["weight"]))
    # 每日排程抓到的持股也算進來
    for f in (DATA / "etf" / code).glob("[0-9]*.csv"):
        d = f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}"
        if d in out:
            continue
        with f.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                out[d][r["code"]] = (r["name"], C.num(r["shares"]), C.num(r["weight"]))
    return out


def save_hist(code, hist):
    p = OUT / "holdings" / f"{code}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    daily = {f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}" for f in (DATA / "etf" / code).glob("[0-9]*.csv")}
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "code", "name", "shares", "weight"])
        for d in sorted(hist):
            if d in daily:
                continue  # 已在每日資料夾，不重複存
            for c, (n, s, wt) in sorted(hist[d].items()):
                w.writerow([d, c, n, "" if s is None else int(s), "" if wt is None else wt])


# ---------------- 交易日曆、生效日 ----------------
def trading_days():
    return sorted(f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}" for f in DATA.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")
                  if len(f.stem) == 8)


def effective_dates():
    """ETF → 指數名稱、[生效日...]（臺灣指數公司日程＋定審結果；追蹤 MSCI 臺灣指數的用 MSCI 審核日）"""
    idx = {}
    p = DATA / "etf" / "tip" / "etf_index.csv"
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            idx = {r["etf"]: r["index"] for r in csv.DictReader(fp)}
    by = defaultdict(set)
    for f in ("schedule.csv", "results.csv"):
        q = DATA / "etf" / "tip" / f
        if q.exists():
            with q.open(encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    if r.get("effective_date"):
                        by[r["index"]].add(r["effective_date"])
    msci = set()
    q = DATA / "etf" / "msci" / "schedule.csv"
    if q.exists():
        with q.open(encoding="utf-8") as fp:
            msci = {r["effective_date"] for r in csv.DictReader(fp) if r.get("effective_date")}
    out = {}
    for etf, name in idx.items():
        ds = set(by.get(name, set()))
        if "MSCI" in name and "臺灣指數" in name.replace("台", "臺"):
            ds |= msci
        out[etf] = (name, sorted(ds))
    return out


# ---------------- 偵測換股事件 ----------------
def _members(day):
    return {c for c, (_, s, w) in day.items() if (s or 0) > 0 or (w or 0) > 0}


def change_intervals(hist, tdays):
    """相鄰兩個取樣日成分股不同、且中間還有沒取樣的交易日 → 需要補抓的區間"""
    ds = sorted(hist)
    out = []
    for a, b in zip(ds, ds[1:]):
        if _members(hist[a]) != _members(hist[b]):
            ia, ib = tdays.index(a) if a in tdays else None, tdays.index(b) if b in tdays else None
            if ia is not None and ib is not None and ib - ia > 1:
                out.append((a, b))
    return out


def clean(hist):
    """成分股數不到平常（中位數）70% 的那天視為資料不完整，略過"""
    counts = sorted(len(_members(v)) for v in hist.values())
    if not counts:
        return hist
    med = counts[len(counts) // 2]
    return {d: v for d, v in hist.items() if len(_members(v)) >= 0.7 * med}


def detect_events(hist, tdays, eff_dates):
    hist = clean(hist)
    ds = sorted(d for d in hist if d in tdays)
    if len(ds) < 2:
        return []
    ti = {d: i for i, d in enumerate(tdays)}
    change_days = [b for a, b in zip(ds, ds[1:]) if _members(hist[a]) != _members(hist[b])]
    # 相距 15 個交易日內的變動視為同一次換股
    groups, cur = [], []
    for d in change_days:
        if cur and ti[d] - ti[cur[-1]] > 15:
            groups.append(cur)
            cur = []
        cur.append(d)
    if cur:
        groups.append(cur)
    events = []
    for g in groups:
        first, last = g[0], g[-1]
        pre = max((d for d in ds if d < first), default=None)
        post = last
        # post 往後延到成分股穩定（之後幾個取樣日不再變動）
        later = [d for d in ds if d >= last]
        for d in later[1:4]:
            if _members(hist[d]) == _members(hist[post]):
                post = d
                break
        if not pre:
            continue
        P, Q = hist[pre], hist[post]
        adds = sorted(_members(Q) - _members(P))
        dels = sorted(_members(P) - _members(Q))
        if not adds and not dels:
            continue
        # 只有單邊大量增減（例如某天持股檔少抓一半）不是換股
        if (not dels and len(adds) > 10) or (not adds and len(dels) > 10) \
                or len(adds) + len(dels) > 0.6 * max(len(_members(Q)), 1):
            continue
        window = [d for d in ds if pre <= d <= post]
        starts, ends = [], []
        for c in dels:
            w0 = P[c][2] or 0
            st = next((d for d in window if d > pre and (c not in hist[d] or (hist[d][c][2] or 0) < 0.8 * w0)), None)
            en = next((d for d in window if d > pre and c not in _members(hist[d])), None)
            if st:
                starts.append(st)
            if en:
                ends.append(en)
        for c in adds:
            w1 = Q[c][2] or 0
            st = next((d for d in window if c in _members(hist[d])), None)
            en = next((d for d in window if c in hist[d] and (hist[d][c][2] or 0) >= 0.9 * w1), None)
            if st:
                starts.append(st)
            if en:
                ends.append(en)
        if not starts or not ends:
            continue
        s, e = min(starts), max(ends)
        # 取樣密度：開始前一個取樣日到開始之間差幾個交易日（1＝逐日都有，時長準確）
        prev = max((d for d in ds if d < s), default=s)
        res = max(ti[s] - ti[prev], 1)
        eff = min((x for x in eff_dates if x in ti and -12 <= ti[x] - ti[s] <= 12 + ti[e] - ti[s]),
                  key=lambda x: abs(ti[x] - ti[s]), default="")
        events.append({"pre_date": pre, "post_date": post, "start": s, "end": e, "days": ti[e] - ti[s] + 1,
                       "effective": eff, "start_off": (ti[s] - ti[eff]) if eff else "",
                       "end_off": (ti[e] - ti[eff]) if eff else "", "n_add": len(adds), "n_del": len(dels),
                       "adds": " ".join(adds), "dels": " ".join(dels), "resolution": res})
    return events


# ---------------- 主程式 ----------------
def etf_list():
    src = (ROOT / "fetch_etf.py").read_text(encoding="utf-8")
    return [m for m in re.findall(r'\("(\w+)",\s*"([^"]+)",\s*"(\w+)",\s*"(\w+)"\)', src)]


def run_etf(code, name, issuer, a, deadline, asked, tdays):
    hist = load_hist(code)
    done = set(asked.get(code, []))
    start = (datetime.now(C.TPE).date() - timedelta(days=a.days)).isoformat()
    cal = [d for d in tdays if d >= start]

    def fetch(d):
        if d in done or time.time() > deadline:
            return
        got = holdings_on(issuer, code, name, date.fromisoformat(d))
        done.add(d)
        if got:
            gd, rows = got
            hist[gd] = {r["code"]: (r["name"], r["shares"], r["weight"]) for r in rows}
        time.sleep(0.3)

    for d in cal[::a.step] + cal[-1:]:  # 粗掃
        fetch(d)
    for _ in range(4):  # 有變動的區間逐日補齊（最多細化 4 輪）
        iv = change_intervals(clean(hist), tdays)
        if not iv or time.time() > deadline:
            break
        for x, y in iv:
            i, j = tdays.index(x), tdays.index(y)
            for d in tdays[max(0, i - 3): j + 4]:
                fetch(d)
    save_hist(code, hist)
    with _lock:
        asked[code] = sorted(done)
    return code, len(hist)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etfs", nargs="*")
    ap.add_argument("--days", type=int, default=400, help="往回查幾天（預設 400）")
    ap.add_argument("--step", type=int, default=5, help="粗掃間隔（工作天）")
    ap.add_argument("--max-minutes", type=float, default=40)
    ap.add_argument("--analyze-only", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    tdays = trading_days()
    asked_p = OUT / "asked.json"
    asked = json.loads(asked_p.read_text()) if asked_p.exists() else {}
    targets = [(c, n, i) for c, n, i, k in etf_list() if k == "passive" and i in HIST_ISSUERS
               and (not a.etfs or c in a.etfs)]
    if not a.analyze_only:
        deadline = time.time() + a.max_minutes * 60
        by_issuer = defaultdict(list)
        for t in targets:
            by_issuer[t[2]].append(t)

        def work(items):
            return [run_etf(c, n, i, a, deadline, asked, tdays) for c, n, i in items]
        with ThreadPoolExecutor(max_workers=len(by_issuer) or 1) as ex:  # 不同投信平行，同一家依序
            for res in ex.map(work, by_issuer.values()):
                for code, n in res:
                    print(f"{code}: {n} 個持股日")
        asked_p.write_text(json.dumps(asked, ensure_ascii=False), encoding="utf-8")

    effs = effective_dates()
    rows = []
    for code, name, issuer in targets:
        index, eff = effs.get(code, ("", []))
        for ev in detect_events(load_hist(code), tdays, eff):
            rows.append({"etf": code, "name": name, "issuer": issuer, "index": index, **ev})
    rows.sort(key=lambda r: (r["etf"], r["start"]))
    with (OUT / "events.csv").open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=EV_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(targets)} 檔 ETF、{len(rows)} 次換股事件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
