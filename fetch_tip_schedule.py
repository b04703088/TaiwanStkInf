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
  data/etf/tip/results.csv    定審結果：index, announce_date, effective_date, action(add/del/none), code, name, source_id
  data/etf/tip/etf_index.csv  etf, name, index（全部上市 ETF 的標的指數；網頁建置時再比對 TIP 指數）

TIP 會直接更新同一個 PDF（同一個 id），所以清單第一頁最新的幾份每次都重新下載解析。
需要 pdfplumber（pip install pdfplumber）。

用法：python fetch_tip_schedule.py [--pages 3]
"""
import argparse
import csv
import html
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
    s = html.unescape(name or "").replace("台灣", "臺灣").replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    s = s.replace("臺灣指數公司", "").replace("指數股份有限公司", "")
    s = s.replace("＆", "&").upper()
    return s


def index_key(name):
    """比對用的寬鬆鍵：再去掉「特選」「報酬」「股價」等常被省略的字，讓日程表與 ETF 標的指數名稱對得上。"""
    s = norm_index(name)
    for w in ("報酬", "股價", "特選", "上市上櫃", "指數"):
        s = s.replace(w, "")
    return s


def match_etfs(indexes, etf_rows, overrides=None, cutoff=0.85):
    """指數名稱 → 追蹤的 ETF 代號清單。先比寬鬆鍵完全相同；對不上的再用相似度（≥ cutoff），
    但已經完全對上別的指數的 ETF 不再拿來模糊比對（避免「IC 設計報酬」誤配到「IC 設計動能」的 ETF）。
    overrides：{指數名稱: [ETF 代號]}，手動指定，優先。"""
    import difflib
    by_key = {}
    for e in etf_rows:
        by_key.setdefault(index_key(e["index"]), []).append(e["etf"])
    out, used = {}, set()
    for name in indexes:
        hit = by_key.get(index_key(name))
        if hit:
            out[name] = list(hit)
            used.update(hit)
    for name in indexes:
        if name in out:
            continue
        k = index_key(name)
        best, score = None, 0.0
        for ek, codes in by_key.items():
            if set(codes) & used:
                continue
            r = difflib.SequenceMatcher(None, k, ek).ratio()
            if r > score:
                best, score = codes, r
        out[name] = list(best) if best and score >= cutoff else []
    for name, codes in (overrides or {}).items():
        for n in indexes:
            if index_key(n) == index_key(name):
                out[n] = list(codes)
    return out


# ---------------- 定審結果（成分股納入／刪除） ----------------
RES_COLS = ["index", "announce_date", "effective_date", "action", "code", "name", "source_id"]
_CODE = re.compile(r"(?<![\d.])(\d{4}[A-Z]?)(?![\d.%])")
_CN_NUM = "一二三四五六七八九十"


def _cn_date(s):
    m = re.search(r"(20\d\d)年(\d{1,2})月(\d{1,2})日", s)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def _effective(text):
    t = re.sub(r"\s+", "", text)
    m = re.search(r"亦即自?(20\d\d年\d{1,2}月\d{1,2}日)", t) or re.search(r"生效日期[：:](20\d\d年\d{1,2}月\d{1,2}日)", t)
    return _cn_date(m.group(1)) if m else None


def _stocks(seg):
    """一段文字裡的股票：(代號, 名稱)。支援「3532 台勝科、6187 萬潤」「祥碩 5269」「9921巨大」等寫法。"""
    out = []
    for line in re.split(r"[\n、，,]", seg):
        line = re.sub(r"公眾流通量.*$", "", line).strip()
        m = _CODE.search(line)
        if not m:
            continue
        name = (line[:m.start()] + " " + line[m.end():]).strip()
        name = re.sub(r"[\s:：()（）]+", "", name)
        out.append((m.group(1), name))
    return out


def _add_del(block):
    """區塊內的「成分股納入」與「成分股刪除」名單（遇到候補名單、註記就停）。"""
    t = re.split(r"成分股候補名單|\*註|※|如欲取得", block)[0]
    hdr = r"\s*[（(]?\s*\d*\s*[)）]?\s*[：:]"
    m_add = re.search(r"成分股納入" + hdr, t)
    m_del = re.search(r"成分股刪除" + hdr, t)
    if not m_add and not m_del:
        return None
    adds = _stocks(t[m_add.end():m_del.start() if m_del and m_del.start() > m_add.start() else len(t)]) if m_add else []
    dels = _stocks(t[m_del.end():]) if m_del else []
    if m_add and m_del and m_del.start() < m_add.start():  # 刪除寫在前面
        dels = _stocks(t[m_del.end():m_add.start()])
    return adds, dels


def parse_result(text, title):
    """定審結果 PDF 文字 → [(指數名稱, 生效日, 納入[(代號,名稱)], 刪除[...])]。
    單一指數：標題「」內是指數名稱；合編多指數（臺灣50 等）：以「一、 臺灣50指數」分段。"""
    eff = _effective(text)
    secs = re.split(r"\n\s*([" + _CN_NUM + r"]+)、\s*([^\n]*指數)\s*\n", "\n" + text)
    out = []
    if len(secs) > 1:
        for i in range(1, len(secs) - 2, 3):
            r = _add_del(secs[i + 2])
            if r:
                out.append((secs[i + 1].strip(), eff, r[0], r[1]))
        if out:
            return out
    m = re.search(r"「([^」]+)」", title) or re.search(r"「([^」]+)」", text)
    r = _add_del(text)
    if m and r:
        out.append((m.group(1).strip(), eff, r[0], r[1]))
    return out


def pdf_text(content):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n".join(pg.extract_text() or "" for pg in pdf.pages)


def fetch_results(pages):
    """定審結果（category_id=1）清單 → 解析還沒抓過的 PDF，累積到 results.csv。"""
    rp, sp = OUT / "results.csv", OUT / "results_sources.json"
    done = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    rows = []
    if rp.exists():
        with rp.open(encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))
    n, failed = 0, []
    for p in range(1, pages + 1):
        page = C.http(LIST, {"category_id": 1, "page": p}, as_json=False)
        items = [(fid, title, fdate) for fid, title, fdate in _ITEMS_ANY(page)]
        if not items:
            break
        for fid, title, fdate in items:
            if fid in done:
                continue
            try:
                parsed = parse_result(pdf_text(C.http(PDF.format(fid), raw=True)), title)
            except Exception as e:  # noqa: BLE001
                failed.append(fid)
                print(f"  定審結果 {fid} {title} 失敗：{e}", file=sys.stderr)
                continue
            for idx, eff, adds, dels in parsed:
                for act, lst in (("add", adds), ("del", dels)):
                    for code, name in lst:
                        rows.append({"index": idx, "announce_date": fdate, "effective_date": eff or "",
                                     "action": act, "code": code, "name": name, "source_id": fid})
                if not adds and not dels:  # 沒有異動也記一筆，網頁才知道已公告
                    rows.append({"index": idx, "announce_date": fdate, "effective_date": eff or "",
                                 "action": "none", "code": "", "name": "", "source_id": fid})
            done[fid] = {"title": title, "file_date": fdate, "indexes": len(parsed)}
            n += 1
            time.sleep(0.4)
    rows.sort(key=lambda r: (r["announce_date"], r["index"], r["action"], r["code"]))
    write_csv(rp, RES_COLS, rows)
    sp.write_text(json.dumps(done, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"定審結果：新解析 {n} 份，累計 {len(done)} 份、{len(rows)} 筆，失敗 {len(failed)}")
    return failed


def _ITEMS_ANY(page):
    """清單頁所有項目（不限日程表）：[(id, 標題, 檔案日期)]"""
    out, seen = [], set()
    for date, title, fid in _ITEM.findall(page):
        if fid not in seen:
            seen.add(fid)
            out.append((fid, re.sub(r"\s+", " ", title).strip(), C.iso(date.strip())))
    return out


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
    """證交所上市 ETF 基本資料 → [{etf, name, index}]。"""
    try:
        info = C.http(ETF_INFO)
    except C.AdapterError as e:
        print(f"ETF 基本資料抓取失敗：{e}", file=sys.stderr)
        return None
    rows = []
    for r in info or []:
        idx = html.unescape(r.get("標的指數/追蹤指數名稱") or "").strip()
        code = (r.get("基金代號") or "").strip()
        if code and idx:
            rows.append({"etf": code, "name": (r.get("基金簡稱") or "").strip(), "index": idx})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, default=1, help="讀日程表清單前幾頁（第一次回補用 3，平常 1）")
    ap.add_argument("--result-pages", type=int, default=1, help="讀定審結果清單前幾頁（第一次回補用 25，平常 1）")
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
    if etfs:
        write_csv(OUT / "etf_index.csv", ["etf", "name", "index"], sorted(etfs, key=lambda e: e["etf"]))
        tip = {index_key(r["index"]) for r in rows}
        print(f"追蹤 TIP 指數的上市 ETF：{sum(1 for e in etfs if index_key(e['index']) in tip)} 檔")
    print(f"日程表：解析 {n_new} 份，共 {len(rows)} 筆指數審核，失敗 {len(failed)}")
    failed += fetch_results(a.result_pages)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
