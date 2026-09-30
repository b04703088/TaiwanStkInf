#!/usr/bin/env python3
"""抓取台股 ETF 每日持股明細（成分股、總股數、權重），存成 CSV。

用法:
    python fetch_etf.py                  # 抓 ETF_LIST 全部
    python fetch_etf.py 0050 00981A      # 只抓指定 ETF
    python fetch_etf.py --issuer ctbc    # 只抓某家投信

輸出:
    data/etf/<ETF代號>/<YYYYMMDD>.csv   欄位見 COLUMNS；檔名日期是持股基準日
    data/etf/summary.csv                每檔每日：基金規模、流通單位數、淨值、持股檔數
    data/etf/etf_list.csv               追蹤中的 ETF 清單（代號、名稱、投信、類型）

各投信的 adapter 在 etf_adapters.py。重複執行只會覆寫同一天，假日不會產生重複日期。
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import etf_adapters as A
from etf_common import TPE, AdapterError

ROOT = Path(__file__).resolve().parent
ETF_DIR = ROOT / "data" / "etf"
COLUMNS = ["date", "etf", "code", "name", "shares", "weight"]
SUMMARY_COLUMNS = ["date", "etf", "aum", "units", "nav", "holdings", "fetched_at"]

ISSUER_NAMES = {
    "yuanta": "元大", "fubon": "富邦", "cathay": "國泰", "capital": "群益", "fuhhwa": "復華",
    "president": "統一", "ctbc": "中信", "nomura": "野村", "allianz": "安聯", "kgi": "凱基",
    "taishin": "台新", "sinopac": "永豐", "mega": "兆豐", "firstsec": "第一金", "ab": "聯博", "jpmorgan": "摩根",
    "franklin": "富蘭克林華美", "uob": "大華銀", "esun": "玉山", "union": "聯邦", "hnitc": "華南永昌",
}

# (代號, 名稱, 投信, 類型)。名稱用交易所簡稱（凱基、兆豐靠名稱對應內部代碼）。
# 同一家投信加 ETF 只要加一行；新投信要在 etf_adapters.py 多寫一個 adapter。
ETF_LIST = [
    # ---- 市值型 / 高股息 / 主題（被動）----
    ("0050", "元大台灣50", "yuanta", "passive"),
    ("0056", "元大高股息", "yuanta", "passive"),
    ("00713", "元大台灣高息低波", "yuanta", "passive"),
    ("00850", "元大臺灣ESG永續", "yuanta", "passive"),
    ("00940", "元大台灣價值高息", "yuanta", "passive"),
    ("006208", "富邦台50", "fubon", "passive"),
    ("00692", "富邦公司治理", "fubon", "passive"),
    ("00892", "富邦台灣半導體", "fubon", "passive"),
    ("00900", "富邦特選高股息30", "fubon", "passive"),
    ("00878", "國泰永續高股息", "cathay", "passive"),
    ("00881", "國泰台灣科技龍頭", "cathay", "passive"),
    ("00919", "群益台灣精選高息", "capital", "passive"),
    ("00927", "群益半導體收益", "capital", "passive"),
    ("00946", "群益科技高息成長", "capital", "passive"),
    ("00929", "復華台灣科技優息", "fuhhwa", "passive"),
    ("00891", "中信關鍵半導體", "ctbc", "passive"),
    ("00915", "凱基優選高股息30", "kgi", "passive"),
    ("00935", "野村臺灣新科技50", "nomura", "passive"),
    ("00939", "統一台灣高息動能", "president", "passive"),
    # ---- 其他國內股票型（被動）----
    ("009816", "凱基台灣TOP50", "kgi", "passive"),
    ("0052", "富邦科技", "fubon", "passive"),
    ("00922", "國泰台灣領袖50", "cathay", "passive"),
    ("00923", "群益台ESG低碳50", "capital", "passive"),
    ("00896", "中信綠能及電動車", "ctbc", "passive"),
    ("00934", "中信成長高股息", "ctbc", "passive"),
    ("00947", "台新臺灣IC設計", "taishin", "passive"),
    ("009802", "富邦旗艦50", "fubon", "passive"),
    ("00894", "中信小資高價30", "ctbc", "passive"),
    ("00701", "國泰股利精選30", "cathay", "passive"),
    ("00904", "台新臺灣半導體30", "taishin", "passive"),
    ("00952", "凱基台灣AI50", "kgi", "passive"),
    ("00733", "富邦臺灣中小", "fubon", "passive"),
    ("0055", "元大MSCI金融", "yuanta", "passive"),
    ("00936", "台新永續高息中小", "taishin", "passive"),
    ("00930", "永豐ESG低碳高息", "sinopac", "passive"),
    ("0051", "元大中型100", "yuanta", "passive"),
    ("00901", "永豐智能車供應鏈", "sinopac", "passive"),
    ("00938", "凱基優選30", "kgi", "passive"),
    ("00728", "第一金工業30", "firstsec", "passive"),
    ("00907", "永豐優息存股", "sinopac", "passive"),
    ("0053", "元大電子", "yuanta", "passive"),
    ("00912", "中信臺灣智慧50", "ctbc", "passive"),
    ("006203", "元大MSCI台灣", "yuanta", "passive"),
    ("00730", "富邦臺灣優質高息", "fubon", "passive"),
    ("00731", "復華富時高息低波", "fuhhwa", "passive"),
    ("00962", "台新AI優息動能", "taishin", "passive"),
    ("00944", "野村趨勢動能高息", "nomura", "passive"),
    ("009809", "富邦淨零ESG50", "fubon", "passive"),
    ("0057", "富邦摩台", "fubon", "passive"),
    ("006204", "永豐臺灣加權", "sinopac", "passive"),
    ("00888", "永豐台灣ESG", "sinopac", "passive"),
    ("00928", "中信上櫃ESG 30", "ctbc", "passive"),
    ("006201", "元大富櫃50", "yuanta", "passive"),
    ("00918", "大華優利高填息30", "uob", "passive"),
    ("00961", "FT臺灣永續高息", "franklin", "passive"),
    ("00905", "FT臺灣Smart", "franklin", "passive"),
    ("009803", "玉山市值動能50", "esun", "passive"),
    ("009804", "聯邦台精彩50", "union", "passive"),
    ("009808", "華南永昌優選50", "hnitc", "passive"),
    # ---- 主動式 ----
    ("00400A", "主動國泰動能高息", "cathay", "active"),
    ("00401A", "主動摩根台灣鑫收", "jpmorgan", "active"),
    ("00402A", "主動安聯美國科技", "allianz", "active"),
    ("00403A", "主動統一升級50", "president", "active"),
    ("00404A", "主動聯博動能50", "ab", "active"),
    ("00405A", "主動富邦台灣龍耀", "fubon", "active"),
    ("00406A", "主動中信台灣收益", "ctbc", "active"),
    ("00407A", "主動凱基台灣", "kgi", "active"),
    ("00408A", "主動第一金優股息", "firstsec", "active"),
    ("00409A", "主動復華全球50", "fuhhwa", "active"),
    ("00410A", "主動永豐科技趨勢", "sinopac", "active"),
    ("00411A", "主動統一前沿科技", "president", "active"),
    ("00980A", "主動野村臺灣優選", "nomura", "active"),
    ("00981A", "主動統一台股增長", "president", "active"),
    ("00982A", "主動群益台灣強棒", "capital", "active"),
    ("00983A", "主動中信ARK創新", "ctbc", "active"),
    ("00984A", "主動安聯台灣高息", "allianz", "active"),
    ("00985A", "主動野村台灣50", "nomura", "active"),
    ("00986A", "主動台新龍頭成長", "taishin", "active"),
    ("00987A", "主動台新優勢成長", "taishin", "active"),
    ("00988A", "主動統一全球創新", "president", "active"),
    ("00989A", "主動摩根美國科技", "jpmorgan", "active"),
    ("00990A", "主動元大AI新經濟", "yuanta", "active"),
    ("00991A", "主動復華未來50", "fuhhwa", "active"),
    ("00992A", "主動群益科技創新", "capital", "active"),
    ("00993A", "主動安聯台灣", "allianz", "active"),
    ("00994A", "主動第一金台股優", "firstsec", "active"),
    ("00995A", "主動中信台灣卓越", "ctbc", "active"),
    # 00996A 主動兆豐台灣豐收：兆豐投信網站對 GitHub Actions 的主機回 403（2026-09-29 測試），暫不追蹤；
    # adapter（etf_adapters.mega）保留，換到其他主機執行時可加回：("00996A", "主動兆豐台灣豐收", "mega", "active")
    ("00997A", "主動群益美國增長", "capital", "active"),
    ("00998A", "主動復華金融股息", "fuhhwa", "active"),
    ("00999A", "主動野村臺灣高息", "nomura", "active"),
]


# ---------------- 檢查 / 補齊 ----------------
def validate(code, rows):
    if len(rows) < 5:
        raise AdapterError(f"{code}: 只有 {len(rows)} 檔成分股，資料可能不完整")
    codes = [r["code"] for r in rows]
    if len(set(codes)) != len(codes):
        raise AdapterError(f"{code}: 成分股代號重複")
    tw = sum(r["weight"] for r in rows if r["weight"] is not None)
    if tw > 105:
        raise AdapterError(f"{code}: 權重加總 {tw:.1f}% 不合理")


def load_market(d):
    """台股收盤：{代號: (收盤價, 交易所簡稱)}。優先用同一天；還沒有當天行情時，
    改用最近一個交易日的行情（只拿來統一名稱，價格不可用 → 不換算權重）。"""
    files = sorted((ROOT / "data").glob("[0-9][0-9][0-9][0-9]/*.csv"), key=lambda p: p.name)
    target = f"{d.replace('-', '')}.csv"
    same = [f for f in files if f.name == target]
    f = same[0] if same else next((f for f in reversed(files) if f.name < target), None)
    if not f:
        return {}
    with f.open(encoding="utf-8") as fp:
        rows = {r["code"]: (float(r["close"]) if same else None, r["name"])
                for r in csv.DictReader(fp) if r.get("close")}
    return rows


def normalize_names(rows, market):
    """各投信對同一檔股票的寫法不同（華碩 / 華碩電腦），台股統一用交易所簡稱。"""
    for r in rows:
        if r["code"] in market:
            r["name"] = market[r["code"]][1]


def fill_weights(rows, market):
    """投信沒給權重時，用股數 × 收盤價換算股票部位內的權重（只限台股都有價格時）。"""
    if all(r["weight"] is not None for r in rows):
        return False
    if any(r["weight"] is None and (r["code"] not in market or market[r["code"]][0] is None) for r in rows):
        return False
    mv = {r["code"]: r["shares"] * market[r["code"]][0] for r in rows
          if r["shares"] is not None and r["code"] in market}
    total = sum(mv.values())
    if not total:
        return False
    for r in rows:
        if r["weight"] is None and r["code"] in mv:
            r["weight"] = round(mv[r["code"]] / total * 100, 4)
    return True


# ---------------- 輸出 ----------------
def write_day(etf, d, rows):
    out = ETF_DIR / etf / f"{d.replace('-', '')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda r: (-(r["weight"] or 0), r["code"]))
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({"date": d, "etf": etf, **r})
    return out


def update_summary(entries):
    path = ETF_DIR / "summary.csv"
    existing = {}
    if path.exists():
        with path.open(encoding="utf-8") as fp:
            for r in csv.DictReader(fp):
                existing[(r["date"], r["etf"])] = r
    for e in entries:
        existing[(e["date"], e["etf"])] = e
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=SUMMARY_COLUMNS)
        w.writeheader()
        for k in sorted(existing):
            w.writerow({c: existing[k].get(c, "") for c in SUMMARY_COLUMNS})


def write_etf_list():
    path = ETF_DIR / "etf_list.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(["etf", "name", "issuer", "issuer_name", "kind"])
        for code, name, issuer, kind in ETF_LIST:
            w.writerow([code, name, issuer, ISSUER_NAMES[issuer], kind])


def load_source_ids():
    p = ETF_DIR / "source_ids.json"
    if p.exists():
        A.SOURCE_IDS.update(json.loads(p.read_text(encoding="utf-8")))


def save_source_ids():
    if A.SOURCE_IDS:
        p = ETF_DIR / "source_ids.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(A.SOURCE_IDS, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("etfs", nargs="*", help="只抓這些 ETF 代號")
    ap.add_argument("--issuer", help="只抓某家投信（adapter 名稱，如 ctbc）")
    args = ap.parse_args(argv)

    targets = [t for t in ETF_LIST
               if (not args.etfs or t[0] in args.etfs) and (not args.issuer or t[2] == args.issuer)]
    unknown = set(args.etfs) - {t[0] for t in ETF_LIST}
    if unknown:
        print(f"未知的 ETF：{sorted(unknown)}（請先加到 ETF_LIST）", file=sys.stderr)

    load_source_ids()
    write_etf_list()
    now = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    summary, failed = [], []
    for code, name, issuer, _kind in targets:
        try:
            d, rows, meta = A.ADAPTERS[issuer](code, name)
            market = load_market(d)
            normalize_names(rows, market)
            derived = fill_weights(rows, market)
            validate(code, rows)
            out = write_day(code, d, rows)
            summary.append({"date": d, "etf": code, "aum": meta.get("aum") or "", "units": meta.get("units") or "",
                            "nav": meta.get("nav") or "", "holdings": len(rows), "fetched_at": now})
            print(f"{code} {name}: {d} {len(rows)} 檔{'（權重由股數×收盤價換算）' if derived else ''} -> {out.relative_to(ROOT)}")
        except Exception as e:  # noqa: BLE001  一檔失敗不影響其他
            print(f"{code} {name}: 失敗 {e}", file=sys.stderr)
            failed.append(code)
    if summary:
        update_summary(summary)
    save_source_ids()
    print(f"完成：成功 {len(summary)}、失敗 {len(failed)}{'：' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
