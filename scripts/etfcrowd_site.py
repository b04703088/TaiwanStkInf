"""ETF 擁擠度頁（site/etfcrowd.html）→ data/etf/crowd.json

用本站收錄的全部台股 ETF 每日完整持股（data/etf/<ETF>/<日期>.csv，主動＋被動），每檔 ETF 取最新一份。
  擠度     個股被 ETF 合計持有的股數、市值、占集保總股數（近似發行股數）、要幾天成交量才消化得完（÷ 近 20 日均量）。
  申贖帶動 被動式 ETF 近 5 個交易日因申購買回而被動買賣的股數：前一份持股 × (本次單位數 ÷ 前次單位數 − 1)，
           逐日累加；換股（成分股調整）不算。主動式 ETF 是經理人自己決定，不算在這裡。
  重疊度   規模前 14 大 ETF 兩兩之間：Σ min(權重A, 權重B)（100% ＝ 持股一模一樣）。
"""
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import etf_site  # noqa: E402

STOCK = re.compile(r"^[1-9]\d{3}$")
MIN_VAL = 5e8        # 擠度表：ETF 合計持有市值 ≥ 5 億
FLOW_N = 5
TOP_N = 14


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def build(data_dir):
    data_dir = Path(data_dir)
    edir = data_dir / "etf"
    lst = {r["etf"]: r for r in _read(edir / "etf_list.csv")} if (edir / "etf_list.csv").exists() else {}
    prices = sorted(data_dir.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    prices = [p for p in prices if len(p.stem) == 8][-20:]
    if not prices:
        return None
    px = {r["code"]: r for r in _read(prices[-1])}
    vol = {}
    for p in prices:
        for r in _read(p):
            v = _f(r["volume"])
            if v:
                vol[r["code"]] = vol.get(r["code"], 0) + v / len(prices)
    tdcc = sorted((data_dir / "tdcc").glob("*.csv"))
    shares = {r["code"]: _f(r["shares"]) for r in _read(tdcc[-1])} if tdcc else {}
    units = etf_site._units_book(data_dir)
    aum_rows = sorted((edir / "aum").glob("[0-9]*.csv"))
    aum = {r["etf"]: _f(r["aum"]) for r in _read(aum_rows[-1])} if aum_rows else {}
    hold, w, flow, etfs = {}, {}, {}, []
    trading = [f"{p.stem[:4]}-{p.stem[4:6]}-{p.stem[6:]}" for p in prices]
    since = trading[-FLOW_N - 1] if len(trading) > FLOW_N else trading[0]
    for d in sorted(p for p in edir.iterdir() if p.is_dir() and re.match(r"^\d{4,6}[A-Z]?$", p.name)):
        files = sorted(d.glob("[0-9]*.csv"))
        if not files:
            continue
        e = d.name
        kind = (lst.get(e) or {}).get("kind") or ("active" if e.endswith("A") else "passive")
        last = _read(files[-1])
        if not last:
            continue
        hd = last[0]["date"]
        if hd < trading[0]:   # 一個月沒更新的不算
            continue
        name = (lst.get(e) or {}).get("name") or e
        ws = {}
        for r in last:
            c, s = r["code"], _f(r["shares"])
            if not STOCK.match(c) or not s:
                continue
            h = hold.setdefault(c, {"sh": 0.0, "n": 0, "top": None, "top_sh": 0.0})
            h["sh"] += s
            h["n"] += 1
            if s > h["top_sh"]:
                h["top"], h["top_sh"] = e, s
            wt = _f(r.get("weight"))
            if wt:
                ws[c] = wt
        w[e] = ws
        etfs.append([e, name, kind, aum.get(e), hd, len(ws)])
        if kind != "passive":
            continue
        # 近 5 日申贖帶動
        seq = [f for f in files if f.stem >= since.replace("-", "")]
        prev = None
        for f in [f for f in files if f.stem < since.replace("-", "")][-1:] + seq:
            rows = _read(f)
            if not rows:
                continue
            dd = rows[0]["date"]
            cur = {r["code"]: _f(r["shares"]) or 0 for r in rows if STOCK.match(r["code"])}
            u = units.get((e, dd))
            if prev is not None and u and prev[2]:
                k = u / prev[2] - 1
                for c, s in prev[1].items():
                    if c in cur:   # 換股剔除的不算
                        flow[c] = flow.get(c, 0) + s * k
            prev = (dd, cur, u)
    rows = []
    for c, h in hold.items():
        p = px.get(c)
        if not p:
            continue
        cl = _f(p["close"])
        mv = h["sh"] * cl if cl else 0
        if mv < MIN_VAL:
            continue
        sh, v = shares.get(c), vol.get(c)
        fl = flow.get(c, 0)
        rows.append([c, p["name"], h["n"], round(h["sh"] / 1000), round(mv / 1e8, 1),
                     round(h["sh"] / sh * 100, 2) if sh else None, round(h["sh"] / v, 1) if v else None,
                     round(fl / 1000), round(fl * cl / 1e8, 2) if cl else None,
                     round(fl / v * 100, 1) if v else None, h["top"]])
    rows.sort(key=lambda r: -(r[5] or 0))
    # 重疊度
    top = [x for x in sorted(etfs, key=lambda x: -(x[3] or 0)) if x[3] and w.get(x[0])][:TOP_N]
    names = [[x[0], x[1]] for x in top]
    mat = [[round(sum(min(w[a[0]].get(k, 0), v) for k, v in w[b[0]].items())) for b in top] for a in top]
    fl_rows = sorted(([c, px[c]["name"], round(v / 1000), round(v * _f(px[c]["close"]) / 1e8, 2)] for c, v in flow.items()
                      if c in px and _f(px[c]["close"])), key=lambda r: -abs(r[3]))
    return {"date": trading[-1], "flow_since": since, "n_etf": len(etfs),
            "cols": ["code", "name", "n", "lots", "mv", "pct", "days", "flow", "flow_amt", "flow_vol", "top"], "rows": rows,
            "flow_top": fl_rows[:60], "overlap": {"etfs": names, "m": mat},
            "etfs": etfs}


def write(data_dir, out_path):
    j = build(data_dir)
    if j is None:
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    j = build(Path(__file__).resolve().parent.parent / "data")
    print(j["date"], j["flow_since"], j["n_etf"], len(j["rows"]))
    for r in j["rows"][:8]:
        print(r)
    print(j["flow_top"][:6])
    print(j["overlap"]["etfs"])
    print(j["overlap"]["m"][:3])
