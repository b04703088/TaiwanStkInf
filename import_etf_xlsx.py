#!/usr/bin/env python3
"""把外部整理的 ETF 每日持股 Excel 匯入 data/etf/<代號>/<日期>.csv（補官網查不到的歷史）。

Excel 格式（第一張工作表）：基金碼（'00405A 主動富邦臺灣龍耀'）、日期、標的類型、標的名稱（'3653 健策'）、股數、金額。
  · 只取標的類型＝股票；期貨、選擇權略過。
  · 只補「本站最早一份之前」的日期，不覆寫既有資料。
  · 台股代號但名稱是外文、且和行情檔的名稱對不上的列（例：'2360 CLOUDFLARE INC'，海外股被配錯代號）略過。
  · 權重＝該股金額 ÷ 當日股票部位總金額（不是佔淨值）；沒有金額時留空。

用法: python import_etf_xlsx.py 檔案.xlsx [--dry-run]
"""
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import openpyxl

from fetch_etf import ETF_DIR, write_day

TW = re.compile(r"^\d{4,6}[A-Z]?$")
CJK = re.compile(r"[一-鿿]")


def tw_names(data_dir):
    """最近一個行情檔的 {代號: 名稱}。"""
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if not files:
        return {}
    with files[-1].open(encoding="utf-8") as fp:
        return {r["code"]: r["name"] for r in csv.DictReader(fp)}


def _norm(s):
    return re.sub(r"[\s\-*]", "", str(s or "")).upper()


def read_xlsx(path):
    """{(ETF, 日期): {代號: (名稱, 股數, 金額)}}"""
    out = defaultdict(dict)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for i, r in enumerate(wb.worksheets[0].iter_rows(values_only=True)):
        if i == 0 or not r[0] or r[2] != "股票" or r[4] is None:
            continue
        etf = str(r[0]).split()[0]
        d = r[1].date().isoformat() if hasattr(r[1], "date") else str(r[1])[:10]
        m = re.match(r"^(\S+)\s+(.*)$", str(r[3]).strip())
        code, name = (m.group(1), m.group(2).strip()) if m else (str(r[3]).strip(), "")
        out[(etf, d)][code] = (name, r[4], r[5])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    names = tw_names(ETF_DIR.parent)
    data = read_xlsx(a.xlsx)
    stats, skipped = defaultdict(list), set()
    first = {}  # 匯入前本站最早一份（先算好，免得剛寫的檔案被當成既有資料）
    for etf in {k[0] for k in data}:
        have = sorted((ETF_DIR / etf).glob("[0-9]*.csv"))
        first[etf] = f"{have[0].stem[:4]}-{have[0].stem[4:6]}-{have[0].stem[6:]}" if have else "9999"
    for (etf, d), rows in sorted(data.items()):
        if d >= first[etf]:
            continue
        hs = []
        for code, (name, sh, amt) in rows.items():
            if TW.match(code) and not CJK.search(name) and code in names and _norm(names[code]) != _norm(name):
                skipped.add((etf, code, name))
                continue
            hs.append({"code": code, "name": name, "shares": int(round(float(sh))), "amt": float(amt) if amt else None})
        tot = sum(h["amt"] or 0 for h in hs)
        rows_out = [{"code": h["code"], "name": h["name"], "shares": h["shares"],
                     "weight": round(h["amt"] / tot * 100, 4) if tot and h["amt"] else None} for h in hs]
        if not a.dry_run:
            write_day(etf, d, rows_out)
        stats[etf].append(d)
    for etf, ds in sorted(stats.items()):
        print(f"{etf}: 新增 {len(ds)} 天 {ds[0]} ~ {ds[-1]}")
    for s in sorted(skipped):
        print("略過（代號與名稱對不上）:", *s)


if __name__ == "__main__":
    main()
