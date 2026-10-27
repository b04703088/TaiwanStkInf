#!/usr/bin/env python3
"""期貨選擇權籌碼：三大法人台指期／選擇權未平倉、Put/Call Ratio、台指期大額交易人、台指期行情（臺灣期貨交易所）。

資料來源（期交所下載專區，POST 表單，回傳 CSV（MS950），一次查一個月）
  三大法人期貨  https://www.taifex.com.tw/cht/3/futContractsDateDown   queryStartDate, queryEndDate, commodityId=（空白＝全部）
  三大法人選擇權 https://www.taifex.com.tw/cht/3/callsAndPutsDateDown  commodityId=TXO
  Put/Call Ratio https://www.taifex.com.tw/cht/3/pcRatioDown
  大額交易人    https://www.taifex.com.tw/cht/3/largeTraderFutDown（全部商品，只留臺股期貨）
  台指期行情    https://www.taifex.com.tw/cht/3/futDataDown  down_type=1, commodity_id=TX

輸出 data/futures/（口數；金額單位：千元）
  inst.csv   date, product, who, net_vol, net_val, oi_long, oi_short, oi_net, oi_net_val
             product：TX 臺股期貨、MTX 小型臺指、TMF 微型臺指、TXO_C 臺指買權、TXO_P 臺指賣權
             who：dealer 自營商、trust 投信、foreign 外資及陸資
  pcr.csv    date, put_vol, call_vol, pc_vol, put_oi, call_oi, pc_oi（比率 %）
  large.csv  date, month(all/near), kind(all/inst), top5_long, top5_short, top10_long, top10_short, oi
             kind=all 前五／十大交易人（全部）、inst 其中的特定法人；month=all 全部月份合計、near 近月
  tx.csv     date, contract（近月）, close, change, volume, settle, oi（近月）, oi_all（全部月份）

用法:
    python fetch_futures.py                        # 本月（月初幾天也補上個月）
    python fetch_futures.py --start 2024-01-01     # 回補（一次一個月）
"""
import argparse
import csv
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "futures"
BASE = "https://www.taifex.com.tw/cht/3/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
INTERVAL = 3
PRODUCTS = {"臺股期貨": "TX", "小型臺指期貨": "MTX", "微型臺指期貨": "TMF"}
WHO = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign", "外資": "foreign"}
COLS = {
    "inst": ["date", "product", "who", "net_vol", "net_val", "oi_long", "oi_short", "oi_net", "oi_net_val"],
    "pcr": ["date", "put_vol", "call_vol", "pc_vol", "put_oi", "call_oi", "pc_oi"],
    "large": ["date", "month", "kind", "top5_long", "top5_short", "top10_long", "top10_short", "oi"],
    "tx": ["date", "contract", "close", "change", "volume", "settle", "oi", "oi_all"],
}
KEYS = {"inst": ("date", "product", "who"), "pcr": ("date",), "large": ("date", "month", "kind"), "tx": ("date",)}


def post_csv(path, form, retries=4):
    body = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(BASE + path, data=body, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
            break
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt + 1}: {e!r}", file=sys.stderr)
            time.sleep(10 * 2 ** attempt)
    for enc in ("cp950", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("cp950", "replace")
    if "<html" in text[:500].lower():
        if "DateTime error" in text or "日期時間錯誤" in text:
            return []  # 查詢區間沒有資料（例如還沒開盤的月份）
        raise RuntimeError(f"{path} 回傳網頁而不是 CSV：{text[:200]!r}")
    rows = list(csv.reader(text.lstrip("﻿").splitlines()))
    return [[c.strip() for c in r] for r in rows[1:] if r and r[0].strip()[:2] == "20"]


def _d(s):
    return s.replace("/", "-")


def _n(s):
    s = s.replace(",", "").replace("%", "").strip()
    try:
        float(s)
        return s
    except ValueError:
        return ""


def parse_fut(rows):
    """日期, 商品名稱, 身份別, 多方交易口數, 多方金額, 空方口數, 空方金額, 淨口數, 淨金額, 多方未平倉, 金額, 空方未平倉, 金額, 未平倉淨額, 金額"""
    out = []
    for r in rows:
        if len(r) < 15 or r[1] not in PRODUCTS or r[2] not in WHO:
            continue
        out.append({"date": _d(r[0]), "product": PRODUCTS[r[1]], "who": WHO[r[2]], "net_vol": _n(r[7]), "net_val": _n(r[8]),
                    "oi_long": _n(r[9]), "oi_short": _n(r[11]), "oi_net": _n(r[13]), "oi_net_val": _n(r[14])})
    return out


def parse_opt(rows):
    """日期, 商品名稱, 買賣權別, 身份別, 買方口數, 金額, 賣方口數, 金額, 淨口數, 淨金額, 買方未平倉, 金額, 賣方未平倉, 金額, 未平倉淨口數, 淨金額"""
    out = []
    for r in rows:
        if len(r) < 16 or r[3] not in WHO or r[2].upper() not in ("CALL", "PUT", "買權", "賣權"):
            continue
        cp = "C" if r[2].upper() in ("CALL", "買權") else "P"
        out.append({"date": _d(r[0]), "product": f"TXO_{cp}", "who": WHO[r[3]], "net_vol": _n(r[8]), "net_val": _n(r[9]),
                    "oi_long": _n(r[10]), "oi_short": _n(r[12]), "oi_net": _n(r[14]), "oi_net_val": _n(r[15])})
    return out


def parse_pcr(rows):
    return [{"date": _d(r[0]), "put_vol": _n(r[1]), "call_vol": _n(r[2]), "pc_vol": _n(r[3]),
             "put_oi": _n(r[4]), "call_oi": _n(r[5]), "pc_oi": _n(r[6])} for r in rows if len(r) >= 7]


def parse_large(rows):
    """日期, 商品, 商品名稱, 到期月份, 交易人類別(0 全部／1 特定法人), 前五大買, 前五大賣, 前十大買, 前十大賣, 全市場未沖銷。
    只留臺股期貨（TX）：全部月份（999999）與近月（同一天最小的到期月份）。"""
    tx = [r for r in rows if len(r) >= 10 and r[1] == "TX"]
    near = {}
    for r in tx:
        m = r[3].strip()
        if m.isdigit() and m != "999999" and len(m) == 6:
            near[r[0]] = min(near.get(r[0], m), m)
    out = []
    for r in tx:
        m = r[3].strip()
        month = "all" if m == "999999" else "near" if near.get(r[0]) == m else None
        if month is None or r[4] not in ("0", "1"):
            continue
        out.append({"date": _d(r[0]), "month": month, "kind": "all" if r[4] == "0" else "inst",
                    "top5_long": _n(r[5]), "top5_short": _n(r[6]), "top10_long": _n(r[7]), "top10_short": _n(r[8]),
                    "oi": _n(r[9])})
    return out


def parse_tx(rows):
    """交易日期, 契約, 到期月份, 開, 高, 低, 收, 漲跌, 漲跌%, 成交量, 結算價, 未沖銷, …, 交易時段。
    只用一般時段；近月＝當天未平倉的最小月份（排除價差單 202611/202612）。"""
    by = {}
    for r in rows:
        if len(r) < 18 or r[1] != "TX" or "/" in r[2] or r[17] != "一般":
            continue
        by.setdefault(_d(r[0]), []).append(r)
    out = []
    for d, rs in sorted(by.items()):
        rs.sort(key=lambda r: r[2])
        n = rs[0]
        oi_all = sum(int(_n(r[11]) or 0) for r in rs)
        out.append({"date": d, "contract": n[2], "close": _n(n[6]), "change": _n(n[7]), "volume": _n(n[9]),
                    "settle": _n(n[10]), "oi": _n(n[11]), "oi_all": str(oi_all)})
    return out


def upsert(name, rows):
    p = OUT_DIR / f"{name}.csv"
    key = lambda r: tuple(r[k] for k in KEYS[name])  # noqa: E731
    have = {}
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            have = {key(r): r for r in csv.DictReader(fp)}
    have.update({key(r): r for r in rows})
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLS[name])
        w.writeheader()
        w.writerows(have[k] for k in sorted(have))
    return len(rows)


def fetch_range(a, b):
    s, e = f"{a:%Y/%m/%d}", f"{b:%Y/%m/%d}"
    got = {}
    got["inst"] = parse_fut(post_csv("futContractsDateDown", {"queryStartDate": s, "queryEndDate": e, "commodityId": ""}))
    time.sleep(INTERVAL)
    got["inst"] += parse_opt(post_csv("callsAndPutsDateDown", {"queryStartDate": s, "queryEndDate": e, "commodityId": "TXO"}))
    time.sleep(INTERVAL)
    got["pcr"] = parse_pcr(post_csv("pcRatioDown", {"queryStartDate": s, "queryEndDate": e}))
    time.sleep(INTERVAL)
    got["large"] = parse_large(post_csv("largeTraderFutDown", {"queryStartDate": s, "queryEndDate": e}))
    time.sleep(INTERVAL)
    got["tx"] = parse_tx(post_csv("futDataDown", {"down_type": "1", "commodity_id": "TX", "queryStartDate": s, "queryEndDate": e}))
    time.sleep(INTERVAL)
    for k, v in got.items():
        upsert(k, v)
    print(f"{s}~{e}: " + "、".join(f"{k} {len(v)}" for k, v in got.items()))


def months(start, end):
    m = start.replace(day=1)
    while m <= end:
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(m, start), min(nxt - timedelta(days=1), end)
        m = nxt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, help="回補起日")
    a = ap.parse_args()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    start = a.start or (today - timedelta(days=10))
    failed = []
    for s, e in months(start, today):
        try:
            fetch_range(s, e)
        except Exception as ex:  # noqa: BLE001
            print(f"{s}~{e}: 失敗 {ex!r}", file=sys.stderr)
            failed.append(s)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
