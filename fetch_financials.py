#!/usr/bin/env python3
"""財報資料：上市櫃公司每月營收、每季損益表與資產負債表重點項目（公開資訊觀測站）。

資料來源（公開、免登入；觀測站舊版網址 mopsov，GitHub 主機連得到）
  月營收  https://mopsov.twse.com.tw/nas/t21/<sii|otc>/t21sc03_<民國年>_<月>_<0|1>.html
          靜態彙總表（Big5），_0 國內公司、_1 外國公司（KY）；依產業別分表，單位千元。102 年起都有。
  季報    https://mopsov.twse.com.tw/mops/web/ajax_t163sb04（綜合損益表彙總）
          https://mopsov.twse.com.tw/mops/web/ajax_t163sb05（資產負債表彙總）
          POST TYPEK=sii/otc、year=民國年、season=01..04；回傳 HTML，依行業格式分成多張表
          （一般業、銀行、金控、證券、保險、異業），欄位名稱各不相同，這裡統一成固定欄位。
          損益表是「當年度累計到該季」的金額，單季數字用前一季相減（q_ 開頭的欄位）。
          一次查詢要 1～2 分鐘（整個市場一次回來），所以每季只在申報期間重抓。

輸出 data/financials/（金額單位：新台幣千元；EPS、每股淨值單位：元）
  revenue/<YYYYMM>.csv     ym, market, code, name, industry, revenue, prev_month, last_year, mom_pct, yoy_pct,
                           cum, cum_last_year, cum_yoy_pct, note
  quarterly/<YYYY>Q<n>.csv year, season, market, code, name, type,
                           （累計）revenue, gross_profit, operating_income, pretax_income, net_income,
                                   net_income_parent, eps,
                           （單季）q_revenue, q_gross_profit, q_operating_income, q_pretax_income, q_net_income,
                                   q_net_income_parent, q_eps,
                           （季底）current_assets, total_assets, current_liabilities, total_liabilities, capital,
                                   retained_earnings, equity_parent, equity, bvps
  sources.json             最近一次執行的摘要與錯誤

  type：一般、銀行、金控、證券、保險、其他（觀測站依行業用不同格式）。
  銀行業沒有「營業收入」，revenue 用淨收益（利息淨收益＋利息以外淨損益）；金控、證券、其他用各自的收入合計；
  保險業 2026 年起適用 IFRS 17（只有保險服務結果、財務結果），revenue 空白。
  沒有子公司的公司不分歸屬，net_income_parent、equity_parent 直接等於全部。

重抓規則
  月營收：最近 2 個月每次重抓（10 日前陸續公布、會更正），更早的月份沒檔案才抓。
  季報：該季結束到申報期限後半個月（Q1 4/1～6/15、Q2 7/1～9/15、Q3 10/1～12/15、Q4 隔年 1/1～4/15）每次重抓，
        之後沒檔案才抓。抓完會順便重算下一季的單季數字。
  回補：--since 起（預設 2019-01）沒有檔案的月份／季別，在 --max-minutes 時間內由新到舊補，下次接續。

用法
  python fetch_financials.py                          # 例行（排程用）
  python fetch_financials.py --since 2013-01 --max-minutes 50
  python fetch_financials.py --revenue 2026-09        # 只抓某月營收
  python fetch_financials.py --quarter 2026Q2         # 只抓某季財報
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
from datetime import date, datetime
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "financials"
REV_URL = "https://mopsov.twse.com.tw/nas/t21/{mkt}/t21sc03_{roc}_{m}_{foreign}.html"
FIN_URL = "https://mopsov.twse.com.tw/mops/web/{api}"
MARKETS = {"sii": "上市", "otc": "上櫃"}
DELAY = 3

REV_COLS = ["ym", "market", "code", "name", "industry", "revenue", "prev_month", "last_year", "mom_pct", "yoy_pct",
            "cum", "cum_last_year", "cum_yoy_pct", "note"]
FLOW = ["revenue", "gross_profit", "operating_income", "pretax_income", "net_income", "net_income_parent", "eps"]
STOCK = ["current_assets", "total_assets", "current_liabilities", "total_liabilities", "capital",
         "retained_earnings", "equity_parent", "equity", "bvps"]
Q_COLS = ["year", "season", "market", "code", "name", "type"] + FLOW + ["q_" + k for k in FLOW] + STOCK

# 標準欄位 ← 觀測站欄位名稱（依序找第一個有的）；名稱比對前會去掉空白、統一全形括號與破折號
IS_MAP = {
    "revenue": ["營業收入", "淨收益", "收益", "收入"],
    "gross_profit": ["營業毛利（毛損）淨額", "營業毛利（毛損）"],
    "operating_income": ["營業利益（損失）", "營業利益"],
    "pretax_income": ["稅前淨利（淨損）", "繼續營業單位稅前淨利（淨損）", "繼續營業單位稅前損益",
                      "繼續營業單位稅前純益（純損）"],
    "net_income": ["本期淨利（淨損）", "本期稅後淨利（淨損）"],
    "net_income_parent": ["淨利（淨損）歸屬於母公司業主", "淨利（損）歸屬於母公司業主"],
    "eps": ["基本每股盈餘（元）", "基本每股盈餘"],
}
BS_MAP = {
    "current_assets": ["流動資產"],
    "total_assets": ["資產總計", "資產總額", "資產合計"],
    "current_liabilities": ["流動負債"],
    "total_liabilities": ["負債總計", "負債總額", "負債合計"],
    "capital": ["股本"],
    "retained_earnings": ["保留盈餘", "保留盈餘（或累積虧損）"],
    "equity_parent": ["歸屬於母公司業主之權益合計", "歸屬於母公司業主權益合計", "歸屬於母公司業主之權益"],
    "equity": ["權益總計", "權益總額", "權益合計"],
    "bvps": ["每股參考淨值"],
}


# ---------------- 共用 ----------------
def _post(url, form, timeout=240, retries=3):
    """觀測站彙總表一次回整個市場，要 1～2 分鐘；etf_common.http 的 30 秒逾時不夠，這裡自己送。"""
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": C.UA, "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://mopsov.twse.com.tw/mops/web/t163sb04"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise C.AdapterError(f"{url} {form.get('TYPEK')} {form.get('year')}Q{form.get('season')}: {e!r}") from e
            time.sleep(15 * (attempt + 1))


def _cells(row):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]


def _num(s):
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").replace(",", "").strip()
    if s in ("", "-", "--", "---", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(round(v, 4))
    return str(v)


def _norm(name):
    s = re.sub(r"\s+", "", name or "")
    return s.replace("(", "（").replace(")", "）").replace("─", "－").replace("-", "－")


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in cols})


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


# ---------------- 月營收 ----------------
def parse_revenue(text, ym, market):
    """月營收彙總表 HTML → rows。表格依「產業別：xxx」分段，合計列（th）略過。"""
    rows = []
    parts = re.split(r"產業別：", text)
    for part in parts[1:]:
        industry = re.match(r"\s*([^<\s]*)", part).group(1)
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", part, re.S | re.I):
            c = _cells(tr)
            if len(c) < 10 or not re.match(r"^[0-9A-Z]{4,6}$", c[0]):
                continue
            rows.append({
                "ym": ym, "market": market, "code": c[0], "name": c[1], "industry": industry,
                "revenue": _num(c[2]), "prev_month": _num(c[3]), "last_year": _num(c[4]),
                "mom_pct": _num(c[5]), "yoy_pct": _num(c[6]), "cum": _num(c[7]), "cum_last_year": _num(c[8]),
                "cum_yoy_pct": _num(c[9]), "note": "" if len(c) < 11 or c[10] in ("-", "") else c[10],
            })
    return rows


def fetch_revenue(y, m):
    """某年某月上市＋上櫃（國內、外國公司）月營收。"""
    ym = f"{y}{m:02d}"
    out, errors = [], []
    for mkt, label in MARKETS.items():
        for foreign in (0, 1):
            url = REV_URL.format(mkt=mkt, roc=y - 1911, m=m, foreign=foreign)
            try:
                b = C.http(url, raw=True, retries=3)
            except C.AdapterError as e:
                errors.append(f"月營收 {ym} {label}{'外國' if foreign else ''}：{e}")
                continue
            text = b.decode("cp950", errors="replace")
            rows = parse_revenue(text, ym, label)
            if not rows and "產業別" in text:
                errors.append(f"月營收 {ym} {label}{'外國' if foreign else ''}：有表格但解析不到資料（格式可能改了）")
            out += rows
            time.sleep(DELAY)
    seen, uniq = set(), []
    for r in out:
        if r["code"] not in seen:
            seen.add(r["code"])
            uniq.append(r)
    uniq.sort(key=lambda r: (r["market"] != "上市", r["code"]))
    return uniq, errors


# ---------------- 季報 ----------------
def fin_type(head):
    h = set(head)
    if "利息淨收益" in h:
        return "金控" if "淨收益" in h else "銀行"
    if "保險服務結果" in h:  # 2026 年起保險業適用 IFRS 17，沒有營業收入
        return "保險"
    if "收益" in h and "支出及費用" in h:
        return "證券"
    if "營業收入" in h and ("營業毛利（毛損）" in h or "營業毛利（毛損）淨額" in h):
        return "一般"
    if "營業收入" in h and "營業成本" in h:
        return "保險"
    return "其他"


def parse_fin(text, mapping):
    """彙總表 HTML → {code: {name, type, 標準欄位...}}。每種行業格式一張表，各自依表頭對應欄位。"""
    out = {}
    for tb in re.findall(r"<table class='hasBorder'[^>]*>(.*?)</table>", text, re.S):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S)
        if not rows:
            continue
        head = [_norm(h) for h in _cells(rows[0])]
        if not head or head[0] != "公司代號":
            continue
        ftype = fin_type(head)
        idx = {}
        for key, names in mapping.items():
            for n in names:
                if _norm(n) in head:
                    idx[key] = head.index(_norm(n))
                    break
        bank = "利息淨收益" in head and "淨收益" not in head
        for tr in rows[1:]:
            c = _cells(tr)
            if len(c) < 2 or not re.match(r"^[0-9A-Z]{4,6}$", c[0]):
                continue
            r = {"code": c[0], "name": c[1], "type": ftype}
            for key, i in idx.items():
                r[key] = _num(c[i]) if i < len(c) else None
            if bank and "revenue" in mapping:  # 銀行：淨收益 = 利息淨收益 + 利息以外淨損益
                a = _num(c[head.index("利息淨收益")])
                j = next((head.index(n) for n in ("利息以外淨損益", "利息以外淨收益") if n in head), None)
                b = _num(c[j]) if j is not None else None
                r["revenue"] = None if a is None and b is None else (a or 0) + (b or 0)
            out[c[0]] = r
    return out


def _fin_page(api, typek, y, s):
    text = _post(FIN_URL.format(api=api), {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "isQuery": "Y",
                                           "TYPEK": typek, "year": str(y - 1911), "season": f"{s:02d}"})
    if "hasBorder" not in text:
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
        if re.search(r"查無|無資料|不存在|尚未", plain):
            return None  # 還沒有公司申報
        raise C.AdapterError(f"{api} {typek} {y}Q{s} 回應看不懂：{plain.strip()[:120]}")
    return text


def fill_parent(r):
    """沒有子公司的公司（個體報表）不分母公司／非控制權益，兩個欄位都是 --：歸屬母公司 = 全部。"""
    if r.get("net_income_parent") is None and r.get("equity_parent") is None:
        r["net_income_parent"] = r.get("net_income")
        r["equity_parent"] = r.get("equity")
    return r


def fetch_quarter(y, s):
    """某季上市＋上櫃損益表（累計）與資產負債表 → rows（未含單季欄位）。"""
    rows, errors = [], []
    for typek, label in MARKETS.items():
        try:
            is_html = _fin_page("ajax_t163sb04", typek, y, s)
            time.sleep(DELAY)
            bs_html = _fin_page("ajax_t163sb05", typek, y, s)
            time.sleep(DELAY)
        except C.AdapterError as e:
            errors.append(f"財報 {y}Q{s} {label}：{e}")
            continue
        inc = parse_fin(is_html, IS_MAP) if is_html else {}
        bal = parse_fin(bs_html, BS_MAP) if bs_html else {}
        if (is_html and not inc) or (bs_html and not bal):
            errors.append(f"財報 {y}Q{s} {label}：有表格但解析不到資料（格式可能改了）")
        for code in sorted(set(inc) | set(bal)):
            r = {"year": y, "season": s, "market": label}
            r.update(bal.get(code, {}))
            r.update(inc.get(code, {}))
            rows.append(fill_parent(r))
    rows.sort(key=lambda r: (r["market"] != "上市", r["code"]))
    return rows, errors


def add_quarterly(rows, prev_rows):
    """累計 → 單季：Q1 就是累計；其他季 = 本季累計 - 前一季累計（前一季沒有資料就留空）。"""
    prev = {r["code"]: r for r in prev_rows}
    for r in rows:
        p = prev.get(r["code"])
        for k in FLOW:
            v = r.get(k)
            if int(r["season"]) == 1:
                q = v
            else:
                pv = _num(p.get(k)) if p else None
                q = None if v is None or pv is None else v - pv
            r["q_" + k] = None if q is None else round(q, 2 if k == "eps" else 0)
    return rows


def qpath(y, s):
    return OUT / "quarterly" / f"{y}Q{s}.csv"


def prev_q(y, s):
    return (y, s - 1) if s > 1 else (y - 1, 4)


def next_q(y, s):
    return (y, s + 1) if s < 4 else (y + 1, 1)


def save_quarter(y, s, rows):
    prev = _read(qpath(*prev_q(y, s))) if s > 1 else []
    _write(qpath(y, s), Q_COLS, add_quarterly(rows, prev))
    ny, ns = next_q(y, s)
    if ns > 1 and qpath(ny, ns).exists():  # 下一季的單季數字跟著重算
        nxt = _read(qpath(ny, ns))
        for r in nxt:
            for k in FLOW:
                r[k] = _num(r.get(k))
        _write(qpath(ny, ns), Q_COLS, add_quarterly(nxt, _read(qpath(y, s))))


# ---------------- 排程規則 ----------------
WINDOWS = {1: ((4, 1), (6, 15)), 2: ((7, 1), (9, 15)), 3: ((10, 1), (12, 15)), 4: ((1, 1), (4, 15))}


def quarter_active(y, s, today):
    """該季是否還在申報期間（結束後到申報期限後半個月）。Q4 的期間在隔年。"""
    (m1, d1), (m2, d2) = WINDOWS[s]
    yy = y + 1 if s == 4 else y
    return date(yy, m1, d1) <= today <= date(yy, m2, d2)


def quarter_ended(y, s, today):
    yy, mm = (y + 1, 1) if s == 4 else (y, s * 3 + 1)
    return today >= date(yy, mm, 1)


def plan_quarters(today, since):
    """回傳 (每次重抓的季, 沒檔案才抓的季)，都由新到舊。"""
    y, s = today.year, (today.month - 1) // 3 + 1
    seq = []
    while (y, s) >= since:
        if quarter_ended(y, s, today):
            seq.append((y, s))
        y, s = prev_q(y, s)
    active = [q for q in seq if quarter_active(*q, today)]
    missing = [q for q in seq if q not in active and not qpath(*q).exists()]
    return active, missing


def plan_months(today, since):
    y, m = today.year, today.month
    seq = []
    while (y, m) >= since:
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        if (y, m) >= since:
            seq.append((y, m))
    recent = seq[:2]
    missing = [ym for ym in seq[2:] if not (OUT / "revenue" / f"{ym[0]}{ym[1]:02d}.csv").exists()]
    return recent, missing


# ---------------- 主程式 ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2019-01", help="回補起點 YYYY-MM（月營收從該月、季報從該月所在的季）")
    ap.add_argument("--max-minutes", type=float, default=30, help="回補時間上限（分鐘）；例行重抓不受限")
    ap.add_argument("--revenue", help="只抓某月營收 YYYY-MM")
    ap.add_argument("--quarter", help="只抓某季財報 YYYYQn")
    ap.add_argument("--skip-revenue", action="store_true")
    ap.add_argument("--skip-quarterly", action="store_true")
    a = ap.parse_args(argv)
    today = datetime.now(C.TPE).date()
    t0 = time.time()
    errors, log = [], {"revenue": [], "quarterly": []}

    def do_month(y, m):
        rows, errs = fetch_revenue(y, m)
        errors.extend(errs)
        if rows:
            _write(OUT / "revenue" / f"{y}{m:02d}.csv", REV_COLS, rows)
        log["revenue"].append(f"{y}{m:02d}:{len(rows)}")
        print(f"月營收 {y}-{m:02d}：{len(rows)} 家")

    def do_quarter(y, s):
        rows, errs = fetch_quarter(y, s)
        errors.extend(errs)
        if rows:
            save_quarter(y, s, rows)
        log["quarterly"].append(f"{y}Q{s}:{len(rows)}")
        print(f"財報 {y}Q{s}：{len(rows)} 家（{time.time() - t0:.0f} 秒）")

    if a.revenue or a.quarter:
        if a.revenue:
            y, m = map(int, a.revenue.split("-"))
            do_month(y, m)
        if a.quarter:
            y, s = map(int, a.quarter.upper().split("Q"))
            do_quarter(y, s)
    else:
        sy, sm = map(int, a.since.split("-"))
        budget = a.max_minutes * 60
        if not a.skip_revenue:
            recent, missing = plan_months(today, (sy, sm))
            for ym in recent:
                do_month(*ym)
            for ym in missing:
                if time.time() - t0 > budget:
                    break
                do_month(*ym)
        if not a.skip_quarterly:
            active, missing = plan_quarters(today, (sy, (sm - 1) // 3 + 1))
            for q in active:
                do_quarter(*q)
            for q in missing:
                if time.time() - t0 > budget:
                    break
                do_quarter(*q)
            left = [f"{y}Q{s}" for y, s in plan_quarters(today, (sy, (sm - 1) // 3 + 1))[1]]
            log["quarterly_left"] = len(left)
            if left:
                print(f"季報還有 {len(left)} 季未回補（下次接續）")

    log.update({"generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "errors": errors})
    (OUT / "sources.json").parent.mkdir(parents=True, exist_ok=True)
    (OUT / "sources.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in errors:
        print("錯誤：" + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
