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

股票清單取自同一天的收盤行情檔（data/<YYYY>/<YYYYMMDD>.csv，成交量 > 0）。
已抓過的股票會略過，中途中斷或部分失敗時，重跑只補沒抓到的。
資料還沒出來（收盤後要一段時間）時直接結束、不算失敗，下一次排程再抓。

用法：
  python fetch_broker.py                 最新一個有收盤行情的交易日
  python fetch_broker.py --date 2026-09-30
  python fetch_broker.py --codes 2330 2454   只抓這幾檔（測試用）
"""
import argparse
import csv
import html
import re
import sys
import time
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


def stock_list(date):
    with price_file(date).open(encoding="utf-8") as fp:
        return [r["code"] for r in csv.DictReader(fp) if (C.num(r.get("volume")) or 0) > 0]


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="交易日 YYYY-MM-DD（預設：最新收盤行情的日期）")
    ap.add_argument("--codes", nargs="*", help="只抓這些股票")
    ap.add_argument("--max-minutes", type=float, default=100, help="最多跑幾分鐘，時間到先存檔（預設 100）")
    a = ap.parse_args(argv)

    date = a.date or latest_trading_day()
    if not price_file(date).exists():
        print(f"{date} 沒有收盤行情檔，無法決定股票清單（非交易日或股價還沒抓）")
        return 0
    codes = a.codes or stock_list(date)
    rp, tp = out_paths(date)
    rows, totals = _read(rp), _read(tp)
    done = {t["code"] for t in totals}
    todo = [c for c in codes if c not in done]
    if not todo:
        print(f"{date}: {len(done)} 檔都已抓過")
        return 0

    # 先確認當天資料已經出來
    probe_rows, _ = parse(fetch_page(PROBE, date), date, PROBE)
    if not probe_rows:
        print(f"{date}: 分點資料尚未公布（{PROBE} 查無資料），稍後再抓")
        return 0

    t0, failed, n_new = time.time(), [], 0
    for i, code in enumerate(todo, 1):
        if time.time() - t0 > a.max_minutes * 60:
            print(f"達到 {a.max_minutes} 分鐘上限，先存檔，剩 {len(todo) - i + 1} 檔下次再抓")
            break
        try:
            r, t = parse(fetch_page(code, date), date, code)
        except C.AdapterError as e:
            failed.append(code)
            print(f"  {code} 失敗：{e}", file=sys.stderr)
            continue
        rows += r
        totals.append(t)
        n_new += 1
        if i % 200 == 0:
            save(date, rows, totals, codes)
            print(f"  {i}/{len(todo)}（{time.time() - t0:.0f} 秒）")
        time.sleep(DELAY)
    save(date, rows, totals, codes)
    with_data = sum(1 for t in totals if t["buy_total"] != "")
    print(f"{date}: 本次 {n_new} 檔，累計 {len(totals)}/{len(codes)} 檔（有分點資料 {with_data} 檔）"
          f"，失敗 {len(failed)} -> {rp}")
    return 1 if len(failed) > FAIL_RATIO * len(todo) else 0


if __name__ == "__main__":
    sys.exit(main())
