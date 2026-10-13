#!/usr/bin/env python3
"""庫藏股（公司買回自家股份）：每一次董事會決議的買回計畫、執行進度與結果。

資料來源（公開資訊觀測站舊版頁面，公開、免登入）
  1. 庫藏股統計彙總表 t35sc09 https://mopsov.twse.com.tw/mops/web/t35sc09
     依董事會決議日查詢（上市、上櫃各一次）：決議日、買回目的、總金額上限、預定買回股數、
     價格區間、預定買回期間、是否執行完畢；執行完畢後才有實際買回股數、金額、均價、佔股本比例。
  2. 個股「買回達一定標準」申報 t35sb01（每買回達已發行股數 2% 或金額 3 億元要申報一次）
     只抓還在買回期間內的計畫，當作執行中的進度（實際買到的可能更多）。

輸出 data/treasury/
  programs.csv   每次買回計畫一列（見 PROG_COLS）；每次重抓查詢區間內的資料，舊資料保留
  progress.csv   執行中計畫的達標申報（見 PROGRESS_COLS）

用法：python fetch_treasury.py [--since 2024-01-01]   （預設：前年 1 月 1 日起）
"""
import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "treasury"
BASE = "https://mopsov.twse.com.tw/mops/web/"
MARKETS = {"sii": "上市", "otc": "上櫃"}
DELAY = 1.0
PURPOSE = {"1": "轉讓員工", "2": "股權轉換", "3": "維護信用及股東權益"}

PROG_COLS = ["market", "code", "name", "board_date", "purpose", "cap_amount", "plan_shares", "price_lo", "price_hi",
             "start", "end", "done", "bought_shares", "cancelled_shares", "exec_pct", "bought_amount", "avg_price",
             "issued_pct", "reason"]
PROGRESS_COLS = ["market", "code", "board_date", "seq", "report_date", "buy_date", "shares", "amount", "avg_price",
                 "held_shares", "held_pct", "note"]
KEY = ("market", "code", "board_date", "start")


# ---------------- 小工具 ----------------
def roc_date(s):
    """115/08/05、1150805 → 2026-08-05；其他 → ''"""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s) or re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", s)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y + 1911, mo, d).isoformat()
    except ValueError:
        return ""


def roc_param(d):
    """date → 1150805（查詢參數用）"""
    return f"{d.year - 1911:03d}{d.month:02d}{d.day:02d}"


def _num(s, as_int=False):
    s = re.sub(r"[,%\s]|&nbsp;", "", s or "")
    if not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return ""
    return str(int(float(s))) if as_int else s


def cells(tr):
    """<tr>…</tr> → 每格純文字（td 常沒有關閉標籤，用下一個 <td 或 </tr> 切）"""
    out = []
    for c in re.findall(r"<td[^>]*>(.*?)(?=<td|</tr>)", tr, re.S | re.I):
        t = re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ")
        out.append(re.sub(r"\s+", " ", t).strip())
    return out


def rows_of(html):
    return re.findall(r"<tr\s+class=\s*['\"](?:even|odd)['\"][^>]*>.*?</tr>", html, re.S | re.I)


def post(api, form, timeout=180, retries=3):
    """舊版觀測站要等整張表產生才回應，查得多時要好幾十秒；urllib 的 timeout 是每次讀取的等待上限。"""
    req = urllib.request.Request(BASE + api, data=urllib.parse.urlencode(form).encode(),
                                 headers={"User-Agent": C.UA, "Content-Type": "application/x-www-form-urlencoded",
                                          "Referer": BASE + api.replace("ajax_", "")})
    for attempt in range(retries):
        try:
            with C._opener.open(req, timeout=timeout) as r:
                html = r.read().decode("utf-8", "replace")
            if "安全性考量" in html or "THIS PAGE CAN NOT BE ACCESSED" in html:
                raise C.AdapterError(f"{api} 被擋（安全性考量）")
            return html
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise C.AdapterError(f"{api} {form.get('TYPEK')} {form.get('co_id', '')}: {e!r}") from e
            time.sleep(10 * (attempt + 1))


# ---------------- 庫藏股統計彙總表 ----------------
def parse_programs(html, market):
    """t35sc09 結果 → [program]。跳過每家公司的「累計」列。

    欄位順序：序號、代號、名稱、決議日、目的、金額上限、預定股數、價格低、價格高、期間起、期間迄、
    是否執行完畢、（達一定標準 查詢按鈕）、已買回股數、已註銷或轉讓股數、佔預定比例、已買回金額、
    平均價、佔已發行比例、未執行完畢原因"""
    out = []
    for tr in rows_of(html):
        c = cells(tr)
        if len(c) < 19 or c[0].startswith("累計") or not re.fullmatch(r"\d{4,6}[A-Z]?", c[1]):
            continue
        board = roc_date(c[3])
        if not board:
            continue
        c += [""] * (20 - len(c))
        out.append({
            "market": market, "code": c[1], "name": c[2], "board_date": board,
            "purpose": ",".join(re.findall(r"[123]", c[4])),
            "cap_amount": _num(c[5], True), "plan_shares": _num(c[6], True),
            "price_lo": _num(c[7]), "price_hi": _num(c[8]),
            "start": roc_date(c[9]), "end": roc_date(c[10]), "done": c[11].strip().upper()[:1],
            "bought_shares": _num(c[13], True), "cancelled_shares": _num(c[14], True), "exec_pct": _num(c[15]),
            "bought_amount": _num(c[16], True), "avg_price": _num(c[17]), "issued_pct": _num(c[18]),
            "reason": "" if c[19] in ("無", "-", "----") else c[19][:200],
        })
    return out


def fetch_programs(market, since, until):
    html = post("ajax_t35sc09", {"encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1, "TYPEK": market,
                                 "d1": roc_param(since), "d2": roc_param(until), "RD": "1"})
    if "hasBorder" not in html:
        msg = re.sub(r"<[^>]+>|\s+", " ", html)
        raise C.AdapterError(f"t35sc09 {market} 沒有表格：{msg.strip()[:120]}")
    return parse_programs(html, market)


def merge(old, new):
    """以 (市場, 代號, 決議日, 期間起) 合併；新抓到的覆蓋舊的。"""
    m = {tuple(r[k] for k in KEY): r for r in old}
    for r in new:
        m[tuple(r[k] for k in KEY)] = r
    return sorted(m.values(), key=lambda r: (r["board_date"], r["code"], r["start"]), reverse=True)


# ---------------- 買回達一定標準（執行中進度） ----------------
def parse_progress(html, market, code, board_date):
    """t35sb01 → [progress]。欄位：第X次、申報日期、迄今買回情形、買回日期、股數、金額、均價、累積持有、比例、其他"""
    out = []
    for tr in rows_of(html):
        c = cells(tr)
        if len(c) < 9 or not c[0].isdigit():
            continue
        c += [""] * (10 - len(c))
        out.append({"market": market, "code": code, "board_date": board_date, "seq": c[0],
                     "report_date": roc_date(c[1]), "buy_date": roc_date(c[3]),
                     "shares": _num(c[4], True), "amount": _num(c[5], True), "avg_price": _num(c[6]),
                     "held_shares": _num(c[7], True), "held_pct": _num(c[8]),
                     "note": "" if c[9] in ("無", "") else c[9][:200]})
    return out


def in_period(p, prog):
    """達標申報屬於這次計畫：買回日期落在預定期間內（申報日期只是輔助，有更正舊序號的情形）。"""
    d = p["buy_date"] or p["report_date"]
    return bool(d and prog["start"] and prog["end"] and prog["start"] <= d <= prog["end"])


def active(programs, today):
    """還在買回期間內、或剛結束還沒公告結果的計畫"""
    return [p for p in programs if not p["bought_shares"] and p["end"] and p["end"] >= (today - timedelta(days=7)).isoformat()]


def fetch_progress(programs, today, budget_s):
    out, errors, t0 = [], [], time.time()
    for p in active(programs, today):
        if time.time() - t0 > budget_s:
            errors.append("達標申報：超過時間上限，剩下的下次再抓")
            break
        try:
            html = post("ajax_t35sb01", {"encodeURIComponent": 1, "step": 2, "firstin": "true", "TYPEK": p["market"],
                                         "co_id": p["code"], "colorchg": 1}, timeout=60, retries=2)
            out += [r for r in parse_progress(html, p["market"], p["code"], p["board_date"]) if in_period(r, p)]
        except C.AdapterError as e:
            errors.append(str(e)[:160])
        time.sleep(DELAY)
    return out, errors


# ---------------- 主程式 ----------------
def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(path, cols, rows):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="董事會決議日查詢起日 YYYY-MM-DD（預設：前年 1 月 1 日）")
    ap.add_argument("--max-minutes", type=float, default=10, help="達標申報抓取時間上限（分鐘）")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(C.TPE).date()
    since = date.fromisoformat(a.since) if a.since else date(today.year - 2, 1, 1)

    new, errors = [], []
    for mk in MARKETS:
        try:
            rows = fetch_programs(mk, since, today)
            print(f"{MARKETS[mk]}：{len(rows)} 筆買回計畫（{since} 起）")
            new += rows
        except C.AdapterError as e:
            errors.append(str(e)[:200])
            print(f"{MARKETS[mk]} 失敗：{e}", file=sys.stderr)
        time.sleep(DELAY)
    programs = merge(_read(OUT / "programs.csv"), new)
    if new:
        _write(OUT / "programs.csv", PROG_COLS, programs)

    prog, errs = fetch_progress(programs, today, a.max_minutes * 60)
    errors += errs
    if prog or not active(programs, today):
        # 只留目前執行中計畫的申報；舊計畫結束後以彙總表的結果為準
        _write(OUT / "progress.csv", PROGRESS_COLS,
               sorted(prog, key=lambda r: (r["code"], r["buy_date"], r["seq"])))
    print(f"執行中 {len(active(programs, today))} 筆，達標申報 {len(prog)} 筆")

    (OUT / "sources.json").write_text(json.dumps({
        "generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "since": since.isoformat(),
        "programs": len(programs), "errors": errors}, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in errors:
        print("  " + e, file=sys.stderr)
    return 0 if new else 1


if __name__ == "__main__":
    sys.exit(main())
