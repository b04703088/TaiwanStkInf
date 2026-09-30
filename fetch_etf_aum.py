#!/usr/bin/env python3
"""抓取全體台股 ETF 的規模（AUM）：發行單位數 × 單位淨值，存成每日 CSV。

資料來源（皆為證交所公開資料）：
  https://mis.twse.com.tw/stock/data/all_etf.txt
      各投信 ETF 即時淨值揭露彙整：a 代號、b 名稱、c 已發行單位數、d 單位數增減、
      e 市價、f 預估淨值、g 折溢價(%)、h 前一營業日單位淨值、i 日期
  https://openapi.twse.com.tw/v1/opendata/t187ap47_L
      上市 ETF 基本資料：基金類型（國內/國外、股票/債券、主動式…）

輸出 data/etf/aum/<YYYYMMDD>.csv（檔名 = 資料日期 i）：
  date, etf, name, category, units, units_change, nav, aum, flow, premium
  aum  = units × nav（nav 為前一營業日單位淨值）
  flow = units_change × nav：當日申購贖回造成的資金流入（負值為流出）

用法：python fetch_etf_aum.py
"""
import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "etf" / "aum"
ALL_ETF = "https://mis.twse.com.tw/stock/data/all_etf.txt"
ETF_INFO = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
COLUMNS = ["date", "etf", "name", "category", "units", "units_change", "nav", "aum", "flow", "premium"]
CATEGORIES = ["國內股票", "主動式", "國外股票", "債券", "槓桿反向", "期貨商品"]


def get_json(url, referer=None):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if referer:
        h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def categorize(code, fund_type=""):
    """歸類：官方基金類型優先，沒有（如上櫃 ETF）就看代號後綴。"""
    t = fund_type or ""
    suffix = code[-1] if code[-1].isalpha() else ""
    if "槓桿" in t or "反向" in t or suffix in ("L", "R"):
        return "槓桿反向"
    if "期貨" in t or suffix == "U":
        return "期貨商品"
    if "主動" in t or suffix in ("A", "D"):
        return "主動式"
    if "債" in t or suffix == "B":
        return "債券"
    if "國外" in t or "跨國" in t:
        return "國外股票"
    return "國內股票"


def parse_all_etf(payload):
    """all_etf.txt → [{etf, name, units, units_change, nav, premium, date}]；同代號只留一筆。"""
    out = {}
    for blk in payload.get("a1") or []:
        for m in blk.get("msgArray") or []:
            code = str(m.get("a") or "").strip()
            units, nav = num(m.get("c")), num(m.get("h"))
            if not code or not units or not nav:
                continue
            out[code] = {"etf": code, "name": str(m.get("b") or "").strip(), "units": units,
                         "units_change": num(m.get("d")) or 0.0, "nav": nav,
                         "premium": num(m.get("g")), "date": str(m.get("i") or "").strip()}
    return list(out.values())


def load_short_names():
    """用每日行情檔的交易所簡稱（all_etf.txt 的名稱多為全名，太長）。"""
    files = sorted((ROOT / "data").glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if not files:
        return {}
    with files[-1].open(encoding="utf-8") as fp:
        return {r["code"]: r["name"] for r in csv.DictReader(fp)}


def build_rows(records, types, short_names):
    rows = []
    for r in records:
        d = r["date"]
        date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d
        rows.append({
            "date": date, "etf": r["etf"], "name": short_names.get(r["etf"]) or r["name"],
            "category": categorize(r["etf"], types.get(r["etf"], "")),
            "units": int(r["units"]), "units_change": int(r["units_change"]), "nav": r["nav"],
            "aum": round(r["units"] * r["nav"]), "flow": round(r["units_change"] * r["nav"]),
            "premium": "" if r["premium"] is None else r["premium"],
        })
    rows.sort(key=lambda x: -x["aum"])
    return rows


def main():
    records = parse_all_etf(get_json(ALL_ETF, referer="https://mis.twse.com.tw/stock/etf_nav.jsp?ex=tse"))
    if len(records) < 50:
        print(f"all_etf.txt 只有 {len(records)} 筆，資料可能不完整", file=sys.stderr)
        return 1
    try:
        types = {r.get("基金代號", "").strip(): r.get("基金類型", "") for r in get_json(ETF_INFO)}
    except Exception as e:  # noqa: BLE001  類型只影響分類，抓不到就用代號後綴
        print(f"ETF 基本資料抓取失敗（改用代號判斷類型）：{e}", file=sys.stderr)
        types = {}
    rows = build_rows(records, types, load_short_names())
    date = max(r["date"] for r in rows)
    out = OUT_DIR / f"{date.replace('-', '')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    total = sum(r["aum"] for r in rows)
    print(f"{date}: {len(rows)} 檔 ETF，總規模 {total / 1e12:.2f} 兆 -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
