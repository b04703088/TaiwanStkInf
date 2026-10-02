#!/usr/bin/env python3
"""臺灣指數公司（TIP）指數定期審核日程表 → 哪些指數哪天公告調整、哪天生效，以及追蹤這些指數的 ETF。

資料來源（公開）：
  清單 https://taiwanindex.com.tw/downloads/technical_notice?category_id=3&page=N
       每月一份「YYYY年M月指數定期審核日程表」PDF
  PDF  https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/<id>/tw
       表格：指數名稱、公告日期（收盤後）、生效日期
  ETF 對應：證交所 ETF 基本資料 openapi t187ap47_L 的「標的指數/追蹤指數名稱」（上市 ETF）

輸出：
  data/etf/tip/schedule.csv   index, announce_date, effective_date, schedule, source_id, file_date
  data/etf/tip/sources.json   已解析過的 PDF（id → 標題、檔案日期、筆數）
  data/etf/tip/etf_index.csv  etf, name, index（追蹤 TIP 指數的上市 ETF）

TIP 會直接更新同一個 PDF（同一個 id），所以清單第一頁最新的幾份每次都重新下載解析。
需要 pdfplumber（pip install pdfplumber）。

用法：python fetch_tip_schedule.py [--pages 3]
"""
import argparse
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "etf" / "tip"
LIST = "https://taiwanindex.com.tw/downloads/technical_notice"
PDF = "https://backend.taiwanindex.com.tw/api/downloadFile/TechnicalNotices/{}/tw"
ETF_INFO = "https://openapi.twse.com.tw/v1/opendata/t187ap47_L"
COLS = ["index", "announce_date", "effective_date", "schedule", "source_id", "file_date"]
REFRESH_LATEST = 3   # 第一頁最新幾份每次重抓（TIP 會原檔更新）

_ITEM = re.compile(r"檔案日期</th>\s*<td[^>]*>\s*([\d/]+)\s*</td>.*?檔案名稱</th>\s*<td[^>]*>\s*([^<]+?)\s*</td>"
                   r".*?TechnicalNotices/(\d+)/tw", re.S)
_DATE = re.compile(r"(20\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")


def parse_list(page):
    """清單頁 → [(id, 標題, 檔案日期)]，只取「定期審核日程表」，依頁面順序去重。"""
    out, seen = [], set()
    for date, title, fid in _ITEM.findall(page):
        title = re.sub(r"\s+", "", title)
        if "審核日程" in title and fid not in seen:
            seen.add(fid)
            out.append((fid, title, C.iso(date.strip())))
    return out


def _d(s):
    m = _DATE.search(s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def parse_tables(tables):
    """pdfplumber 的表格 → [(指數名稱, 公告日, 生效日)]。每列取第一個非日期欄當名稱、前兩個日期。"""
    out = []
    for t in tables:
        for row in t:
            cells = [re.sub(r"\s+", " ", c).strip() for c in row if c]
            dates = [_d(c) for c in cells if _d(c)]
            names = [c for c in cells if not _d(c) and "指數" in c and "指數名稱" not in c]
            if len(dates) >= 2 and names:
                out.append((names[0], dates[0], dates[1]))
    return out


def parse_pdf(content):
    import pdfplumber
    tables = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for pg in pdf.pages:
            tables += pg.extract_tables()
    return parse_tables(tables)


def norm_index(name):
    """指數名稱正規化：去掉「臺灣指數公司」前綴、空白、全半形差異，方便和 ETF 標的指數比對。"""
    s = (name or "").replace("台灣", "臺灣").replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    s = s.replace("臺灣指數公司", "").replace("指數股份有限公司", "")
    s = s.replace("＆", "&").upper()
    return s


def read_schedule():
    p = OUT / "schedule.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def map_etfs():
    """上市 ETF 的標的指數 → 只留追蹤 TIP 指數（名稱含「臺灣指數公司」或與日程表指數相符）的。"""
    try:
        info = C.http(ETF_INFO)
    except C.AdapterError as e:
        print(f"ETF 基本資料抓取失敗：{e}", file=sys.stderr)
        return None
    rows = []
    for r in info or []:
        idx = (r.get("標的指數/追蹤指數名稱") or "").strip()
        code = (r.get("基金代號") or "").strip()
        if code and idx:
            rows.append({"etf": code, "name": (r.get("基金簡稱") or "").strip(), "index": idx})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, default=1, help="讀清單前幾頁（第一次回補用 3，平常 1）")
    a = ap.parse_args(argv)

    sources_p = OUT / "sources.json"
    sources = json.loads(sources_p.read_text(encoding="utf-8")) if sources_p.exists() else {}
    items = []
    for p in range(1, a.pages + 1):
        page = C.http(LIST, {"category_id": 3, "page": p}, as_json=False)
        items += parse_list(page)
    if not items:
        print("清單頁沒有找到任何日程表（網站可能改版）", file=sys.stderr)
        return 1

    rows = read_schedule()
    refresh = {fid for fid, _, _ in items[:REFRESH_LATEST]}
    n_new, failed = 0, []
    for fid, title, fdate in items:
        if fid in sources and fid not in refresh:
            continue
        try:
            parsed = parse_pdf(C.http(PDF.format(fid), raw=True))
        except Exception as e:  # noqa: BLE001  單一 PDF 失敗不影響其他
            failed.append(fid)
            print(f"  {title}（{fid}）解析失敗：{e}", file=sys.stderr)
            continue
        if not parsed:
            failed.append(fid)
            print(f"  {title}（{fid}）沒有解析出任何指數", file=sys.stderr)
            continue
        m = re.search(r"(20\d\d)年(\d{1,2})月", title)
        sched = f"{m.group(1)}-{int(m.group(2)):02d}" if m else title
        rows = [r for r in rows if r["source_id"] != fid]
        rows += [{"index": n, "announce_date": d1, "effective_date": d2, "schedule": sched,
                  "source_id": fid, "file_date": fdate} for n, d1, d2 in parsed]
        sources[fid] = {"title": title, "file_date": fdate, "rows": len(parsed)}
        n_new += 1
        time.sleep(0.5)

    # 同一指數同一生效日只留最新一份
    best = {}
    for r in rows:
        k = (norm_index(r["index"]), r["effective_date"])
        if k not in best or int(r["source_id"]) > int(best[k]["source_id"]):
            best[k] = r
    rows = sorted(best.values(), key=lambda r: (r["announce_date"], r["index"]))
    write_csv(OUT / "schedule.csv", COLS, rows)
    sources_p.write_text(json.dumps(sources, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    etfs = map_etfs()
    if etfs is not None:
        tip = {norm_index(r["index"]) for r in rows}
        keep = [e for e in etfs if norm_index(e["index"]) in tip or "臺灣指數公司" in e["index"].replace("台灣", "臺灣")]
        write_csv(OUT / "etf_index.csv", ["etf", "name", "index"], sorted(keep, key=lambda e: e["etf"]))
        print(f"追蹤 TIP 指數的上市 ETF：{len(keep)} 檔")
    print(f"日程表：解析 {n_new} 份，共 {len(rows)} 筆指數審核，失敗 {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
