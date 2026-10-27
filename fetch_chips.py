#!/usr/bin/env python3
"""每日籌碼：三大法人買賣超、借券賣出、現股當沖（上市＋上櫃），存成一天一個 CSV。

資料來源（證交所／櫃買中心，公開免登入）
  三大法人  上市 https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json
           上櫃 https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date=YYYY/MM/DD&response=json
  借券賣出  上市 https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date=YYYYMMDD&response=json
           上櫃 https://www.tpex.org.tw/www/zh-tw/margin/sbl?date=YYYY/MM/DD&response=json
           （信用額度總量管制餘額表：前 8 欄是融券，後 6 欄是借券賣出：前日餘額、賣出、還券、調整、餘額、次一營業日限額）
  現股當沖  上市 https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date=YYYYMMDD&selectType=All&response=json
           上櫃 https://www.tpex.org.tw/www/zh-tw/intraday/stat?type=Daily&date=YYYY/MM/DD&response=json
           當沖股數、買進金額、賣出金額。交易所 T+2 日才定案，所以最近幾天每次重抓（--refresh）。

輸出 data/chips/<YYYY>/<YYYYMMDD>.csv（單位：股；金額：元）
  date, market, code, name,
  f_net     外資及陸資（不含外資自營商）買賣超
  fd_net    外資自營商買賣超
  t_net     投信買賣超
  d_net     自營商買賣超（自行買賣＋避險）
  inst_net  三大法人合計買賣超
  sbl_sell, sbl_ret, sbl_bal   借券賣出：當日賣出、當日還券、當日餘額
  dt_vol, dt_buy, dt_sell      現股當沖：成交股數、買進金額、賣出金額
  沒有資料的欄位留空（例如不能借券賣出、不能當沖的股票）。

用法:
    python fetch_chips.py                       # 抓今天（台北時間）
    python fetch_chips.py --start 2025-10-01    # 回補區間（已抓過的日期跳過）
    python fetch_chips.py --start 2026-10-20 --refresh 4   # 4 天內的日期一律重抓（當沖 T+2 才定案）
非交易日沿用 data/no_trading_days.txt（與 fetch_daily.py 共用）。
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timedelta

from fetch_daily import (DATA_DIR, REQUEST_INTERVAL, TPE, http_get_json, is_warrant, load_holidays,
                         parse_date, save_holidays, to_number)

CHIPS_DIR = DATA_DIR / "chips"
COLUMNS = ["date", "market", "code", "name", "f_net", "fd_net", "t_net", "d_net", "inst_net",
           "sbl_sell", "sbl_ret", "sbl_bal", "dt_vol", "dt_buy", "dt_sell"]

T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={d:%Y%m%d}&selectType=ALLBUT0999&response=json"
TPEX_INST_URL = ("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW"
                 "&date={d:%Y}/{d:%m}/{d:%d}&response=json")
TWT93U_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={d:%Y%m%d}&response=json"
TPEX_SBL_URL = "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date={d:%Y}/{d:%m}/{d:%d}&response=json"
TWTB4U_URL = "https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U?date={d:%Y%m%d}&selectType=All&response=json"
TPEX_DT_URL = "https://www.tpex.org.tw/www/zh-tw/intraday/stat?type=Daily&date={d:%Y}/{d:%m}/{d:%d}&response=json"


def _int(s):
    v = to_number(s)
    return str(int(float(v))) if v != "" else ""


def _tables(payload):
    """證交所新版 API 有時直接放 fields/data，有時包在 tables 裡；統一回傳 [(fields, data)]。"""
    if not payload:
        return []
    out = []
    if payload.get("data") and payload.get("fields"):
        out.append((payload["fields"], payload["data"]))
    for t in payload.get("tables") or []:
        if isinstance(t, dict) and t.get("data") and t.get("fields"):
            out.append((t["fields"], t["data"]))
    return out


def _check_inst(rows, label):
    """外資＋投信＋自營商要等於三大法人合計；對不起來代表欄位位置變了，寧可失敗也不要存錯資料。"""
    bad = [r for r in rows if r["inst_net"] != "" and all(r[k] != "" for k in ("f_net", "fd_net", "t_net", "d_net"))
           and int(r["f_net"]) + int(r["fd_net"]) + int(r["t_net"]) + int(r["d_net"]) != int(r["inst_net"])]
    if rows and len(bad) > len(rows) * 0.05:
        raise RuntimeError(f"{label} 三大法人欄位加總對不起來（{len(bad)}/{len(rows)} 筆），請檢查欄位")


def parse_t86(payload):
    """T86 19 欄：代號、名稱、外資(不含外資自營商)買/賣/超、外資自營商買/賣/超、投信買/賣/超、
    自營商買賣超、自營商(自行)買/賣/超、自營商(避險)買/賣/超、三大法人買賣超。"""
    out = {}
    for fields, data in _tables(payload):
        if len(fields) < 19:
            continue
        for r in data:
            code = r[0].strip()
            out[code] = {"name": r[1].strip(), "f_net": _int(r[4]), "fd_net": _int(r[7]), "t_net": _int(r[10]),
                         "d_net": _int(r[11]), "inst_net": _int(r[18])}
    _check_inst(list(out.values()), "上市")
    return out


def parse_tpex_inst(payload):
    """櫃買 24 欄：代號、名稱、外資(不含外資自營商)買/賣/超、外資自營商買/賣/超、外資及陸資合計買/賣/超、
    投信買/賣/超、自營商(自行)買/賣/超、自營商(避險)買/賣/超、自營商合計買/賣/超、三大法人買賣超。"""
    out = {}
    for fields, data in _tables(payload):
        if len(fields) < 24:
            continue
        for r in data:
            code = r[0].strip()
            if is_warrant(code):
                continue
            out[code] = {"name": r[1].strip(), "f_net": _int(r[4]), "fd_net": _int(r[7]), "t_net": _int(r[13]),
                         "d_net": _int(r[22]), "inst_net": _int(r[23])}
    _check_inst(list(out.values()), "上櫃")
    return out


def parse_sbl(payload):
    """信用額度總量管制餘額表：代號、名稱、融券 6 欄、借券賣出 6 欄（前日餘額、賣出、還券、調整、餘額、限額）、備註。
    前日＋賣出－還券＋調整＝餘額；個別股票偶爾對不起來（停止借券、下市歸零），超過 5% 對不起來才當成欄位變了。"""
    out, bad = {}, 0
    for fields, data in _tables(payload):
        if len(fields) < 14:
            continue
        for r in data:
            code = r[0].strip()
            if not code:
                continue  # 合計列
            prev, sell, ret, adj, bal = (_int(x) for x in r[8:13])
            if "" not in (prev, sell, ret, bal) and int(prev) + int(sell) - int(ret) + int(adj or 0) != int(bal):
                bad += 1
            out[code] = {"name": r[1].strip(), "sbl_sell": sell, "sbl_ret": ret, "sbl_bal": bal}
    if out and bad > len(out) * 0.05:
        raise RuntimeError(f"借券賣出餘額對不起來（{bad}/{len(out)} 筆），請檢查欄位")
    return out


def parse_daytrade(payload):
    """當沖標的及成交量值：代號、名稱、暫停註記、當沖成交股數、買進金額、賣出金額（統計表只有 1 列，略過）。"""
    out = {}
    for fields, data in _tables(payload):
        if len(fields) < 6 or "代號" not in "".join(fields[:1]):
            continue
        for r in data:
            code = r[0].strip()
            out[code] = {"name": r[1].strip(), "dt_vol": _int(r[3]), "dt_buy": _int(r[4]), "dt_sell": _int(r[5])}
    return out


def merge(d, market, *parts):
    rows = {}
    for p in parts:
        for code, v in p.items():
            r = rows.setdefault(code, {"date": d.isoformat(), "market": market, "code": code, "name": v["name"]})
            r.update({k: x for k, x in v.items() if k != "name"})
    return [{c: rows[k].get(c, "") for c in COLUMNS} for k in sorted(rows)]


def output_path(d):
    return CHIPS_DIR / f"{d:%Y}" / f"{d:%Y%m%d}.csv"


SKIPPED, FETCHED, NO_DATA = "skipped", "fetched", "no_data"


def fetch_day(d, force=False, holidays=frozenset()):
    if not force and (output_path(d).exists() or d.weekday() >= 5 or d in holidays):
        return SKIPPED
    if d.weekday() >= 5:
        return SKIPPED
    got = {}
    for key, url, parse in [("t86", T86_URL, parse_t86), ("tpi", TPEX_INST_URL, parse_tpex_inst),
                            ("sbl", TWT93U_URL, parse_sbl), ("tps", TPEX_SBL_URL, parse_sbl),
                            ("dt", TWTB4U_URL, parse_daytrade), ("tpd", TPEX_DT_URL, parse_daytrade)]:
        got[key] = parse(http_get_json(url.format(d=d)))
        time.sleep(REQUEST_INTERVAL)
        if key == "t86" and not got[key]:
            print(f"{d}: 無資料（非交易日或尚未公布）")
            return NO_DATA
    if not got["tpi"]:
        raise RuntimeError("上市有三大法人資料但上櫃沒有，稍後重試")
    rows = merge(d, "TWSE", got["t86"], got["sbl"], got["dt"]) + merge(d, "TPEx", got["tpi"], got["tps"], got["tpd"])
    out = output_path(d)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{d}: 法人 上市 {len(got['t86'])}／上櫃 {len(got['tpi'])}、借券 {len(got['sbl'])}／{len(got['tps'])}、"
          f"當沖 {len(got['dt'])}／{len(got['tpd'])}")
    return FETCHED


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=parse_date, help="單日 YYYY-MM-DD")
    ap.add_argument("--start", type=parse_date, help="回補起日")
    ap.add_argument("--end", type=parse_date, help="回補迄日（預設今天）")
    ap.add_argument("--force", action="store_true", help="覆寫已存在的檔案")
    ap.add_argument("--refresh", type=int, default=0, help="今天往前幾天內的日期一律重抓（當沖數字 T+2 才定案）")
    ap.add_argument("--max-minutes", type=float, default=0, help="最多執行幾分鐘（0 = 不限）")
    args = ap.parse_args()

    today = datetime.now(TPE).date()
    if args.start:
        days, d, end = [], args.start, args.end or today
        while d <= end:
            days.append(d)
            d += timedelta(days=1)
    else:
        days = [args.date or today]

    holidays = load_holidays()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    failed, counts = [], {SKIPPED: 0, FETCHED: 0, NO_DATA: 0}
    for d in days:
        if deadline and time.monotonic() > deadline:
            print(f"已達 {args.max_minutes:g} 分鐘上限，停在 {d}；重跑會接著抓")
            break
        force = args.force or (args.refresh and (today - d).days < args.refresh)
        try:
            result = fetch_day(d, force, holidays)
        except Exception as e:  # noqa: BLE001  單日失敗不中斷整個回補
            print(f"{d}: 失敗 {e!r}", file=sys.stderr)
            failed.append(d)
            time.sleep(REQUEST_INTERVAL)
            continue
        counts[result] += 1
        if result == NO_DATA and d < today and d not in holidays:
            holidays.add(d)
            save_holidays(holidays)

    print(f"完成：新抓 {counts[FETCHED]} 天、跳過 {counts[SKIPPED]} 天、新發現非交易日 {counts[NO_DATA]} 天、失敗 {len(failed)} 天")
    if failed:
        print(f"失敗: {', '.join(map(str, failed))}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
