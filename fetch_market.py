#!/usr/bin/env python3
"""大盤頁用的市場層級資料：指數開高低收、大盤估值、三大法人買賣金額、台指 VIX。

資料來源（公開免登入）
  加權指數 OHLC   https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date=YYYYMM01&response=json   （一次一個月）
  櫃買指數 OHLC   https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date=YYYY/MM/01&response=json     （一次一個月）
  個股本益比等    https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=YYYYMMDD&selectType=ALL&response=json
                  2005-09-02 起；舊格式沒有收盤價，要另外抓 MI_INDEX（type=ALLBUT0999）的個股收盤
  法人買賣金額    上市 https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate=YYYYMMDD&response=json
                  上櫃 https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date=YYYY/MM/DD&response=json
  台指 VIX        https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/YYYYMMnew.txt  （每月一檔，日資料；只留近 3 個月）
  推算 VIX        https://www.taifex.com.tw/cht/3/optDataDown（POST，TXO 選擇權日資料）→ scripts/vix_calc.py
                  用月選結算價照 CBOE 方法算；2016 起回補，跟官方重疊期平均差 0.1 點

輸出 data/market/
  taiex.csv  date,open,high,low,close
  tpex.csv   date,open,high,low,close
  val.csv    date,pe,pb,dy,mcap,n          上市普通股市值加權：本益比（只算有獲利的）、股價淨值比、殖利率%、總市值（億）、檔數
             市值＝收盤 × 最新一份集保總股數（近似發行股數；早年股數不同，權重是近似）
  inst.csv   date,market,f,fd,t,d_self,d_hedge   買賣超金額（元）；f＝外資及陸資（不含外資自營商），fd＝外資自營商
  vix.csv    date,open,high,low,close        期交所官方（目前只有收盤＝13:45 指數值）
  vix_calc.csv date,vix                      推算值（官方沒有的日子補洞，也用來抓官方收盤異常）

用法：
  python fetch_market.py                       # 例行：近兩個月指數／VIX、近 7 天估值與法人金額
  python fetch_market.py --since 2016-01 --only index,vix
  python fetch_market.py --since 2026-11-01 --only vixcalc
  python fetch_market.py --since 2010-01 --only val --weekly     # 估值回補：每週最後一個交易日
  python fetch_market.py --since 2025-06 --only inst
"""
import argparse
import csv
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "market"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
GAP = 3.2           # 證交所每次請求間隔（秒）
STOCK = re.compile(r"^[1-9]\d{3}$")
COLS = {"taiex": ["date", "open", "high", "low", "close"], "tpex": ["date", "open", "high", "low", "close"],
        "vix": ["date", "open", "high", "low", "close"], "vix_calc": ["date", "vix"], "val": ["date", "pe", "pb", "dy", "mcap", "n"],
        "inst": ["date", "market", "f", "fd", "t", "d_self", "d_hedge"]}
_last = [0.0]


def get(url, enc="utf-8", raw=False):
    import json
    wait = _last[0] + GAP - time.time()
    if wait > 0:
        time.sleep(wait)
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read()
                ct = r.headers.get("Content-Type") or ""
            _last[0] = time.time()
            if raw:
                return None if "html" in ct else b.decode(enc, "replace")
            return json.loads(b.decode(enc))
        except Exception as e:  # noqa: BLE001
            if k == 3:
                print(f"  失敗 {url}: {e!r}", file=sys.stderr)
                return None
            time.sleep(10 * 2 ** k)


def num(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def load(name):
    p = OUT / f"{name}.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    key = (lambda r: (r["date"], r["market"])) if name == "inst" else (lambda r: r["date"])
    return {key(r): r for r in rows}


def save(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{name}.csv").open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS[name])
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in COLS[name]})


def roc(s):
    """115/11/02 → 2026-11-02；2026/11/02 也接受。"""
    y, m, d = s.strip().split("/")
    y = int(y)
    return f"{y + 1911 if y < 1000 else y:04d}-{int(m):02d}-{int(d):02d}"


def months(since, until):
    y, m = since.year, since.month
    while (y, m) <= (until.year, until.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_index(since, until):
    tx, tp = load("taiex"), load("tpex")
    for y, m in months(since, until):
        j = get(f"https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={y}{m:02d}01&response=json")
        n1 = 0
        for r in (j or {}).get("data") or []:
            o, h, lo, c = (num(x) for x in r[1:5])
            if c:
                tx[roc(r[0])] = {"date": roc(r[0]), "open": o, "high": h, "low": lo, "close": c}
                n1 += 1
        j = get(f"https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?date={y}/{m:02d}/01&response=json")
        n2 = 0
        for t in (j or {}).get("tables") or []:
            for r in t.get("data") or []:
                o, h, lo, c = (num(x) for x in r[1:5])
                if c:
                    tp[roc(r[0])] = {"date": roc(r[0]), "open": o, "high": h, "low": lo, "close": c}
                    n2 += 1
        print(f"指數 {y}-{m:02d}：加權 {n1} 天、櫃買 {n2} 天")
    save("taiex", tx)
    save("tpex", tp)


def fetch_vix(since, until):
    vx = load("vix")
    for y, m in months(since, until):
        t = get(f"https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{y}{m:02d}new.txt", enc="big5", raw=True)
        n = 0
        for line in (t or "").splitlines():
            p = line.split()
            if len(p) >= 2 and re.fullmatch(r"\d{8}", p[0]):
                # 欄位：日期 時間 指數 收盤前1分鐘平均；收盤取 13:45 的指數值
                c = num(p[2]) if len(p) >= 3 else None
                if c is None:
                    continue
                d = f"{p[0][:4]}-{p[0][4:6]}-{p[0][6:]}"
                vx[d] = {"date": d, "open": None, "high": None, "low": None, "close": c}
                n += 1
        if t and n == 0:
            print("  VIX 檔格式看不懂，前幾行：", t[:300].replace("\n", " | "))
        print(f"VIX {y}-{m:02d}：{n} 天")
    save("vix", vx)


def fetch_vixcalc(since, until):
    """抓 TXO 選擇權日資料、用結算價推算 VIX（一次最多一個月）。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import urllib.parse
    import vix_calc
    vc = load("vix_calc")
    s = since
    while s <= until:
        e = min(until, (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
        body = urllib.parse.urlencode({"down_type": "1", "commodity_id": "TXO", "commodity_id2": "",
                                       "queryStartDate": s.strftime("%Y/%m/%d"), "queryEndDate": e.strftime("%Y/%m/%d")}).encode()
        t = None
        for k in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request("https://www.taifex.com.tw/cht/3/optDataDown", headers=UA, data=body), timeout=180) as r:
                    t = r.read().decode("big5", "replace")
                break
            except Exception as ex:
                print("  選擇權日資料失敗，重試：", ex)
                time.sleep(10)
        data, last = vix_calc.parse_taifex(t or "")
        res = vix_calc.compute(data, last, max(data) if data else "")
        for d, v in res.items():
            vc[d] = {"date": d, "vix": v}
        print(f"推算 VIX {s}～{e}：{len(res)} 天")
        s = e + timedelta(days=1)
    save("vix_calc", vc)


def trading_days():
    """用 data/YYYY/*.csv 與指數檔推交易日。"""
    ds = {f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}" for p in ROOT.glob("data/[0-9][0-9][0-9][0-9]/[0-9]*.csv") if len(p.stem) == 8}
    ds |= set(load("taiex"))
    return sorted(ds)


def shares():
    files = sorted((ROOT / "data" / "tdcc").glob("*.csv"))
    if not files:
        return {}
    with files[-1].open(encoding="utf-8") as fp:
        return {r["code"]: num(r["shares"]) for r in csv.DictReader(fp) if num(r.get("shares"))}


def fetch_val(days):
    vals, sh = load("val"), shares()
    for d in days:
        ymd = d.replace("-", "")
        j = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={ymd}&selectType=ALL&response=json")
        if not j or j.get("stat") != "OK" or not j.get("data"):
            print(f"估值 {d}：沒有資料")
            continue
        f = j["fields"]
        ix = {k: next((i for i, x in enumerate(f) if x.startswith(k)), None) for k in ("證券代號", "收盤價", "本益比", "殖利率", "股價淨值比")}
        close = {}
        if ix["收盤價"] is None:   # 舊格式：另抓個股收盤
            m = get(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json")
            for t in (m or {}).get("tables") or []:
                tf = t.get("fields") or []
                if "證券代號" in tf and "收盤價" in tf:
                    a, b = tf.index("證券代號"), tf.index("收盤價")
                    close = {r[a].strip(): num(r[b]) for r in t.get("data") or []}
        cap = earn = book = div = 0.0
        tot = 0.0
        n = 0
        for r in j["data"]:
            code = str(r[ix["證券代號"]]).strip()
            if not STOCK.match(code) or not sh.get(code):
                continue
            c = num(r[ix["收盤價"]]) if ix["收盤價"] is not None else close.get(code)
            if not c:
                continue
            mc = c * sh[code]
            tot += mc
            n += 1
            pe, pb, dy = num(r[ix["本益比"]]), num(r[ix["股價淨值比"]]), num(r[ix["殖利率"]])
            if pe and pe > 0:
                cap += mc
                earn += mc / pe
            if pb and pb > 0:
                book += mc / pb
            if dy is not None:
                div += mc * dy / 100
        if not tot or not earn:
            print(f"估值 {d}：算不出來（檔數 {n}）")
            continue
        vals[d] = {"date": d, "pe": round(cap / earn, 2), "pb": round(tot / book, 2) if book else "",
                   "dy": round(div / tot * 100, 2), "mcap": round(tot / 1e8), "n": n}
        print(f"估值 {d}：PE {vals[d]['pe']} PB {vals[d]['pb']} 殖利率 {vals[d]['dy']}% 市值 {vals[d]['mcap']} 億（{n} 檔）")
    save("val", vals)


def fetch_inst(days):
    rows = load("inst")
    for d in days:
        ymd = d.replace("-", "")
        j = get(f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={ymd}&response=json")
        if j and j.get("stat") == "OK" and j.get("data"):
            v = {r[0]: num(r[3]) for r in j["data"]}
            pick = lambda k: next((x for n, x in v.items() if n.startswith(k)), None)  # noqa: E731
            rows[(d, "TWSE")] = {"date": d, "market": "TWSE", "f": pick("外資及陸資"), "fd": pick("外資自營商"), "t": pick("投信"),
                                 "d_self": pick("自營商(自行"), "d_hedge": pick("自營商(避險")}
        j = get(f"https://www.tpex.org.tw/www/zh-tw/insti/summary?type=Daily&date={d.replace('-', '/')}&response=json")
        data = [r for t in (j or {}).get("tables") or [] for r in t.get("data") or []]
        if data:
            v = {r[0].strip("　 "): num(r[3]) for r in data}
            rows[(d, "TPEx")] = {"date": d, "market": "TPEx", "f": v.get("外資及陸資(不含自營商)"), "fd": v.get("外資自營商"), "t": v.get("投信"),
                                 "d_self": v.get("自營商(自行買賣)"), "d_hedge": v.get("自營商(避險)")}
        print(f"法人金額 {d}：上市 {'有' if (d, 'TWSE') in rows else '無'}・上櫃 {'有' if data else '無'}")
    save("inst", rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM 或 YYYY-MM-DD")
    ap.add_argument("--until", help="YYYY-MM-DD（預設今天）")
    ap.add_argument("--only", default="index,vix,vixcalc,val,inst")
    ap.add_argument("--weekly", action="store_true", help="估值／法人只抓每週最後一個交易日")
    ap.add_argument("--max-minutes", type=float, default=0)
    ap.add_argument("--merge-from", help="把另一個目錄的同名 CSV 併進 data/market（回補平行 job 用）")
    a = ap.parse_args()
    if a.merge_from:
        for name in COLS:
            p = Path(a.merge_from) / f"{name}.csv"
            if p.exists():
                with p.open(encoding="utf-8") as fp:
                    new = list(csv.DictReader(fp))
                cur = load(name)
                for r in new:
                    cur[(r["date"], r["market"]) if name == "inst" else r["date"]] = r
                save(name, cur)
                print(f"併入 {name}：{len(new)} 列 → {len(cur)} 列")
        return
    today = (datetime.utcnow() + timedelta(hours=8)).date()
    until = date.fromisoformat(a.until) if a.until else today
    only = set(a.only.split(","))
    if a.since:
        s = a.since if len(a.since) > 7 else a.since + "-01"
        since = date.fromisoformat(s)
    else:
        since = None
    msince = since or (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    if "index" in only:
        fetch_index(msince, until)
    if "vix" in only:
        fetch_vix(msince, until)
    if "vixcalc" in only:
        # 例行只算近 10 天；月選到期日由當月資料推（最後交易日），所以起點往前抓到月初
        fetch_vixcalc(since or (until - timedelta(days=10)).replace(day=1), until)
    td = [d for d in trading_days() if d <= until.isoformat()]
    if since:
        days = [d for d in td if d >= since.isoformat()]
        if a.weekly:
            wk = {}
            for d in days:
                wk[date.fromisoformat(d).isocalendar()[:2]] = d
            days = sorted(wk.values())
    else:
        days = td[-5:]
    t0 = time.time()
    if a.max_minutes:
        # 依時間上限截掉：每天約 2 次請求
        cap = int(a.max_minutes * 60 / (GAP * 2.2))
        if len(days) > cap:
            print(f"只抓前 {cap} 天（共 {len(days)}），剩下的下次再補")
            done = set(load("val")) if "val" in only else set(d for d, _ in load("inst"))
            days = [d for d in days if d not in done][:cap]
    if "val" in only:
        fetch_val(days)
    if "inst" in only:
        fetch_inst(days)
    print(f"完成，用了 {time.time() - t0:.0f} 秒")


if __name__ == "__main__":
    main()
