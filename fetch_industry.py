#!/usr/bin/env python3
"""個股產業細分類。

資料來源（公開、免登入）
  1. 櫃買中心「產業價值鏈資訊平台」https://ic.tpex.org.tw/
     約 50 個產業，每個產業分上／中／下游 → 類別（例：IC設計）→ 細類（例：電源管理IC），
     各列出上市、上櫃、興櫃公司。一檔股票可以屬於多個細類。
  2. 證交所／櫃買中心 OpenAPI 公司基本資料的「產業別」代碼（官方分類，約 40 類），
     給價值鏈平台沒涵蓋的股票當備援。

輸出 data/industry/
  chain.csv     code, name, industry_id, industry, stream, node_id, node, sub_id, sub
  official.csv  code, name, market, ind_code, industry
  sources.json  抓取時間、各產業筆數、錯誤

用法：python fetch_industry.py
"""
import csv
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "industry"
IC = "https://ic.tpex.org.tw/"
CO_TWSE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
CO_TPEX = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
CO_EMG = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R"
DELAY = 1.0

CHAIN_COLS = ["code", "name", "industry_id", "industry", "stream", "node_id", "node", "sub_id", "sub"]
OFF_COLS = ["code", "name", "market", "ind_code", "industry"]

# 證交所／櫃買「產業別」代碼
OFFICIAL = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維", "05": "電機機械", "06": "電器電纜",
    "08": "玻璃陶瓷", "09": "造紙工業", "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險", "18": "貿易百貨", "19": "綜合", "20": "其他",
    "21": "化學工業", "22": "生技醫療", "23": "油電燃氣", "24": "半導體", "25": "電腦及週邊設備", "26": "光電",
    "27": "通信網路", "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子", "32": "文化創意",
    "33": "農業科技", "34": "電子商務", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒", "38": "居家生活",
    "80": "管理股票", "91": "存託憑證",
}


def _clean(s):
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).replace(" ", "")


def parse_industries(page):
    """產業下拉選單 → [(id, 名稱)]"""
    out = []
    for v, name in re.findall(r"<option value='(\w+)'[^>]*>([^<]+)</option>", page):
        if (v, name.strip()) not in out:
            out.append((v, name.strip()))
    return out


def parse_chain(page, ind_id, ind_name):
    """產業鏈頁面 → [{code,name,industry_id,industry,stream,node_id,node,sub_id,sub}]"""
    # 上中下游：鏈圖裡 ic_link_XXXX 出現在哪個「上游／中游／下游」標題之後
    stream_of, cur = {}, ""
    for m in re.finditer(r'chain-title-panel">\s*([^<]+?)\s*<|id="ic_link_(\w+)"', page):
        if m.group(1):
            cur = m.group(1).strip()
        else:
            stream_of.setdefault(m.group(2), cur)
    sub_name = {k: re.sub(r"\(\d+家\)$", "", _clean(v)).lstrip("►▶") for k, v in
                re.findall(r'id="sc_link_(\w+)"[^>]*>(.*?)</div>', page, re.S)}
    rows, seen = [], set()
    blocks = re.split(r'(?=<div id="companyList_)', page)
    for b in blocks:
        m = re.match(r'<div id="companyList_(\w+)" title="([^"]*)"', b)
        if not m:
            continue
        node_id, node = m.group(1), _clean(m.group(2))
        tables = re.split(r'(?=<table id="sc_company_)', b)
        for t in tables:
            tm = re.match(r'<table id="sc_company_(\w+)"', t)
            sub_id = tm.group(1) if tm else ""
            if sub_id.startswith("count_"):
                continue
            for code, name in re.findall(r'company_basic\.php\?stk_code=(\w+)"[^>]*title="([^"]*)"', t):
                k = (code, node_id, sub_id)
                if k in seen:
                    continue
                seen.add(k)
                rows.append({"code": code, "name": html.unescape(name), "industry_id": ind_id, "industry": ind_name,
                             "stream": stream_of.get(node_id, ""), "node_id": node_id, "node": node,
                             "sub_id": sub_id, "sub": sub_name.get(sub_id, "")})
    # 節點下面有細類時，節點本身那張表通常是「全部公司」，和細類重複 → 只留沒有被細類涵蓋的
    with_sub = {(r["code"], r["node_id"]) for r in rows if r["sub_id"]}
    return [r for r in rows if r["sub_id"] or (r["code"], r["node_id"]) not in with_sub]


def fetch_official():
    rows = []
    for url, market, code_k, name_k, ind_k in ((CO_TWSE, "上市", "公司代號", "公司簡稱", "產業別"),
                                               (CO_TPEX, "上櫃", "SecuritiesCompanyCode", "CompanyAbbreviation", "SecuritiesIndustryCode"),
                                               (CO_EMG, "興櫃", "SecuritiesCompanyCode", "CompanyAbbreviation", "SecuritiesIndustryCode")):
        try:
            for c in C.http(url):
                code = (c.get(code_k) or "").strip()
                ind = (c.get(ind_k) or "").strip()
                if code:
                    rows.append({"code": code, "name": (c.get(name_k) or "").strip(), "market": market,
                                 "ind_code": ind, "industry": OFFICIAL.get(ind, ind)})
        except Exception as e:  # noqa: BLE001
            print(f"公司基本資料 {market} 失敗：{e}", file=sys.stderr)
    return rows


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    errors, counts = [], {}
    off = fetch_official()
    if len(off) > 1500:
        _write(OUT / "official.csv", OFF_COLS, sorted(off, key=lambda r: r["code"]))
    else:
        errors.append(f"官方產業別只抓到 {len(off)} 筆，沿用舊檔")

    chain = []
    try:
        first = C.http(IC + "introduce.php?ic=D000", as_json=False)
        inds = parse_industries(first)
        if not any(i == "D000" for i, _ in inds):
            inds.insert(0, ("D000", "半導體"))
    except C.AdapterError as e:
        errors.append(f"產業價值鏈首頁：{e}")
        inds, first = [], ""
    for ind_id, ind_name in inds:
        try:
            page = first if ind_id == "D000" else C.http(IC + f"introduce.php?ic={ind_id}", as_json=False)
            rows = parse_chain(page, ind_id, ind_name)
            counts[ind_name] = len(rows)
            chain += rows
            if not rows:
                errors.append(f"{ind_name}（{ind_id}）沒有解析到公司")
        except C.AdapterError as e:
            errors.append(f"{ind_name}（{ind_id}）：{e}")
        time.sleep(DELAY)
    if len(chain) > 3000:
        chain.sort(key=lambda r: (r["code"], r["industry_id"], r["node_id"], r["sub_id"]))
        _write(OUT / "chain.csv", CHAIN_COLS, chain)
    else:
        errors.append(f"產業鏈只抓到 {len(chain)} 筆，沿用舊檔")

    (OUT / "sources.json").write_text(json.dumps({
        "generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "industries": counts,
        "chain_rows": len(chain), "chain_stocks": len({r["code"] for r in chain}), "official": len(off),
        "errors": errors}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"產業鏈 {len(inds)} 個產業、{len(chain)} 筆（{len({r['code'] for r in chain})} 檔）；官方產業別 {len(off)} 檔")
    for e in errors:
        print("錯誤：" + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
