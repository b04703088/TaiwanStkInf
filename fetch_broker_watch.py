#!/usr/bin/env python3
"""重點分點追蹤：抓 config/broker_watch.csv 裡每個分點每天買賣了哪些股票（金額＋張數）。

資料來源：富邦證券網站「分點明細查詢」（MoneyDJ，公開頁面、免登入）
  https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgb/zgb0.djhtm?a=<券商>&b=<分點>&c=B|E&e=<日期>&f=<日期>
  c=B 金額（仟元）、c=E 張數；每邊（買超／賣超）最多列 50 檔。

設定檔 config/broker_watch.csv（label 顯示名稱, branch 富邦網站上的分點名稱）：
  新增分點：加一行；刪除：刪一行。名稱查 data/broker/branches.csv（全部約 900 個分點）。
  總公司就寫券商名稱本身，例如「康和」「元大」。

輸出 data/broker/watch/<YYYY>/<YYYYMMDD>.csv：
  date, bid, branch, code, name, buy_amt, sell_amt, net_amt, buy_sh, sell_sh, net_sh
  金額單位：仟元；張數單位：張。某檔只出現在其中一種排行時，另一種留空。

每次執行都會檢查最近 --days 個交易日（預設 20），只補還沒抓過的「日期 × 分點」，
所以新增分點後會自動回補近 20 個交易日；當天資料還沒公布時略過，下次再抓。

用法：python fetch_broker_watch.py [--days 20]
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
OUT = DATA / "broker" / "watch"
CONFIG = ROOT / "config" / "broker_watch.csv"
BRANCHES = DATA / "broker" / "branches.csv"
SITE = "https://fubon-ebrokerdj.fbs.com.tw"
COLS = ["date", "bid", "branch", "code", "name", "buy_amt", "sell_amt", "net_amt", "buy_sh", "sell_sh", "net_sh"]
DELAY = 0.3

_HEX = re.compile(r"00[0-9a-fA-F]{2}(?:00[0-9a-fA-F]{2})+")


def dec(x):
    """富邦的代號：含英文字母時編成 UTF-16 hex（0039004100390067 → 9A9g）。"""
    if len(x) % 4 == 0 and _HEX.fullmatch(x):
        return "".join(chr(int(x[i:i + 4], 16)) for i in range(0, len(x), 4))
    return x


def enc(x):
    return x if x.isdigit() else "".join(f"{ord(ch):04x}" for ch in x)


def parse_branch_list(js):
    """zbrokerjs.djjs 的 g_BrokerList → [(券商代號, 券商名稱, 分點代號, 分點名稱)]"""
    m = re.search(r"g_BrokerList\s*=\s*'([^']*)'", js)
    out = []
    for group in (m.group(1).split(";") if m else []):
        items = group.split("!")
        if len(items) < 2 or "," not in items[0]:
            continue
        hq_id, hq_name = items[0].split(",", 1)
        for it in items[1:]:
            if "," in it:
                bid, name = it.split(",", 1)
                out.append((dec(hq_id), hq_name, dec(bid), name))
    return out


def load_branches(refresh=True):
    rows = []
    if refresh:
        try:
            js = C.http(SITE + "/z/js/zbrokerjs.djjs", raw=True).decode("cp950", errors="replace")
            rows = parse_branch_list(js)
        except C.AdapterError as e:
            print(f"分點清單抓取失敗，改用快取：{e}", file=sys.stderr)
    if len(rows) > 500:
        BRANCHES.parent.mkdir(parents=True, exist_ok=True)
        with BRANCHES.open("w", newline="", encoding="utf-8") as fp:
            w = csv.writer(fp)
            w.writerow(["broker_id", "broker", "bid", "branch"])
            w.writerows(rows)
        return rows
    if BRANCHES.exists():
        with BRANCHES.open(encoding="utf-8") as fp:
            return [(r["broker_id"], r["broker"], r["bid"], r["branch"]) for r in csv.DictReader(fp)]
    return rows


def load_config():
    with CONFIG.open(encoding="utf-8-sig") as fp:
        out = []
        for r in csv.DictReader(fp):
            b = (r.get("branch") or "").strip()
            if b and not b.startswith("#"):
                out.append({"label": (r.get("label") or "").strip() or b, "branch": b})
        return out


def resolve(config, branches):
    """設定的分點名稱 → (券商代號, 分點代號)；找不到時提示相近名稱。"""
    by_name = {}
    for hq_id, _, bid, name in branches:
        by_name.setdefault(name, (hq_id, bid))
    ok, missing = [], []
    for c in config:
        name = c["branch"].replace("總公司", "") if c["branch"] not in by_name else c["branch"]
        if name in by_name:
            ok.append({**c, "hq": by_name[name][0], "bid": by_name[name][1]})
        else:
            near = [n for n in by_name if c["branch"].split("-")[-1] in n][:6]
            missing.append(f"{c['branch']}（相近：{'、'.join(near) or '無'}）")
    return ok, missing


def _num(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _stock(cell):
    m = re.search(r"GenLink2stk\('A[A-Z]?([^']+)','([^']*)'\)", cell)
    if m:
        return m.group(1), html.unescape(m.group(2)).strip()
    m = re.search(r"Link2Stk\('([^']+)'\);\">(.*?)</a>", cell, re.S)
    if m:
        code = m.group(1)
        name = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        return code, name[len(code):].strip() if name.startswith(code) else name
    return None, None


def parse_zgb(page):
    """回傳 (資料日期 'YYYY-MM-DD' 或 None, {代號: (名稱, 買, 賣)})；買超、賣超兩張表合併。"""
    m = re.search(r"資料日期：\s*(\d{8})", page)
    date = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(tds) != 4 or "Link2" not in tds[0] and "GenLink2stk" not in tds[0]:
            continue
        code, name = _stock(tds[0])
        buy, sell = _num(tds[1]), _num(tds[2])
        if code and buy is not None and sell is not None:
            out[code] = (name, buy, sell)
    return date, out


def fetch(hq, bid, kind, date):
    y, m, d = (int(x) for x in date.split("-"))
    ds = f"{y}-{m}-{d}"
    raw = C.http(SITE + "/z/zg/zgb/zgb0.djhtm", {"a": enc(hq), "b": enc(bid), "c": kind, "e": ds, "f": ds}, raw=True)
    return parse_zgb(raw.decode("cp950", errors="replace"))


def trading_days(n):
    files = sorted(DATA.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)[-n:]
    return [f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:8]}" for f in files]


def day_path(date):
    return OUT / date[:4] / f"{date.replace('-', '')}.csv"


def read_day(date):
    p = day_path(date)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def write_day(date, rows):
    p = day_path(date)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["bid"], -abs(float(r["net_amt"] or 0)), r["code"]))
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def branch_rows(date, b, amt, sh):
    def f(x):
        return "" if x is None else int(round(x))
    rows = []
    for code in sorted(set(amt) | set(sh)):
        name = (amt.get(code) or sh.get(code))[0]
        ba, sa = (amt[code][1], amt[code][2]) if code in amt else (None, None)
        bs, ss = (sh[code][1], sh[code][2]) if code in sh else (None, None)
        rows.append({"date": date, "bid": b["bid"], "branch": b["branch"], "code": code, "name": name,
                     "buy_amt": f(ba), "sell_amt": f(sa), "net_amt": f(None if ba is None else ba - sa),
                     "buy_sh": f(bs), "sell_sh": f(ss), "net_sh": f(None if bs is None else bs - ss)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=20, help="檢查最近幾個交易日（預設 20）")
    a = ap.parse_args(argv)

    watch, missing = resolve(load_config(), load_branches())
    for m in missing:
        print(f"找不到分點：{m}", file=sys.stderr)
    failed, fetched = [], 0
    for date in reversed(trading_days(a.days)):  # 新到舊：當天還沒公布就跳過那天
        rows = read_day(date)
        have = {r["bid"] for r in rows}
        todo = [b for b in watch if b["bid"] not in have]
        if not todo:
            continue
        added = []
        for b in todo:
            try:
                d1, amt = fetch(b["hq"], b["bid"], "B", date)
                time.sleep(DELAY)
                if d1 != date:
                    print(f"{date} {b['label']}：資料尚未公布（頁面日期 {d1}）")
                    break
                _, sh = fetch(b["hq"], b["bid"], "E", date)
                time.sleep(DELAY)
            except C.AdapterError as e:
                failed.append(f"{date} {b['label']}")
                print(f"  {date} {b['label']} 失敗：{e}", file=sys.stderr)
                continue
            added += branch_rows(date, b, amt, sh)
            fetched += 1
        if added:
            write_day(date, rows + added)
            print(f"{date}: 新增 {len({r['bid'] for r in added})} 個分點、{len(added)} 筆")
    print(f"完成：抓了 {fetched} 個「日期×分點」，失敗 {len(failed)}，設定找不到 {len(missing)}")
    return 1 if failed or missing else 0


if __name__ == "__main__":
    sys.exit(main())
