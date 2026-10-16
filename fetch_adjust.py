#!/usr/bin/env python3
"""還原股價用的「基準價變動」事件：除權息、減資、變更面額、ETF 分割／反分割。

每個事件都有「事件前收盤價」與「事件後參考價」，兩者相除就是還原因子：
    factor = ref_price / prev_close
事件日（除權息日、恢復買賣日）之前的價格 × 之後所有事件的 factor 連乘 = 還原股價（見 adjust.py）。

資料來源（證交所、櫃買中心公開資料，免登入）
  上市 https://www.twse.com.tw/rwd/zh/exRight/TWT49U        除權除息計算結果表
       https://www.twse.com.tw/rwd/zh/reducation/TWTAUU     減資恢復買賣參考價格
       https://www.twse.com.tw/rwd/zh/change/TWTB8U         變更股票面額恢復買賣參考價格
       https://www.twse.com.tw/rwd/zh/split/TWTCAU          ETF 分割（反分割）恢復買賣參考價格
  上櫃 https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ  除權除息計算結果表
       https://www.tpex.org.tw/www/zh-tw/bulletin/revivt    減資恢復買賣參考價格

輸出 data/adjust/
  events.csv     date, market, code, name, kind, prev_close, ref_price, factor, cash, note, source
                 date      除權息日／恢復買賣日（這天開始用新基準；這天之前的價格要乘 factor）
                 kind      除息、除權、除權息、減資、面額變更、分割、反分割
                 cash      每股現金（除息的現金股利；減資的每股退還股款），查得到才填
                 note      減資原因、換股比例等
  sources.json   最後執行時間、各來源筆數、錯誤

用法
  python fetch_adjust.py                        # 近 60 天到未來 14 天（每天排程）
  python fetch_adjust.py --since 2022-01-01     # 回補（按年分段查，約 1 分鐘）
"""
import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

TPE = timezone(timedelta(hours=8))
OUT_DIR = Path(__file__).resolve().parent / "data" / "adjust"
COLUMNS = ["date", "market", "code", "name", "kind", "prev_close", "ref_price", "factor",
           "cash", "note", "source"]

TWSE = "https://www.twse.com.tw/rwd/zh/{path}?startDate={s:%Y%m%d}&endDate={e:%Y%m%d}&response=json"
TPEX = "https://www.tpex.org.tw/www/zh-tw/bulletin/{path}?startDate={s:%Y/%m/%d}&endDate={e:%Y/%m/%d}&response=json"
DELAY = 4  # 證交所約 5 秒 3 次請求，超過會被暫時封鎖


def http_json(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            wait = 10 * 2 ** attempt
            print(f"  retry {attempt + 1}/{retries - 1} in {wait}s: {e!r}", file=sys.stderr)
            time.sleep(wait)


def roc_date(s):
    """'115年06月01日'、'115/06/01'、'1150601' → '2026-06-01'；看不懂回傳 ''。"""
    digits = re.findall(r"\d+", str(s))
    if len(digits) == 1 and len(digits[0]) == 7:
        digits = [digits[0][:3], digits[0][3:5], digits[0][5:]]
    if len(digits) != 3:
        return ""
    try:
        return date(int(digits[0]) + 1911, int(digits[1]), int(digits[2])).isoformat()
    except ValueError:
        return ""


def num(s):
    """'2,485.00' → 2485.0；'--'、'N/A'、空白 → None。"""
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def fmt(x, nd=6):
    if x is None:
        return ""
    return f"{x:.{nd}f}".rstrip("0").rstrip(".")


def event(d, market, code, name, kind, prev, ref, source, cash=None, note=""):
    prev, ref = num(prev), num(ref)
    if not d or not code or not prev or not ref:
        return None
    return {"date": d, "market": market, "code": code.strip(), "name": name.strip(), "kind": kind,
            "prev_close": fmt(prev, 4), "ref_price": fmt(ref, 4), "factor": fmt(ref / prev, 8),
            "cash": fmt(cash) if cash else "", "note": note, "source": source}


def _rows(payload):
    """證交所：{fields, data}；櫃買：{tables: [{fields, data}]} → (fields, data)。"""
    if not payload:
        return [], []
    if "tables" in payload:
        t = next((t for t in payload["tables"] if t.get("data")), None)
        return (t["fields"], t["data"]) if t else ([], [])
    if str(payload.get("stat", "")).upper() != "OK":
        return [], []
    return payload.get("fields") or [], payload.get("data") or []


def _ix(fields, *names):
    for name in names:
        for i, f in enumerate(fields):
            if name in f:
                return i
    raise KeyError(f"找不到欄位 {names}，現有欄位: {fields}")


EX_KIND = {"息": "除息", "權": "除權", "權息": "除權息", "除息": "除息", "除權": "除權", "除權息": "除權息"}


def parse_twse_exright(payload):
    """TWT49U 除權除息計算結果表。cash 只在純除息時填（權息合併時表上只有「權值+息值」）。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        kind = EX_KIND.get(g("權/息").strip(), "除權息")
        e = event(roc_date(g("資料日期")), "TWSE", g("股票代號"), g("股票名稱"), kind,
                  g("除權息前收盤價"), g("除權息參考價"), "TWT49U",
                  cash=num(g("權值+息值")) if kind == "除息" else None)
        if e:
            out.append(e)
    return out


def parse_tpex_exright(payload):
    """exDailyQ 除權除息計算結果表（有拆開權值、息值、現金股利、每仟股配股）。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        stock = num(g("每仟股無償配股"))
        e = event(roc_date(g("除權息日期")), "TPEx", g("代號"), g("名稱"), EX_KIND.get(g("權/息").strip(), "除權息"),
                  g("除權息前收盤價"), g("除權息參考價"), "exDailyQ", cash=num(g("現金股利")),
                  note=f"每仟股配股 {fmt(stock)} 股" if stock else "")
        if e:
            out.append(e)
    return out


def parse_twse_reduction(payload):
    """TWTAUU 減資恢復買賣參考價格。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        e = event(roc_date(g("恢復買賣日期")), "TWSE", g("股票代號"), g("名稱"), "減資",
                  g("停止買賣前收盤價格"), g("恢復買賣參考價"), "TWTAUU", note=g("減資原因").strip())
        if e:
            out.append(e)
    return out


def _detail(htm, label):
    m = re.search(re.escape(label) + r".*?<td>(.*?)</td>", htm or "", re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).replace("\xa0", " ").strip() if m else ""


def parse_tpex_reduction(payload):
    """revivt 減資恢復買賣參考價格；詳細資料（HTML）裡有換股比例、每股退還股款。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        det = g("詳細資料")
        per1000 = num(_detail(det, "每壹仟股換發新股票").split(" ")[0])
        refund = num(_detail(det, "每股退還股款").split(" ")[0])
        note = g("減資原因").strip()
        if per1000:
            note += f"；每仟股換發 {fmt(per1000, 3)} 股"
        e = event(roc_date(g("恢復買賣日期")), "TPEx", g("股票代號"), g("名稱"), "減資",
                  g("最後交易日之收盤價格"), g("減資恢復買賣開始日參考價格"), "revivt", cash=refund, note=note)
        if e:
            out.append(e)
    return out


def parse_twse_par(payload):
    """TWTB8U 變更股票面額恢復買賣參考價格（參考價 = 前收盤 / 換股率）。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        prev, ref = num(g("停止買賣前收盤價格")), num(g("恢復買賣參考價"))
        note = f"1 股換 {fmt(prev / ref, 2)} 股" if prev and ref else ""
        e = event(roc_date(g("恢復買賣日期")), "TWSE", g("股票代號"), g("名稱"), "面額變更",
                  prev, ref, "TWTB8U", note=note)
        if e:
            out.append(e)
    return out


def parse_twse_split(payload):
    """TWTCAU ETF 分割（反分割）恢復買賣參考價格。"""
    f, data = _rows(payload)
    out = []
    for r in data:
        g = lambda *n: r[_ix(f, *n)]  # noqa: E731
        prev, ref = num(g("停止買賣前收盤價格")), num(g("恢復買賣參考價"))
        kind = g("分割(反分割)").strip() or ("分割" if prev and ref and ref < prev else "反分割")
        note = (f"1 單位分割為 {fmt(prev / ref, 2)} 單位" if kind == "分割" else
                f"{fmt(ref / prev, 2)} 單位合併為 1 單位") if prev and ref else ""
        e = event(roc_date(g("恢復買賣日期")), "TWSE", g("ETF代號"), g("名稱"), kind, prev, ref, "TWTCAU", note=note)
        if e:
            out.append(e)
    return out


# (來源名稱, URL 樣板, path, parser, 是否要按年分段)
SOURCES = [
    ("TWT49U", TWSE, "exRight/TWT49U", parse_twse_exright, True),
    ("TWTAUU", TWSE, "reducation/TWTAUU", parse_twse_reduction, False),
    ("TWTB8U", TWSE, "change/TWTB8U", parse_twse_par, False),
    ("TWTCAU", TWSE, "split/TWTCAU", parse_twse_split, False),
    ("exDailyQ", TPEX, "exDailyQ", parse_tpex_exright, True),
    ("revivt", TPEX, "revivt", parse_tpex_reduction, False),
]


def year_chunks(start, end):
    s = start
    while s <= end:
        e = min(date(s.year, 12, 31), end)
        yield s, e
        s = e + timedelta(days=1)


def fetch_all(start, end, sleep=DELAY):
    """回傳 (events, ok_sources, errors)。某個來源失敗不影響其他來源。"""
    events, ok, errors, first = [], [], [], True
    for name, tpl, path, parser, chunk in SOURCES:
        got = []
        try:
            for s, e in (year_chunks(start, end) if chunk else [(start, end)]):
                if not first:
                    time.sleep(sleep)
                first = False
                got += parser(http_json(tpl.format(path=path, s=s, e=e)))
        except Exception as ex:  # noqa: BLE001
            errors.append(f"{name}: {ex!r}")
            print(f"{name}: 失敗 {ex!r}", file=sys.stderr)
            continue
        print(f"{name}: {len(got)} 筆")
        events += got
        ok.append(name)
    return events, ok, errors


def key(e):
    return (e["date"], e["code"], e["kind"])


def merge(old, new, start, end, ok_sources):
    """查詢區間內、且這次有成功查到的來源 → 以新資料為準；其餘保留舊的。"""
    s, e = start.isoformat(), end.isoformat()
    keep = [r for r in old if not (s <= r["date"] <= e and r["source"] in ok_sources)]
    merged = {key(r): r for r in keep}
    for r in new:
        merged[key(r)] = r
    return sorted(merged.values(), key=lambda r: (r["date"], r["market"], r["code"], r["kind"]))


def read_csv(path):
    try:
        with open(path, encoding="utf-8") as fp:
            return list(csv.DictReader(fp))
    except FileNotFoundError:
        return []


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, help="查詢起日（預設 60 天前）")
    ap.add_argument("--until", type=date.fromisoformat, help="查詢迄日（預設 14 天後；除權息計算結果會提前公布）")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    today = datetime.now(TPE).date()
    start = args.since or today - timedelta(days=60)
    end = args.until or today + timedelta(days=14)
    new, ok, errors = fetch_all(start, end)

    path = args.out / "events.csv"
    rows = merge(read_csv(path), new, start, end, set(ok))
    write_csv(path, rows)
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    src = {"generated": datetime.now(TPE).isoformat(timespec="seconds"), "range": [start.isoformat(), end.isoformat()],
           "fetched": len(new), "ok": ok, "errors": errors, "total": len(rows), "kinds": counts,
           "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None}
    (args.out / "sources.json").write_text(json.dumps(src, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"完成：這次抓到 {len(new)} 筆，共 {len(rows)} 筆 -> {path}")
    if errors and not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
