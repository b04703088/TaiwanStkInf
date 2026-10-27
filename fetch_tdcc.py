#!/usr/bin/env python3
"""集保戶股權分散表（每週）：每檔股票各持股級距的人數與比例，整理成大戶／散戶持股。

資料來源（臺灣集中保管結算所開放資料，公開免登入）
  https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
  欄位：資料日期, 證券代號, 持股分級, 人數, 股數, 占集保庫存數比例%
  持股分級 1～15：1-999 股、1-5 張、5-10、10-15、15-20、20-30、30-40、40-50、50-100、100-200、200-400、
                  400-600、600-800、800-1000、1000 張以上；16 差異數調整；17 合計
  只提供最新一週（每週五傍晚更新，資料日期是當週最後一個營業日），所以每週抓一次累積歷史。

輸出 data/tdcc/<YYYYMMDD>.csv（檔名＝資料日期）
  date, code, holders     集保總人數
  shares                  集保總股數
  p1000, n1000            1000 張以上大戶：持股比例 %、人數
  p400                    400 張以上持股比例 %
  p_retail                50 張以下持股比例 %（級距 1～8）
  p_lt1                   未滿 1 張（零股）持股比例 %

用法：python fetch_tdcc.py
"""
import csv
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "data" / "tdcc"
URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
COLUMNS = ["date", "code", "holders", "shares", "p1000", "n1000", "p400", "p_retail", "p_lt1"]


def parse(text):
    """CSV 文字 → (資料日期 YYYYMMDD, rows)。只收台股代號（4～6 碼英數），略過全部是 0 的。"""
    lv = {}
    date = None
    for r in csv.reader(text.lstrip("﻿").splitlines()):
        if len(r) < 6 or not r[0].strip().isdigit():
            continue
        date = r[0].strip()
        code, level = r[1].strip(), int(r[2])
        try:
            n, sh, pct = int(r[3]), int(r[4]), float(r[5])
        except ValueError:
            continue
        lv.setdefault(code, {})[level] = (n, sh, pct)
    rows = []
    for code, x in sorted(lv.items()):
        tot = x.get(17)
        if not tot or not tot[0] or not (4 <= len(code) <= 6):
            continue
        p = lambda ks: round(sum(x.get(k, (0, 0, 0))[2] for k in ks), 2)  # noqa: E731
        rows.append({"date": f"{date[:4]}-{date[4:6]}-{date[6:]}", "code": code, "holders": tot[0], "shares": tot[1],
                     "p1000": p([15]), "n1000": x.get(15, (0,))[0], "p400": p([12, 13, 14, 15]),
                     "p_retail": p(range(1, 9)), "p_lt1": p([1])})
    return date, rows


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8", "replace")
    date, rows = parse(text)
    if not date or len(rows) < 1000:
        print(f"資料異常：日期 {date}、{len(rows)} 檔", file=sys.stderr)
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{date}.csv"
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{date}: {len(rows)} 檔 -> {out}")


if __name__ == "__main__":
    main()
