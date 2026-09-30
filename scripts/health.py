#!/usr/bin/env python3
"""資料健檢：檢查股價、ETF 持股、ETF 規模是否都有按時、完整地抓到。

檢查項目
  股價   最近一個應開盤日（今天之前、平日、不在 no_trading_days.txt）有沒有收盤檔、筆數是否正常
  ETF   每檔最新持股落後幾個交易日、成分股數、權重加總、檔數與前一份相比是否暴增暴減、股數是否缺漏
  規模   data/etf/aum/ 最新一天是否落後

等級：ok 正常 / warn 需留意（可能是投信資料本身的狀況）/ error 幾乎可以確定漏抓或抓錯

用法：
  python scripts/health.py            印出報告
  python scripts/health.py --strict   有 error 就回傳 1（GitHub Actions 會因此寄失敗通知信）
  python scripts/health.py --json out.json
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TPE = timezone(timedelta(hours=8))

# 門檻
ETF_LAG_ERROR = 2      # 持股落後 ≥ 2 個交易日 → error（T+1 公告的投信早上本來就落後 1 天）
AUM_LAG_WARN = 2
WEIGHT_LOW_ERROR, WEIGHT_LOW_WARN, WEIGHT_HIGH_ERROR = 70.0, 80.0, 105.0
COUNT_JUMP_WARN = 0.25  # 成分股數與前一份相差超過 25%
PRICE_MIN_ROWS = 1000   # 上市櫃合計一天應有數千檔


def _num(s):
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _date(stem):
    return f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"


def _read(path):
    with open(path, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def expected_trading_day(now, holidays):
    """今天之前最近一個應開盤日（平日且不在已知休市日）。"""
    d = now.date()
    for _ in range(20):
        d -= timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in holidays:
            return d.isoformat()
    return None


def check(data_dir=ROOT / "data", now=None):
    data_dir = Path(data_dir)
    now = now or datetime.now(TPE)
    hp = data_dir / "no_trading_days.txt"
    holidays = set(hp.read_text().split()) if hp.exists() else set()
    expected = expected_trading_day(now, holidays)
    items = []

    def add(kind, key, name, level, date, msg, **stats):
        items.append({"kind": kind, "id": key, "name": name, "level": level, "date": date, "msg": msg, **stats})

    # ---------- 股價 ----------
    price_files = sorted(data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    trading_days = [_date(f.stem) for f in price_files]
    latest_price = trading_days[-1] if trading_days else None
    if not latest_price:
        add("price", "prices", "每日股價", "error", None, "沒有任何股價檔")
    else:
        n = len(_read(price_files[-1]))
        if expected and latest_price < expected:
            add("price", "prices", "每日股價", "error", latest_price,
                f"缺 {expected} 的收盤資料（若當天休市，排程會自動記進 no_trading_days.txt）", rows=n)
        elif n < PRICE_MIN_ROWS:
            add("price", "prices", "每日股價", "error", latest_price, f"只有 {n} 檔，資料可能不完整", rows=n)
        else:
            add("price", "prices", "每日股價", "ok", latest_price, f"{n} 檔", rows=n)

    # 交易日序列（含應開盤但還沒抓到的那天），用來算 ETF 落後幾個交易日
    days = sorted(set(trading_days) | ({expected} if expected else set()))

    def lag(d):
        return sum(1 for x in days if x > d and (expected is None or x <= expected)) if d else None

    # ---------- ETF 持股 ----------
    etf_dir = data_dir / "etf"
    lst = etf_dir / "etf_list.csv"
    for info in (_read(lst) if lst.exists() else []):
        code, name = info["etf"], f'{info["name"]}（{info.get("issuer_name", "")}）'
        files = sorted((etf_dir / code).glob("[0-9]*.csv"))
        if not files:
            add("etf", code, name, "error", None, "還沒有任何持股資料")
            continue
        d = _date(files[-1].stem)
        rows = _read(files[-1])
        prev = _read(files[-2]) if len(files) > 1 else None
        w = sum(_num(r["weight"]) or 0 for r in rows)
        has_w = any(r["weight"] for r in rows)
        null_sh = sum(1 for r in rows if not r["shares"])
        prev_null = sum(1 for r in prev if not r["shares"]) if prev else 0
        lg = lag(d)
        stats = {"n": len(rows), "prev_n": len(prev) if prev else None, "wsum": round(w, 1) if has_w else None,
                 "lag": lg, "files": len(files)}
        errs, warns = [], []
        if lg is not None and lg >= ETF_LAG_ERROR:
            errs.append(f"落後 {lg} 個交易日")
        if len(rows) < 5:
            errs.append(f"只有 {len(rows)} 檔成分股")
        if has_w and (w < WEIGHT_LOW_ERROR or w > WEIGHT_HIGH_ERROR):
            errs.append(f"權重加總 {w:.1f}%")
        elif has_w and w < WEIGHT_LOW_WARN:
            warns.append(f"權重加總偏低 {w:.1f}%")
        if not has_w:
            warns.append("沒有權重")
        if null_sh and null_sh > prev_null:
            errs.append(f"{null_sh} 檔沒有股數")
        if prev and abs(len(rows) - len(prev)) > COUNT_JUMP_WARN * len(prev):
            warns.append(f"成分股數 {len(prev)} → {len(rows)}")
        if lg == 1:
            msg = "T+1 公告，等下一次排程"
        else:
            msg = ""
        level = "error" if errs else ("warn" if warns else "ok")
        add("etf", code, name, level, d, "；".join(errs + warns) or msg, **stats)

    # ---------- ETF 規模 ----------
    aum_files = sorted((etf_dir / "aum").glob("[0-9]*.csv"))
    if not aum_files:
        add("aum", "aum", "全體 ETF 規模", "warn", None, "沒有規模資料")
    else:
        d = _date(aum_files[-1].stem)
        n = len(_read(aum_files[-1]))
        lg = lag(d)
        level = "warn" if (lg or 0) >= AUM_LAG_WARN or n < 100 else "ok"
        add("aum", "aum", "全體 ETF 規模", level, d, f"{n} 檔" + (f"，落後 {lg} 個交易日" if lg else ""), rows=n, lag=lg)

    count = {k: sum(1 for i in items if i["level"] == k) for k in ("ok", "warn", "error")}
    return {"generated": now.strftime("%Y-%m-%d %H:%M"), "expected": expected, "latest_price": latest_price,
            "count": count, "items": items}


def report(h):
    lines = [f"資料健檢 {h['generated']}（應有交易日 {h['expected']}，最新股價 {h['latest_price']}）",
             f"正常 {h['count']['ok']}、留意 {h['count']['warn']}、異常 {h['count']['error']}"]
    for lv, tag in (("error", "✗ 異常"), ("warn", "! 留意")):
        for i in h["items"]:
            if i["level"] == lv:
                lines.append(f"{tag}  {i['id']:8} {i['name']}  資料日 {i['date'] or '-'}  {i['msg']}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="有 error 就回傳 1")
    ap.add_argument("--json", help="另存 JSON")
    a = ap.parse_args(argv)
    h = check()
    text = report(h)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fp:
            fp.write("```\n" + text + "\n```\n")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 1 if a.strict and h["count"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
