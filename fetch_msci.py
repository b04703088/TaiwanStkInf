#!/usr/bin/env python3
"""MSCI 指數季度審核：MSCI Taiwan Index（標準型）的成分股納入／刪除，以及未來審核日期。

資料來源（MSCI 公開資料）：
  審核頁 https://app2.msci.com/eqb/gimi/stdindex/index_review.html → 各期「MSCI Global Standard Indexes
       List of Additions/Deletions」PDF（MSCI_<Mon><YY>_STPublicList.pdf），取 MSCI TAIWAN INDEX 段
  日期   https://app2.msci.com/eqb/pressreleases/archive/ir_dates.csv（未來八次審核的公告日、生效日）
  代號對應：MSCI 名單只有英文名稱，用證交所／櫃買中心公司基本資料（英文簡稱、網址、e-mail 網域）比對；
           對不準的寫在 config/msci_names.csv（en_name,code）手動指定，優先採用。

輸出 data/etf/msci/：
  results.csv   review, index, announce_date, effective_date, action(add/del), en_name, code
  schedule.csv  review, announce_date, effective_date（MSCI 公布的未來審核日期）
  companies.csv 代號比對用的公司英文資料快取
  sources.json  已解析的 PDF

生效日 = MSCI「as of the close of X」的下一個交易日（X 收盤後生效，ETF 在 X 收盤調整）。
用法：python fetch_msci.py [--since 23]   只抓 20YY 年以後的審核（預設 2023）
"""
import argparse
import csv
import difflib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "etf" / "msci"
BASE = "https://app2.msci.com"
REVIEW_PAGE = BASE + "/eqb/gimi/stdindex/index_review.html"
IR_DATES = BASE + "/eqb/pressreleases/archive/ir_dates.csv"
CO_TWSE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
CO_TPEX = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
RES_COLS = ["review", "index", "announce_date", "effective_date", "action", "en_name", "code"]
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
STOP = {"CORP", "CO", "CO.", "INC", "LTD", "IND", "INDL", "INDUSTRIAL", "COMPANY", "HOLDINGS", "HOLDING", "GROUP",
        "TECH", "TECHNOLOGY", "TECHNOLOGIES", "INTL", "INTERNATIONAL", "ENTERPRISE", "ELECTRONICS", "ELECTRONIC",
        "(THE)", "&"}


def _en_date(s):
    return datetime.strptime(re.sub(r"\s+", " ", s.strip()), "%B %d, %Y").date() if s else None


def next_weekday(d):
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def parse_list_pdf(content, country="TAIWAN"):
    """MSCI 異動名單 PDF → (公告日, 收盤生效日, 納入[英文名], 刪除[英文名])。依文字 x 座標分左右兩欄。"""
    import pdfplumber
    adds, dels, in_sec, del_x = [], [], False, None
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        head = (pdf.pages[0].extract_text() or "").replace("\n", " ")
        m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", head)
        ann = _en_date(m.group(1)) if m else None
        m = re.search(r"as of the close of\s+([A-Z][a-z]+ \d{1,2},\s*\d{4})", head)
        close = _en_date(m.group(1)) if m else None
        for pg in pdf.pages:
            lines = {}
            for w in pg.extract_words():
                lines.setdefault(round(w["top"] / 3), []).append(w)
            for k in sorted(lines):
                ws = sorted(lines[k], key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in ws)
                if re.match(r"MSCI .* INDEX$", text):
                    in_sec, del_x = text == f"MSCI {country} INDEX", None
                    continue
                if not in_sec or text.startswith("Page ") or "All rights reserved" in text:
                    continue
                if ws[0]["text"] == "Additions" and any(w["text"] == "Deletions" for w in ws):
                    del_x = next(w["x0"] for w in ws if w["text"] == "Deletions") - 4
                    continue
                if del_x is None:
                    continue
                left = " ".join(w["text"] for w in ws if w["x0"] < del_x).strip()
                right = " ".join(w["text"] for w in ws if w["x0"] >= del_x).strip()
                if left and left != "None":
                    adds.append(left)
                if right and right != "None":
                    dels.append(right)
    return ann, close, adds, dels


# ---------------- 英文名稱 → 股票代號 ----------------
def _dom(u):
    m = re.search(r"(?:https?://)?(?:www\.)?([a-z0-9\-]+)\.", (u or "").lower())
    return m.group(1) if m else ""


def load_companies(refresh=True):
    p = OUT / "companies.csv"
    rows = []
    if refresh:
        try:
            for c in C.http(CO_TWSE):
                rows.append({"code": c["公司代號"], "name": c["公司簡稱"], "abbr": (c.get("英文簡稱") or "").strip(),
                             "web": _dom(c.get("網址")), "mail": _dom((c.get("電子郵件信箱") or "").split("@")[-1])})
            for c in C.http(CO_TPEX):
                rows.append({"code": c["SecuritiesCompanyCode"], "name": c["CompanyAbbreviation"],
                             "abbr": (c.get("Symbol") or "").strip(), "web": _dom(c.get("WebAddress")),
                             "mail": _dom((c.get("EmailAddress") or "").split("@")[-1])})
        except Exception as e:  # noqa: BLE001
            print(f"公司基本資料抓取失敗，改用快取：{e}", file=sys.stderr)
            rows = []
    if len(rows) > 1000:
        _write(p, ["code", "name", "abbr", "web", "mail"], rows)
        return rows
    if p.exists():
        with p.open(encoding="utf-8") as fp:
            return list(csv.DictReader(fp))
    return rows


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _score(name, c):
    words = [w for w in re.split(r"[\s\-]+", name.upper()) if w]
    core = [w for w in words if w not in STOP] or words
    cj = _norm("".join(core))
    acr = {"".join(w[0] for w in words).lower(), "".join(w[0] for w in core).lower()}
    best = 0.0
    for d in {_norm(c["web"]), _norm(c["mail"])} - {""}:
        if len(d) < 3:
            continue
        r = difflib.SequenceMatcher(None, cj, d).ratio()
        if cj.startswith(d) or d.startswith(cj[:max(4, len(d))]):
            r = max(r, 0.8 if len(d) >= 5 else 0.6)
        best = max(best, r)
    ab = _norm(c["abbr"])
    if ab:
        if ab in acr:
            best = max(best, 0.85)
        elif ab == _norm(core[0]):
            best = max(best, 0.9)
        elif len(ab) >= 4 and cj.startswith(ab):
            best = max(best, 0.8)
        else:
            best = max(best, difflib.SequenceMatcher(None, cj, ab).ratio() * 0.8)
    return best


def map_name(name, companies, overrides):
    """英文名 → 代號；手動對照優先，自動比對要夠確定（分數 ≥ 0.8 且明顯勝過第二名）才採用。"""
    if name in overrides:
        return overrides[name]
    sc = sorted(((_score(name, c), c["code"]) for c in companies), reverse=True)[:2]
    if sc and sc[0][0] >= 0.8 and (len(sc) < 2 or sc[0][0] - sc[1][0] >= 0.05):
        return sc[0][1]
    return ""


def load_overrides():
    p = ROOT / "config" / "msci_names.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8-sig") as fp:
        return {r["en_name"].strip(): r["code"].strip() for r in csv.DictReader(fp) if r.get("en_name") and r.get("code")}


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def parse_ir_dates(text):
    out = []
    for m in re.finditer(r"([A-Z][a-z]{2}), (\d{4})\|\"*Index Review\"*\|(\d{2})-(\d{2})-(\d{4})\|(\d{2})-(\d{2})-(\d{4})", text):
        mon, yr, am, ad, ay, em, ed, ey = m.groups()
        out.append({"review": f"{yr}-{MONTHS[mon]:02d}", "announce_date": f"{ay}-{am}-{ad}", "effective_date": f"{ey}-{em}-{ed}"})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=int, default=23, help="只抓 20YY 年以後的審核（預設 23）")
    a = ap.parse_args(argv)

    # 未來審核日期
    try:
        sched = parse_ir_dates(C.http(IR_DATES, as_json=False))
        if sched:
            old = []
            if (OUT / "schedule.csv").exists():
                with (OUT / "schedule.csv").open(encoding="utf-8") as fp:
                    old = list(csv.DictReader(fp))
            merged = {r["review"]: r for r in old}
            merged.update({r["review"]: r for r in sched})
            _write(OUT / "schedule.csv", ["review", "announce_date", "effective_date"], sorted(merged.values(), key=lambda r: r["review"]))
    except C.AdapterError as e:
        print(f"MSCI 審核日期抓取失敗：{e}", file=sys.stderr)

    # 歷次名單
    sp = OUT / "sources.json"
    done = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    raw_p = OUT / "raw.csv"   # 英文名原始名單（代號每次重新比對）
    raw = []
    if raw_p.exists():
        with raw_p.open(encoding="utf-8") as fp:
            raw = list(csv.DictReader(fp))
    page = C.http(REVIEW_PAGE, as_json=False)
    links = sorted(set(re.findall(r'href="(/eqb/gimi/stdindex/MSCI_([A-Z][a-z]{2})(\d{2})_STPublicList\.pdf)"', page)))
    failed = []
    for path, mon, yy in links:
        if int(yy) < a.since or path in done:
            continue
        review = f"20{yy}-{MONTHS[mon]:02d}"
        try:
            ann, close, adds, dels = parse_list_pdf(C.http(BASE + path, raw=True, retries=2))
        except Exception as e:  # noqa: BLE001  May 名單偶爾 403，下次再試
            failed.append(path)
            print(f"  {path} 失敗：{e}", file=sys.stderr)
            continue
        eff = next_weekday(close) if close else None
        raw = [r for r in raw if r["review"] != review]
        for act, names in (("add", adds), ("del", dels)):
            for n in names:
                raw.append({"review": review, "index": "MSCI Taiwan", "announce_date": ann.isoformat() if ann else "",
                            "effective_date": eff.isoformat() if eff else "", "action": act, "en_name": n})
        if not adds and not dels:
            raw.append({"review": review, "index": "MSCI Taiwan", "announce_date": ann.isoformat() if ann else "",
                        "effective_date": eff.isoformat() if eff else "", "action": "none", "en_name": ""})
        done[path] = {"review": review, "adds": len(adds), "dels": len(dels)}
        time.sleep(0.5)
    raw.sort(key=lambda r: (r["review"], r["action"], r["en_name"]))
    _write(raw_p, RES_COLS[:-1], raw)
    sp.write_text(json.dumps(done, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    companies, overrides = load_companies(), load_overrides()
    res = [{**r, "code": map_name(r["en_name"], companies, overrides) if r["en_name"] else ""} for r in raw]
    _write(OUT / "results.csv", RES_COLS, res)
    unmatched = sorted({r["en_name"] for r in res if r["en_name"] and not r["code"]})
    print(f"MSCI：{len(done)} 期名單、{len(res)} 筆異動，對不到代號 {len(unmatched)} 檔{'：' + '、'.join(unmatched) if unmatched else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
