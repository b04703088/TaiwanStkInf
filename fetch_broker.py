#!/usr/bin/env python3
"""抓取每檔股票的券商分點進出：前 15 大買超、前 15 大賣超分點。

資料來源：富邦證券網站「券商分點-進出明細」（MoneyDJ 系統，公開頁面、免登入）
  https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a=<代號>&e=<日期>&f=<日期>
  單位：張。只公布前 15 大，不是全部分點。

輸出（日期 = 交易日）：
  data/broker/<YYYY>/<YYYYMMDD>.csv
      date, code, side(B 買超／S 賣超), rank, bid(分點代號), broker(分點名稱), buy, sell, net, pct
      net = buy − sell（賣超為負數）；pct = 佔當日成交量比重（%）
  data/broker/<YYYY>/<YYYYMMDD>_total.csv
      date, code, buy_total, sell_total, buy_cost, sell_cost
      前 15 大合計買超／賣超張數與平均成本；查詢過但當天沒有資料的股票四欄留空

股票清單取自同一天的收盤行情檔（data/<YYYY>/<YYYYMMDD>.csv），只抓成交金額 ≥ --min-value
（預設 3000 萬元，約 900 檔、涵蓋當天 99% 以上成交金額）；--min-value 0 = 有成交的全部（約 2,400 檔）。
門檻是為了省 GitHub Actions 分鐘數（私人 repo 免費方案每月 2,000 分鐘）。
已有分點資料的股票會略過，中途中斷、部分失敗或「查無資料」（太早抓到空頁）時，重跑只補這些。
每次執行也會順便補前 12 個交易日裡還是空頁的股票（--recheck-days）。
資料還沒出來（收盤後要一段時間）時直接結束、不算失敗，下一次排程再抓。
--wait-until HH:MM：還沒出來就每 5 分鐘再看一次，等到台北時間 HH:MM 為止（傍晚那次用，資料一出來就抓）。

用法：
  python fetch_broker.py                 最新一個有收盤行情的交易日
  python fetch_broker.py --date 2026-09-30
  python fetch_broker.py --codes 2330 2454   只抓這幾檔（測試用）
  python fetch_broker.py --min-value 0       有成交的全部都抓
  python fetch_broker.py --wait-until 20:30  還沒公布就等，最晚等到 20:30
"""
import argparse
import csv
import html
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "broker"
BASE = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"
ROW_COLS = ["date", "code", "side", "rank", "bid", "broker", "buy", "sell", "net", "pct"]
TOTAL_COLS = ["date", "code", "buy_total", "sell_total", "buy_cost", "sell_cost"]
PROBE = "2330"           # 用來判斷當天資料是否已經出來
DELAY = 0.15             # 每頁之間的間隔（秒），一次只開一條連線
FAIL_RATIO = 0.03        # 失敗比例超過就讓 workflow 標示失敗

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_LINK = re.compile(r'href="[^"]*[?&]b=([0-9A-Za-z]+)[^"]*"[^>]*>(.*?)</a>', re.S | re.I)


def decode_bid(b):
    """分點代號：純數字直接用；含英文字母的會編成 UTF-16 hex（0039004200320030 → 9B20）。"""
    if len(b) % 4 == 0 and len(b) >= 8 and re.fullmatch(r"[0-9a-fA-F]+", b) and b.startswith("00"):
        try:
            return "".join(chr(int(b[i:i + 4], 16)) for i in range(0, len(b), 4))
        except ValueError:
            pass
    return b


def _clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _num(s):
    s = _clean(s).replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse(page, date, code):
    """回傳 (rows, total)；當天沒有資料時 rows 為空。"""
    rows, total = [], {"date": date, "code": code, "buy_total": "", "sell_total": "", "buy_cost": "", "sell_cost": ""}
    rank = {"B": 0, "S": 0}
    for tr in _TR.findall(page):
        tds = _TD.findall(tr)
        if len(tds) >= 10 and "zco0" in tr:
            for side, cells in (("B", tds[0:5]), ("S", tds[5:10])):
                m = _LINK.search(cells[0])
                if not m:
                    continue
                buy, sell = _num(cells[1]), _num(cells[2])
                if buy is None or sell is None:
                    continue
                rank[side] += 1
                rows.append({"date": date, "code": code, "side": side, "rank": rank[side],
                             "bid": decode_bid(m.group(1)), "broker": _clean(m.group(2)),
                             "buy": int(buy), "sell": int(sell), "net": int(buy - sell),
                             "pct": _num(cells[4])})
        elif "合計買超張數" in tr or "平均買超成本" in tr:
            vals = [_num(td) for td in tds]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 2:
                k = ("buy_total", "sell_total") if "合計" in tr else ("buy_cost", "sell_cost")
                total[k[0]], total[k[1]] = vals[0], vals[1]
    if not rows:
        total.update(buy_total="", sell_total="", buy_cost="", sell_cost="")
    return rows, total


def fetch_page(code, date):
    y, m, d = (int(x) for x in date.split("-"))
    ds = f"{y}-{m}-{d}"
    raw = C.http(BASE, {"a": code, "e": ds, "f": ds}, raw=True, retries=3)
    return raw.decode("cp950", errors="replace")


def price_file(date):
    return DATA / date[:4] / f"{date.replace('-', '')}.csv"


def latest_trading_day():
    files = sorted(DATA.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    s = files[-1].stem
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


MIN_VALUE = 30_000_000  # 成交金額門檻（元）


def stock_list(date, min_value=MIN_VALUE):
    """當天有成交、且成交金額 ≥ min_value 的股票（依成交金額大到小，時間不夠時先抓大的）。"""
    with price_file(date).open(encoding="utf-8") as fp:
        rows = [r for r in csv.DictReader(fp) if (C.num(r.get("volume")) or 0) > 0
                and (C.num(r.get("value")) or 0) >= min_value]
    rows.sort(key=lambda r: -(C.num(r.get("value")) or 0))
    return [r["code"] for r in rows]


def out_paths(date):
    d = OUT / date[:4]
    return d / f"{date.replace('-', '')}.csv", d / f"{date.replace('-', '')}_total.csv"


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def save(date, rows, totals, order):
    rp, tp = out_paths(date)
    pos = {c: i for i, c in enumerate(order)}
    rows.sort(key=lambda r: (pos.get(r["code"], 1e9), r["code"], r["side"], int(r["rank"])))
    totals.sort(key=lambda r: (pos.get(r["code"], 1e9), r["code"]))
    _write(rp, ROW_COLS, rows)
    _write(tp, TOTAL_COLS, totals)


def fetch_date(date, codes, deadline, retry_rounds=0, retry_wait=120):
    """抓 date 這天 codes 裡還沒有分點資料的股票。回傳 (本次抓的檔數, 失敗代號, 仍查無資料檔數)。

    「查無資料」（頁面沒有任何分點）不算抓過：富邦收盤後是一檔一檔陸續算好的，太早抓會拿到空頁，
    2026-11-03 起 18:01 一公布就抓，每天有 60～280 檔空頁被當成已抓、之後再也不補。
    現在空頁不記為完成，同一次執行最後再隔 retry_wait 秒重抓 retry_rounds 輪，下一次排程也會再補。
    """
    rp, tp = out_paths(date)
    rows, totals = _read(rp), _read(tp)
    have = {t["code"] for t in totals if t["buy_total"] != ""}
    todo = [c for c in codes if c not in have]
    if not todo:
        return 0, [], 0
    by_code = {t["code"]: t for t in totals}
    failed, n_new, empty = [], 0, []
    for rnd in range(retry_rounds + 1):
        if rnd:
            if time.time() + retry_wait > deadline:
                break
            print(f"  {date}: {len(todo)} 檔查無分點資料，{retry_wait} 秒後重抓（第 {rnd} 輪）", flush=True)
            time.sleep(retry_wait)
        empty = []
        for i, code in enumerate(todo, 1):
            if time.time() > deadline:
                print(f"  時間到，先存檔，{date} 剩 {len(todo) - i + 1} 檔下次再抓")
                empty += todo[i - 1:]
                break
            try:
                r, t = parse(fetch_page(code, date), date, code)
            except C.AdapterError as e:
                failed.append(code)
                print(f"  {code} 失敗：{e}", file=sys.stderr)
                continue
            if r:
                rows = [x for x in rows if x["code"] != code] + r
            by_code[code] = t
            n_new += 1
            if not r:
                empty.append(code)
            if i % 200 == 0:
                save(date, rows, list(by_code.values()), codes)
                print(f"  {i}/{len(todo)}")
            time.sleep(DELAY)
        save(date, rows, list(by_code.values()), codes)
        todo = [c for c in empty if c not in failed]
        if not todo:
            break
    with_data = sum(1 for t in by_code.values() if t["buy_total"] != "")
    print(f"{date}: 本次 {n_new} 頁，累計 {len(by_code)}/{len(codes)} 檔（有分點資料 {with_data} 檔，"
          f"查無資料 {len(todo)} 檔），失敗 {len(failed)} -> {rp}", flush=True)
    return n_new, failed, len(todo)


def recent_dates_with_empty(date, days):
    """date 之前 days 個交易日中，_total.csv 裡還有「查無資料」股票的日期（新到舊）。"""
    files = sorted(OUT.glob("[0-9][0-9][0-9][0-9]/[0-9]*_total.csv"), key=lambda p: p.name)
    out = []
    for f in reversed(files):
        d = f.stem[:8]
        d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        if d >= date:
            continue
        if len(out) >= days:
            break
        out.append((d, sum(1 for t in _read(f) if t["buy_total"] == "")))
    return [d for d, n in out if n]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="交易日 YYYY-MM-DD（預設：最新收盤行情的日期）")
    ap.add_argument("--codes", nargs="*", help="只抓這些股票")
    ap.add_argument("--max-minutes", type=float, default=100, help="最多跑幾分鐘，時間到先存檔（預設 100）")
    ap.add_argument("--min-value", type=float, default=MIN_VALUE,
                    help="只抓成交金額 ≥ 這個數字（元）的股票；0 = 全部（預設 3000 萬）")
    ap.add_argument("--wait-until", metavar="HH:MM",
                    help="資料還沒公布就每 5 分鐘再查一次，最晚等到台北時間 HH:MM")
    ap.add_argument("--retry-rounds", type=int, default=3, help="查無資料的股票，同一次執行最後再重抓幾輪（預設 3）")
    ap.add_argument("--recheck-days", type=int, default=12,
                    help="順便補前幾個交易日裡「查無資料」的股票（預設 12；0 = 不補）")
    a = ap.parse_args(argv)

    date = a.date or latest_trading_day()
    if not price_file(date).exists():
        print(f"{date} 沒有收盤行情檔，無法決定股票清單（非交易日或股價還沒抓）")
        return 0
    deadline = time.time() + a.max_minutes * 60
    codes = a.codes or stock_list(date, a.min_value)
    rp, tp = out_paths(date)
    have = {t["code"] for t in _read(tp) if t["buy_total"] != ""}
    todo = [c for c in codes if c not in have]
    failed, n_todo = [], len(todo)
    if not todo:
        print(f"{date}: {len(have)} 檔都已有分點資料")
    else:
        # 先確認當天資料已經出來
        probe_rows, _ = parse(fetch_page(PROBE, date), date, PROBE)
        if not probe_rows and a.wait_until:
            tpe = timezone(timedelta(hours=8))
            now = datetime.now(tpe)
            hh, mm = map(int, a.wait_until.split(":"))
            until = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            while not probe_rows and datetime.now(tpe) + timedelta(minutes=5) <= until:
                print(f"{date}: 分點資料尚未公布，{datetime.now(tpe):%H:%M} 起等 5 分鐘再查（最晚 {a.wait_until}）", flush=True)
                time.sleep(300)
                probe_rows, _ = parse(fetch_page(PROBE, date), date, PROBE)
        if not probe_rows:
            print(f"{date}: 分點資料尚未公布（{PROBE} 查無資料），稍後再抓")
            return 0
        _, failed, _ = fetch_date(date, codes, deadline, a.retry_rounds)

    # 回補前幾天的空頁（只在抓最新一天、沒有指定股票時做）
    if not a.codes and a.recheck_days > 0:
        for d in recent_dates_with_empty(date, a.recheck_days):
            if time.time() > deadline:
                break
            if not price_file(d).exists():
                continue
            fetch_date(d, stock_list(d, a.min_value), deadline, retry_rounds=0)
    return 1 if n_todo and len(failed) > FAIL_RATIO * n_todo else 0


if __name__ == "__main__":
    sys.exit(main())
