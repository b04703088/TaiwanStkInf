#!/usr/bin/env python3
"""處置股、注意股：上市（證交所）＋上櫃（櫃買中心）每日公告。

資料來源（公開頁面、免登入）
  證交所 公布處置有價證券   https://www.twse.com.tw/rwd/zh/announcement/punish?startDate=&endDate=&response=json
  證交所 公布注意有價證券   https://www.twse.com.tw/rwd/zh/announcement/notice?startDate=&endDate=&response=json
  證交所 注意累計次數異常   https://openapi.twse.com.tw/v1/announcement/notetrans （只有當天）
  櫃買 處置有價證券         POST https://www.tpex.org.tw/www/zh-tw/bulletin/disposal
  櫃買 公布注意有價證券     POST https://www.tpex.org.tw/www/zh-tw/bulletin/attention
  櫃買 注意累計次數異常     https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_note （只有當天）

輸出 data/alert/（每次抓的區間會和舊資料合併，同一筆以新的為準）
  disposal.csv   處置：market,ann_date,code,name,start,end,reason,measure,interval,detail
  attention.csv  注意：market,date,code,name,info,clauses,close,pe
  near.csv       注意累計次數異常（再一次就可能處置）：date,market,code,name,situation

用法：python fetch_alert.py [--days 10] [--start 2025-01-01 [--end 2026-10-13]]
"""
import argparse
import csv
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "alert"
TWSE_PUNISH = "https://www.twse.com.tw/rwd/zh/announcement/punish"
TWSE_NOTICE = "https://www.twse.com.tw/rwd/zh/announcement/notice"
TWSE_NEAR = "https://openapi.twse.com.tw/v1/announcement/notetrans"
TPEX_DISPOSAL = "https://www.tpex.org.tw/www/zh-tw/bulletin/disposal"
TPEX_ATTENTION = "https://www.tpex.org.tw/www/zh-tw/bulletin/attention"
TPEX_NEAR = "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_note"
DELAY = 3  # 證交所查太快會被擋
CHUNK = 31  # 每次查詢最多幾天

DISP_COLS = ["market", "ann_date", "code", "name", "start", "end", "reason", "measure", "interval", "detail"]
ATT_COLS = ["market", "date", "code", "name", "info", "clauses", "close", "pe"]
NEAR_COLS = ["date", "market", "code", "name", "situation"]
KEYS = {"disposal": ("market", "code", "ann_date", "start"), "attention": ("market", "code", "date"),
        "near": ("date", "market", "code")}
ORDER = {"disposal": ("ann_date", "market", "code", "start"), "attention": ("date", "market", "code"),
         "near": ("date", "market", "code")}


# ---------------- 解析 ----------------
def iso(s):
    """115/10/07、115.10.07、1151007、115年10月7日、2026/10/07、20261012 → 2026-10-07"""
    s = str(s or "").strip()
    m = re.search(r"(\d{2,4})\s*[/.\-年]\s*(\d{1,2})\s*[/.\-月]\s*(\d{1,2})", s)
    if not m:
        m = re.fullmatch(r"(\d{3,4})(\d{2})(\d{2})", s)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y + 1911 if y < 1911 else y, mo, d).isoformat()
    except ValueError:
        return ""


def period(s):
    """115/10/13～115/10/19、1151013~1151019 → (起, 迄)"""
    parts = [p for p in re.split(r"[～~至]", str(s or "")) if p.strip()]
    return (iso(parts[0]), iso(parts[-1])) if len(parts) >= 2 else (iso(s), "")


def text(s):
    """去掉 HTML 標籤與多餘空白；<br> 換成空白。"""
    s = re.sub(r"<br\s*/?>", " ", str(s or ""), flags=re.I)
    s = re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def clean_name(s):
    """櫃買名稱後面會帶連結：德宏(../../mainboard/...) → 德宏"""
    return re.sub(r"\((?:\.\.?/|https?:)[^)]*\)", "", text(s)).strip()


_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn(s):
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CN.get(a, 1) if a else 1) * 10 + (_CN.get(b, 0) if b else 0)
    return _CN.get(s, 0)


def clauses(info):
    """注意交易資訊裡的「第X款」→ "1;4"（由小到大、不重複）"""
    ks = {_cn(m) for m in re.findall(r"第([一二三四五六七八九十]+)款", info or "")}
    return ";".join(str(k) for k in sorted(ks) if k)


def interval(detail):
    """處置內容的撮合間隔（分鐘）：約每二分鐘／約每25分鐘 → 2／25"""
    m = re.search(r"約每\s*([\d一二三四五六七八九十]+)\s*分鐘", detail or "")
    if not m:
        return ""
    v = m.group(1)
    return str(int(v) if v.isdigit() else _cn(v))


def _num(s):
    s = str(s or "").replace(",", "").strip()
    try:
        float(s)
        return s
    except ValueError:
        return ""


def _idx(fields, *names):
    for i, f in enumerate(fields):
        if any(n in f for n in names):
            return i
    return None


def _get(row, i):
    return row[i] if i is not None and i < len(row) else ""


def parse_disposal(fields, rows, market):
    f = [text(x) for x in fields]
    i_ann, i_code, i_name = _idx(f, "公布日期"), _idx(f, "證券代號"), _idx(f, "證券名稱")
    i_per, i_reason = _idx(f, "起迄", "起訖"), _idx(f, "處置條件", "處置原因")
    i_meas, i_det = _idx(f, "處置措施"), _idx(f, "處置內容")
    out = []
    for r in rows:
        code = text(_get(r, i_code))
        if not code:
            continue
        start, end = period(text(_get(r, i_per)))
        det = text(_get(r, i_det))
        out.append({"market": market, "ann_date": iso(text(_get(r, i_ann))), "code": code,
                    "name": clean_name(_get(r, i_name)), "start": start, "end": end,
                    "reason": text(_get(r, i_reason)), "measure": text(_get(r, i_meas)),
                    "interval": interval(det), "detail": det})
    return out


def parse_attention(fields, rows, market):
    f = [text(x) for x in fields]
    i_code, i_name, i_info = _idx(f, "證券代號"), _idx(f, "證券名稱"), _idx(f, "注意交易資訊")
    i_date, i_close, i_pe = _idx(f, "日期"), _idx(f, "收盤價"), _idx(f, "本益比")
    out = []
    for r in rows:
        code = text(_get(r, i_code))
        if not code:
            continue
        info = text(_get(r, i_info))
        out.append({"market": market, "date": iso(text(_get(r, i_date))), "code": code,
                    "name": clean_name(_get(r, i_name)), "info": info, "clauses": clauses(info),
                    "close": _num(_get(r, i_close)), "pe": _num(_get(r, i_pe))})
    return out


def parse_near_twse(items, fallback_date=""):
    """[{Code, Name, RecentlyMetAttentionSecuritiesCriteria: "115年10月8日至115年10月12日連續二次"}]"""
    out = []
    for it in items or []:
        code, sit = (it.get("Code") or "").strip(), (it.get("RecentlyMetAttentionSecuritiesCriteria") or "").strip()
        if not code:
            continue
        ds = re.findall(r"\d{2,4}年\d{1,2}月\d{1,2}日", sit)
        out.append({"date": iso(ds[-1]) if ds else fallback_date, "market": "上市", "code": code,
                    "name": (it.get("Name") or "").strip(), "situation": sit})
    return out


def parse_near_tpex(items, fallback_date=""):
    """[{Date: "20261012", SecuritiesCompanyCode, CompanyName, AccumulationSituation}]"""
    out = []
    for it in items or []:
        code = (it.get("SecuritiesCompanyCode") or "").strip()
        if not code:
            continue
        out.append({"date": iso(it.get("Date")) or fallback_date, "market": "上櫃", "code": code,
                    "name": (it.get("CompanyName") or "").strip(),
                    "situation": (it.get("AccumulationSituation") or "").strip()})
    return out


# ---------------- 抓取 ----------------
def _twse(url, a, b):
    d = C.http(url, params={"startDate": a.strftime("%Y%m%d"), "endDate": b.strftime("%Y%m%d"), "response": "json"})
    time.sleep(DELAY)
    if not isinstance(d, dict) or d.get("stat") != "OK":
        return [], []
    return d.get("fields") or [], d.get("data") or []


def _tpex(url, a, b):
    d = C.http(url, form={"startDate": a.strftime("%Y/%m/%d"), "endDate": b.strftime("%Y/%m/%d"), "response": "json"})
    time.sleep(1)
    t = (d.get("tables") or [{}])[0] if isinstance(d, dict) else {}
    return t.get("fields") or [], t.get("data") or []


def chunks(a, b, n=CHUNK):
    while a <= b:
        e = min(b, a + timedelta(days=n - 1))
        yield a, e
        a = e + timedelta(days=1)


def fetch(a, b):
    disp, att, errors = [], [], []
    for x, y in chunks(a, b):
        for label, fn, url, parse, market, bucket in (
                ("證交所處置", _twse, TWSE_PUNISH, parse_disposal, "上市", disp),
                ("證交所注意", _twse, TWSE_NOTICE, parse_attention, "上市", att),
                ("櫃買處置", _tpex, TPEX_DISPOSAL, parse_disposal, "上櫃", disp),
                ("櫃買注意", _tpex, TPEX_ATTENTION, parse_attention, "上櫃", att)):
            try:
                rows = parse(*fn(url, x, y), market)
                bucket += rows
                print(f"{label} {x}~{y}: {len(rows)} 筆")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label} {x}~{y}: {e}")
                print(f"!! {label} {x}~{y}: {e}", file=sys.stderr)
    near = []
    today = datetime.now(C.TPE).date().isoformat()
    for label, url, parse in (("證交所注意累計", TWSE_NEAR, parse_near_twse), ("櫃買注意累計", TPEX_NEAR, parse_near_tpex)):
        try:
            rows = parse(C.http(url), today)
            near += rows
            print(f"{label}: {len(rows)} 筆")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
            print(f"!! {label}: {e}", file=sys.stderr)
    return disp, att, near, errors


# ---------------- 存檔 ----------------
def read_csv(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def merge(old, new, key):
    """同一 key 以新抓的為準。"""
    m = {tuple(r.get(k, "") for k in key): r for r in old}
    for r in new:
        if all(r.get(k) for k in key):
            m[tuple(r[k] for k in key)] = r
    return list(m.values())


def write_csv(p, cols, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def save(out, disp, att, near):
    for name, cols, rows in (("disposal", DISP_COLS, disp), ("attention", ATT_COLS, att), ("near", NEAR_COLS, near)):
        p = out / f"{name}.csv"
        merged = merge(read_csv(p), rows, KEYS[name])
        merged.sort(key=lambda r: tuple(r.get(k, "") for k in ORDER[name]))
        write_csv(p, cols, merged)
        print(f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}: {len(merged)} 筆")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10, help="抓最近幾天（預設 10）")
    ap.add_argument("--start", help="回補起日 YYYY-MM-DD")
    ap.add_argument("--end", help="回補迄日 YYYY-MM-DD（預設今天）")
    a = ap.parse_args()
    today = datetime.now(C.TPE).date()
    end = date.fromisoformat(a.end) if a.end else today
    start = date.fromisoformat(a.start) if a.start else end - timedelta(days=a.days)
    disp, att, near, errors = fetch(start, end)
    save(OUT, disp, att, near)
    if errors and not (disp or att):
        sys.exit(1)


if __name__ == "__main__":
    main()
