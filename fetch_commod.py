#!/usr/bin/env python3
"""原物料報價頁用的日資料：能源、金屬、農產品、化工、航運運價、記憶體現貨。

資料來源（品項與代號見 config/commod_items.csv 的 sources，「來源:代號」，| 分隔依序嘗試）
  yahoo  Yahoo Finance chart API  https://query1.finance.yahoo.com/v8/finance/chart/<代號>?range=5y&interval=1d
         美國期貨近月連續（CL=F、GC=F…）與 ETF（BDRY、BWET）
  sina   新浪財經 中國期貨主力連續日 K
         https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.getDailyKLine?symbol=<代號>
         主力合約換月時價格會跳一下（不調整）
  sinag  新浪財經 外盤期貨日 K（LME 3 個月）
         https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=<代號>
  （運價指數、記憶體現貨另見下面各函式）
  容器 proxy 連不到以上網站，只能在 GitHub Actions 跑。

輸出 data/commod/daily.csv：date, key, close, source
  每次抓完整歷史並覆蓋重疊日期，只保留 2018 年起。

用法：python fetch_commod.py [--only key1,key2]
"""
import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "commod" / "daily.csv"
ITEMS = ROOT / "config" / "commod_items.csv"
SINCE = "2018-01-01"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
SINA_REF = {"Referer": "https://finance.sina.com.cn/"}


def get(url, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo(sym):
    q = urllib.parse.quote(sym)
    j = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?range=10y&interval=1d"))
    res = j["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    out = {}
    for ts, v in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
        if v is not None:
            out[datetime.fromtimestamp(ts + off, timezone.utc).date().isoformat()] = round(v, 4)
    return out


def _sina_rows(text):
    m = re.search(r"\((\[.*\])\)", text, re.S)
    return json.loads(m.group(1)) if m else []


def sina(sym):
    t = get("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/"
            f"InnerFuturesNewService.getDailyKLine?symbol={sym}", SINA_REF)
    return {r["d"]: float(r["c"]) for r in _sina_rows(t) if float(r["c"])}


def sinag(sym):
    t = get("https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/"
            f"GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={sym}&source=web", SINA_REF)
    return {r["date"]: float(r["close"]) for r in _sina_rows(t) if float(r["close"])}


MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_page = {}


def _text(url, headers=None):
    """抓網頁轉成純文字（同一頁只抓一次）。"""
    if url not in _page:
        t = get(url, headers)
        t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", t, flags=re.S)
        _page[url] = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    return _page[url]


def dramx(name):
    """DRAMeXchange 首頁的現貨價：品名後面 5 個數字的最後一個是當天（週）均價；日期取前面最近的 Last Update。"""
    t = _text("https://www.dramexchange.com/")
    i = t.find(name + " ")
    if i < 0:
        return {}
    m = re.match(r"\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", t[i + len(name):])
    ds = list(re.finditer(r"Last ?Update: ?([A-Z][a-z]{2})\.? ?(\d{1,2}),? (\d{4})", t[:i]))
    if not m or not ds:
        return {}
    mon, day, yr = ds[-1].groups()
    return {f"{yr}-{MON[mon]:02d}-{int(day):02d}": float(m.group(5))}


def cnyes(code):
    """鉅亨網航運指數（BDI、BCI…）：線圖頁內嵌近一年日資料 globalData.push([.., 'YYYYMMDD', 開, 高, 低, 收, ..])。"""
    t = get("https://so.cnyes.com/JavascriptGraphic/chartstudy.aspx?country=future&market=future"
            f"&code={urllib.parse.quote(code)}&divwidth=650&divheight=330",
            {"Referer": f"https://www.cnyes.com/futures/html5chart/{code}.html"})
    out = {}
    for d, c in re.findall(r"globalData\.push\(\[[^,]*,[^,]*,'(\d{8})',[^,]*,[^,]*,[^,]*,([\d.]+)", t):
        if float(c):
            out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = float(c)
    return out


def sse(spec):
    """上海航運交易所單期頁（週資料，免登入只看得到本期和上期）：spec＝指數:欄位名稱。
    多期查詢 /index/mutipleIndex 要登入，所以歷史靠每週累積。"""
    idx, _, label = spec.partition(":")
    t = _text(f"https://www.sse.net.cn/index/singleIndex?indexType={idx}")
    d = re.search(r"上期 (\d{4}-\d{2}-\d{2}) 本期 (\d{4}-\d{2}-\d{2})", t)
    i = t.find(label)
    m = re.match(r"[^\d]*?([\d.]+) ([\d.]+)", t[i + len(label):]) if i >= 0 else None
    if not d or not m:
        return {}
    return {d.group(1): float(m.group(1)), d.group(2): float(m.group(2))}


FETCH = {"yahoo": yahoo, "sina": sina, "sinag": sinag, "dramx": dramx, "cnyes": cnyes, "sse": sse}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(filter(None, a.only.split(",")))
    rows = {}
    if OUT.exists():
        with OUT.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[(r["date"], r["key"])] = r
    with ITEMS.open(encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    fails = 0
    for it in items:
        k = it["key"]
        if only and k not in only:
            continue
        got = None
        for src in it["sources"].split("|"):
            name, _, sym = src.partition(":")
            try:
                got = FETCH[name](sym)
                if got:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  {k} {src} 失敗：{e}", file=sys.stderr)
            time.sleep(0.5)
        if not got:
            fails += 1
            continue
        for d, v in got.items():
            if d >= SINCE:
                rows[(d, k)] = {"date": d, "key": k, "close": v, "source": name}
        print(f"{k:14s} {name}:{sym} {len(got)} 筆，最新 {max(got)} {got[max(got)]}", flush=True)
        time.sleep(0.5)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "key", "close", "source"])
        w.writeheader()
        for key in sorted(rows):
            w.writerow(rows[key])
    print(f"寫入 {OUT}（{len(rows)} 筆），失敗 {fails} 項")
    return 1 if fails > len(items) // 2 else 0


if __name__ == "__main__":
    sys.exit(main())
