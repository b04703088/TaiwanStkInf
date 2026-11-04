"""盤後摘要頁的「重點」：資金流向、追蹤分點、CB 詢圈、ETF 調整、內部人申報、主動式 ETF 大幅調倉（表格）。
目前只輸出 SECTIONS 列的段落（2026-11-03 起只有主動式 ETF 大幅調倉）。

由 scripts/digest.py 呼叫，輸出 data/digest/points/<日期>.md，同內容也接在數字摘要後面給每晚判讀用。
「這次」指上一個交易日之後到資料日 D（含週末公告）。

  資金流向  每檔個股的 法人（外資＋投信＋自營）5 日買賣超 ＋ 融資 5 日增減（億），
            依它所屬的產業鏈節點數平均分攤（台積電在幾十個節點，不分攤會讓每個節點都長得一樣），
            再加總到節點。流入、流出各列前 5，附代表股、5 日漲跌中位數、成交占比（近 5 日 vs 前 20 日）。
  追蹤分點  首頁同一區：config/broker_watch.csv 分點加總，個股淨額 ≥ 5000 萬（不含 ETF）。
  CB 詢圈   詢圈中（含常客分點有沒有進場）、即將詢圈（代收行庫公告後約 5 天）、這次訂價、
            這次董事會決議／送件／生效。
  ETF 調整  這次公告的指數成分調整、未來 14 天要公告與已公告未生效的審核（同首頁，etf_site.build_tip）、
            ETF 持股這次新增／剔除的成分股、主動式 ETF 合計加減碼前段。
  內部人    這次申報轉讓（依金額，信託另計）、最新月報市場買進／賣出前段。

用法：python scripts/digest.py（會一起產生）；單獨測試 python scripts/digest_points.py --date YYYYMMDD
"""
import argparse
import csv
import glob
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data"


def _read(p):
    p = Path(p)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _iso(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _md(iso):
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def _yi(v):
    return f"{v:+,.0f} 億" if abs(v) >= 10 else f"{v:+,.1f} 億"


def _lots(sh):
    return f"{sh / 1000:,.0f} 張"


def _tbl(heads, rows):
    """Markdown 表格；儲存格裡的 | 換成全形，避免切錯欄"""
    c = lambda v: str(v).replace("|", "｜") if v not in (None, "") else "—"
    return ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)] + \
           ["| " + " | ".join(c(v) for v in r) + " |" for r in rows]


def _n(v):
    """數字欄：億，帶正負號（網頁會上色）"""
    return f"{v:+,.0f}" if abs(v) >= 10 else f"{v:+,.1f}"


def _names():
    out = {}
    for f in sorted(glob.glob(str(D / "20[0-9][0-9]" / "*.csv")))[-3:]:
        for r in _read(f):
            out[r["code"]] = r["name"]
    for r in _read(D / "cb" / "companies.csv"):
        out.setdefault(r["code"], r.get("abbr") or r.get("name", ""))
    return out


# ───────────── 資金流向 ─────────────
def flows(px_files, chip_files, day, top=5):
    i = [Path(f).stem for f in px_files].index(day)
    if i < 25:
        return []
    rd = lambda f, cols: pd.read_csv(f, dtype={"code": str}, usecols=cols)
    P = pd.concat(rd(f, ["code", "name", "close", "value"]).assign(k=k) for k, f in enumerate(px_files[i - 24:i + 1]))
    P = P[P.code.str.len() == 4]
    P["close"] = pd.to_numeric(P.close, errors="coerce")
    now = P[P.k == 24].drop_duplicates("code").set_index("code")
    c5 = P[P.k == 19].drop_duplicates("code").set_index("code").close
    v5 = P[P.k >= 20].groupby("code").value.sum() / 1e8
    v20 = P[P.k < 20].groupby("code").value.sum() / 1e8 / 4
    closes = {Path(f).stem: rd(f, ["code", "close"]).assign(close=lambda d: pd.to_numeric(d.close, errors="coerce"))
              for f in px_files[i - 4:i + 1]}
    inst = []
    for f in [f for f in chip_files if Path(f).stem <= day][-5:]:
        c = rd(f, ["code", "inst_net"]).merge(closes.get(Path(f).stem, now.close.reset_index()), on="code")
        inst.append(c.assign(a=c.inst_net * c.close / 1e8)[["code", "a"]])
    inst = pd.concat(inst).groupby("code").a.sum() if inst else pd.Series(dtype=float)
    mg = sorted(f for f in glob.glob(str(D / "margin" / "20*" / "*.csv")) if Path(f).stem <= day)[-6:]
    if len(mg) == 6:
        fb = lambda f: rd(f, ["code", "fin_bal"]).drop_duplicates("code").set_index("code").fin_bal
        dfin = (fb(mg[-1]) - fb(mg[0])) * 1000 * now.close / 1e8
    else:
        dfin = pd.Series(dtype=float)
    m = pd.DataFrame({"name": now["name"], "close": now.close, "c5": c5, "v5": v5, "v20": v20,
                      "inst": inst, "dfin": dfin}).dropna(subset=["close"])
    m = m.fillna({"v5": 0, "v20": 0, "inst": 0, "dfin": 0})
    m["r5"] = (m.close / m.c5 - 1) * 100
    m["flow"] = m.inst + m.dfin

    ch = pd.read_csv(D / "industry" / "chain.csv", dtype={"code": str}).drop_duplicates(["code", "industry", "node"])
    ch = ch[["code", "industry", "node"]]
    ch["w"] = 1 / ch.groupby("code").code.transform("size")
    x = ch.merge(m, left_on="code", right_index=True)
    for k in ("v5", "v20", "inst", "dfin", "flow"):
        x[k + "w"] = x[k] * x.w
    g = x.groupby(["industry", "node"]).agg(n=("code", "size"), v5=("v5w", "sum"), v20=("v20w", "sum"),
                                             inst=("instw", "sum"), dfin=("dfinw", "sum"), flow=("floww", "sum"),
                                             r5=("r5", "median")).reset_index()
    g["s5"], g["s20"] = g.v5 / g.v5.sum() * 100, g.v20 / g.v20.sum() * 100
    g = g[(g.n >= 4) & (g.v20 >= 5)]
    g["label"] = g.node.str.replace(r"[（(].*", "", regex=True)

    def reps(r, sign):
        s = x[(x.industry == r.industry) & (x.node == r.node)]
        # 依分攤後金額挑，才會挑到這個節點的代表股，而不是橫跨幾十個節點的權值股；顯示的是個股全額
        s = s[s.flow * sign > 0].assign(fw=lambda d: d.flow * d.w).sort_values("fw", ascending=sign < 0).head(3)
        return "、".join(f"{q['name']} {_n(q.flow)}" for _, q in s.iterrows())

    def lines(df, sign):
        rows, seen = [], set()
        for r in df.itertuples():
            if r.label in seen:
                continue
            seen.add(r.label)
            rows.append([f"**{r.label}**", r.industry, _n(r.flow), _n(r.inst), _n(r.dfin), f"{r.r5:+.1f}%",
                         f"{r.s20:.1f}%→{r.s5:.1f}%", reps(r, sign)])
            if len(rows) >= top:
                break
        return _tbl(["族群", "產業鏈", "法人＋融資", "法人", "融資", "5日漲跌", "成交占比", "代表股（個股法人＋融資）"], rows)

    tot = m.flow.sum()
    out = ["## 資金流向（近 5 日）", "",
           f"法人＋融資 5 日合計 {_yi(tot)}（法人 {_yi(m.inst.sum())}、融資 {_yi(m.dfin.sum())}）。"
           "金額單位億；個股依所屬產業鏈節點數平均分攤後加總，5 日漲跌是族群中位數，成交占比是前 20 日→近 5 日。",
           "", "**流入**", ""]
    out += lines(g.sort_values("flow", ascending=False), 1)
    out += ["", "**流出**", ""]
    out += lines(g.sort_values("flow"), -1)
    return out


# ───────────── 追蹤分點 ─────────────
def watch(day, limit=5000):
    """首頁「追蹤分點大額進出」：config/broker_watch.csv 的分點加總，個股淨額 ≥ 5000 萬（萬元），不含 ETF"""
    f = D / "broker" / "watch" / day[:4] / f"{day}.csv"
    rows = _read(f)
    if not rows:
        return []
    label = {r["branch"].strip(): (r.get("label") or "").strip() or r["branch"].strip()
             for r in csv.DictReader((ROOT / "config" / "broker_watch.csv").open(encoding="utf-8-sig"))
             if (r.get("branch") or "").strip()}
    by = defaultdict(lambda: {"net": 0, "br": defaultdict(int), "name": ""})
    for r in rows:
        if r["code"].startswith("00"):
            continue
        n = (int(r["buy_amt"] or 0) - int(r["sell_amt"] or 0)) / 10   # 仟元 → 萬
        o = by[r["code"]]
        o["net"] += n
        o["name"] = r["name"]
        o["br"][label.get(r["branch"], label.get(r["branch"] + "總公司", r["branch"]))] += n
    hits = [(c, o) for c, o in by.items() if abs(o["net"]) >= limit]
    if not hits:
        return ["## 重要分點買賣超", "", f"追蹤分點加總沒有個股淨額達 {limit:,} 萬。"]
    who = lambda o: "、".join([f"{b} {abs(n) / 1e4:,.2f}" for b, n in
                               sorted(o["br"].items(), key=lambda kv: -abs(kv[1]))
                               if (n > 0) == (o["net"] > 0) and abs(n) >= 1000][:2]) or "—"
    buy = sorted((h for h in hits if h[1]["net"] > 0), key=lambda h: -h[1]["net"])
    sell = sorted((h for h in hits if h[1]["net"] < 0), key=lambda h: h[1]["net"])
    out = [["買超" if o["net"] > 0 else "賣超", f"{o['name']}（{c}）", f"{o['net'] / 1e4:+,.2f}", who(o)] for c, o in buy + sell]
    tb, ts = sum(o["net"] for _, o in buy) / 1e4, sum(o["net"] for _, o in sell) / 1e4
    return ["## 重要分點買賣超", "",
            f"{len(label)} 個追蹤分點加總、個股淨額 ≥ {limit:,} 萬（不含 ETF）：買超 {len(buy)} 檔合計 {tb:+,.2f} 億，"
            f"賣超 {len(sell)} 檔合計 {ts:+,.2f} 億。", ""] + _tbl(["方向", "個股", "淨額（億）", "主要分點（億）"], out)


# ───────────── CB 詢圈 ─────────────
def _short(s):
    return (s or "").replace("股份有限公司", "").replace("綜合證券", "").replace("證券", "")


def cb(iso, prev_iso, names):
    import cb_broker_site
    import cb_site
    cases = cb_site.add_flow_dates(_read(D / "cb" / "cases.csv"), D)
    if not cases:
        return []
    win = lambda v: bool(v) and prev_iso < v <= iso
    nm = lambda c: f"{names.get(c['code']) or c['company'].replace('股份有限公司', '')[:4]}（{c['code']}）"
    amt = lambda c: (f"{float(c['board_amount']) / 1e8:,.1f} 億" if c.get("board_amount") else
                     f"{int(c['units']) / 10000:,.1f} 億" if c.get("units") else "")
    is_bb = lambda c: c["method"] == "詢價圈購" or (not c["method"] and "詢價圈購" in (c.get("board_method") or ""))

    # 常客分點
    hits = {}
    p = ROOT / "research" / "data" / "cb_regulars.json"
    regs = json.loads(p.read_text(encoding="utf-8")).get("regulars", []) if p.exists() else []
    known = {(g["broker"], g["side"]) for g in regs}
    regs += [{"broker": g["broker"], "side": g["side"], "tier": g["tier"]} for g in _read(ROOT / "config" / "cb_regulars.csv")
             if (g["broker"], g["side"]) not in known]
    try:
        live, _ = cb_broker_site.build_live(D, regs)
        hits = {r["code"]: r["hits"] for r in live}
    except Exception as e:   # 分點資料有缺時不影響其他段落
        print("cb broker:", e)

    def hit_txt(code):
        return "、".join(f"{x['broker']}{'買' if x['side'] == 'B' else '賣'} {abs(x['lots']):,}"
                        for x in (hits.get(code) or [])[:3])

    out = []
    lots = lambda c: f"{int(c['bb_units'] or c['units'] or 0):,} 張"
    on = [c for c in cases if c["method"] == "詢價圈購" and c["bb_start"] and c["bb_start"] <= iso <= (c["bb_end"] or iso)]
    for c in sorted(on, key=lambda c: c["bb_end"]):
        prem = f"溢價 {float(c['premium_lo']):g}–{float(c['premium_hi']):g}%，" if c["premium_lo"] else ""
        out.append(["**詢圈中**", nm(c), f"{_md(c['bb_start'])}–{_md(c['bb_end'])}", lots(c),
                    f"{prem}{c['type'].replace('轉換公司債', '')}，主辦 {_short(c['lead'])}", hit_txt(c["code"])])
    soon_end = (date.fromisoformat(iso) + timedelta(days=10)).isoformat()
    for c in sorted(cases, key=lambda c: c["bb_start"] or "9"):
        if c["method"] == "詢價圈購" and c["bb_start"] and iso < c["bb_start"] <= soon_end:
            prem = f"溢價 {float(c['premium_lo']):g}–{float(c['premium_hi']):g}%，" if c["premium_lo"] else ""
            out.append(["即將詢圈", nm(c), f"{_md(c['bb_start'])}–{_md(c['bb_end'])}", lots(c),
                        f"{prem}主辦 {_short(c['lead'])}", hit_txt(c["code"])])
    bank_from = (date.fromisoformat(iso) - timedelta(days=8)).isoformat()
    shown = {c["code"] for c in cases if c["bb_start"] and iso < c["bb_start"]}
    for c in sorted(cases, key=lambda c: c["bank_date"]):
        if (is_bb(c) and c["bank_date"] and bank_from <= c["bank_date"] <= iso and not c["bb_start"]
                and not c["done_date"] and not c["wd_date"] and c["eff_date"] and c["code"] not in shown):
            shown.add(c["code"])
            est = (date.fromisoformat(c["bank_date"]) + timedelta(days=5)).isoformat()
            when = f"推估 {_md(est)} 前後開始詢圈" if est >= iso else f"推估日 {_md(est)} 已過，還沒看到承銷公告"
            out.append(["代收行庫公告", nm(c), f"{_md(c['bank_date'])} 公告", amt(c), when, hit_txt(c["code"])])
    for c in cases:
        if c["method"] == "詢價圈購" and win(c["done_date"]) and c["conv_price"]:
            out.append(["訂價", nm(c), _md(c["done_date"]), lots(c),
                        f"轉換價 {float(c['conv_price']):g}、溢價 {float(c['premium'] or 0):g}%、"
                        f"預計掛牌 {_md(c['list_expected']) if c['list_expected'] else '—'}", hit_txt(c["code"])])
    # 同一家同時辦詢圈＋競拍時合併成一筆
    ev = defaultdict(lambda: defaultdict(list))
    for c in cases:
        for k, lab in (("board_date", "董事會決議"), ("filed_date", "送件"), ("eff_date", "生效"), ("wd_date", "撤件")):
            if win(c.get(k)):
                how = "詢圈" if is_bb(c) else "競拍" if (c["method"] or c.get("board_method")) else ""
                ev[lab][(nm(c), c["code"])].append((f"{how} {amt(c)}".strip(), c[k]))
    for lab in ("董事會決議", "送件", "生效", "撤件"):
        for (name, code), v in ev[lab].items():
            out.append([lab, name, _md(v[0][1]), "＋".join(sorted({a for a, _ in v}, reverse=True)), "", hit_txt(code)])
    if not out:
        return ["## CB 詢圈重點", "", "這次沒有新的詢圈、訂價或董事會決議。"]
    return ["## CB 詢圈重點", ""] + _tbl(["狀態", "公司", "日期", "規模", "條件", "常客分點（張）"], out)


# ───────────── ETF 調整 ─────────────
def _norm(s):
    """指數名稱在排程、公告、ETF 對照表的寫法不一致（有無「臺灣指數公司」「特選」「上市上櫃」「報酬」、空格）"""
    s = re.sub(r"\s+", "", s or "")
    for t in ("臺灣指數公司", "特選", "上市上櫃", "報酬", "臺灣", "台灣"):
        s = s.replace(t, "")
    return s


def etf(iso, prev_iso, names):
    import etf_site
    etfs = {r["etf"]: r for r in _read(D / "etf" / "etf_list.csv")}
    by_index = defaultdict(list)
    for r in _read(D / "etf" / "tip" / "etf_index.csv"):
        if r["index"] and r["index"] != "不適用":
            by_index[_norm(r["index"])].append(f"{r['etf']} {r['name']}")
    out = []

    # 指數成分公告
    res = defaultdict(lambda: {"add": [], "del": [], "eff": ""})
    for r in _read(D / "etf" / "tip" / "results.csv"):
        if prev_iso < r["announce_date"] <= iso and r["action"] in ("add", "del"):
            g = res[r["index"]]
            g[r["action"]].append(r["name"] or names.get(r["code"], r["code"]))
            g["eff"] = r["effective_date"]
    for idx, g in res.items():
        tr = by_index.get(_norm(idx))
        out.append(["**指數審核公告**", "、".join(tr[:3]) if tr else idx, "、".join(g["add"]) or "無",
                    "、".join(g["del"]) or "無", f"生效 {_md(g['eff'])}" if g["eff"] else ""])
    ms = defaultdict(lambda: {"add": [], "del": [], "eff": ""})
    for r in _read(D / "etf" / "msci" / "results.csv"):
        if prev_iso < r["announce_date"] <= iso and r["action"] in ("add", "del"):
            ms[r["review"]][r["action"]].append(names.get(r["code"], r["en_name"]))
            ms[r["review"]]["eff"] = r["effective_date"]
    for rv, g in ms.items():
        out.append(["**MSCI 季度調整**", f"MSCI {rv}", "、".join(g["add"]) or "無", "、".join(g["del"]) or "無",
                    f"生效 {_md(g['eff'])}"])

    # 未來 14 天要公告的審核，加上已公告還沒生效的（同首頁「未來一週 ETF 指數調整」，資料取自 etf_site.build_tip）
    end = (date.fromisoformat(iso) + timedelta(days=14)).isoformat()
    upcoming = []
    try:
        tip = etf_site.build_tip(D, ROOT)
        for x in sorted((dict(zip(tip["cols"], r)) for r in tip["rows"]), key=lambda x: (x["ann"], x["index"])):
            if not x["etfs"]:
                continue
            done = x["ann"] <= iso and (x["add"] is not None or x["del"] is not None)
            if not ((iso < x["ann"] <= end) or (done and x["eff"] and x["eff"] > iso)):
                continue
            nm = lambda c: f"{c} {tip['etfs'].get(c, '')}".strip()
            state = f"已公告：納入 {len(x['add'] or [])}、刪除 {len(x['del'] or [])}" if done else "待公告"
            prov = {"MSCI": "MSCI ", "FTSE": "富時 "}.get(x["prov"], "")
            prov = "" if x["index"].startswith(prov.strip() or "\0") else prov
            upcoming.append([_md(x["ann"]), _md(x["eff"]) if x["eff"] else "", "、".join(nm(c) for c in x["etfs"][:3]),
                             prov + re.sub(r"^臺灣指數公司", "", x["index"]), state])
    except Exception as e:
        print("etf upcoming:", e)

    # ETF 持股新增／剔除（這次公布的持股 vs 該 ETF 前一份）、主動式加減碼
    prices = etf_site.PriceBook(D)
    units = etf_site._units_book(D)
    act = defaultdict(float)
    act_name = {}
    for code, info in etfs.items():
        files = sorted(f for f in (D / "etf" / code).glob("[0-9]*.csv") if f.stem <= iso.replace("-", ""))
        if len(files) < 2 or not (prev_iso < etf_site.date_of(files[-1]) <= iso):
            continue
        cur, prev = etf_site.read_holdings(files[-1]), etf_site.read_holdings(files[-2])
        px = prices.get(etf_site.date_of(files[-1]))
        new, gone = [], []
        for c in set(cur) | set(prev):
            if not re.fullmatch(r"\d{4,6}[A-Z]?", c):
                continue
            cls, d = etf_site.classify(prev.get(c), cur.get(c))
            nm = (cur.get(c) or prev.get(c))["name"]
            if cls == "new":
                new.append(nm)
            elif cls == "removed":
                gone.append(nm)
            if info["kind"] == "active" and d and px.get(c):
                act[c] += d * px[c] / 1e8
                act_name[c] = nm
        big = None
        if info["kind"] == "active":   # 主動式：扣除申購贖回後的雙向換手 ≥ 門檻 → 標「主動大幅調倉」（etf_site.shift_score）
            u0, u1 = units.get((code, etf_site.date_of(files[-2]))), units.get((code, etf_site.date_of(files[-1])))
            sc = etf_site.shift_score(prev, cur, (u1 / u0) if u0 and u1 else None)
            if sc and sc["score"] >= etf_site.SHIFT_BIG:
                big = f"主動式，雙向換手 {sc['score']:.1f}%（續抱 {sc['cont']} 檔中加碼 {sc['up']}、減碼 {sc['dn']}）"
        if big or ((new or gone) and len(new) + len(gone) <= 30):
            out.append(["主動大幅調倉" if big else "持股異動", f"{code} {info['name']}", "、".join(sorted(new)) or "無",
                        "、".join(sorted(gone)) or "無", big or ("主動式" if info["kind"] == "active" else "被動式")])
    res_out = ["## ETF 調整重點", ""]
    if out:
        res_out += _tbl(["類型", "ETF／指數", "新增", "剔除", "備註"], out)
    else:
        res_out.append("這次沒有指數審核公告，ETF 持股也沒有新增或剔除的成分股。")
    if upcoming:
        res_out += ["", "**未來兩週的指數調整**（含已公告、還沒生效的）", ""] + \
            _tbl(["公告日", "生效日", "ETF", "指數", "狀態"], upcoming)
    if act:
        s = sorted(act.items(), key=lambda kv: kv[1])
        buy = [(act_name[c], v) for c, v in s[::-1][:5] if v > 0.5]
        sell = [(act_name[c], v) for c, v in s[:5] if v < -0.5]
        if buy or sell:
            rows = []
            for k in range(max(len(buy), len(sell))):
                b = buy[k] if k < len(buy) else ("", None)
                q = sell[k] if k < len(sell) else ("", None)
                rows.append([b[0], _n(b[1]) if b[1] is not None else "", q[0], _n(q[1]) if q[1] is not None else ""])
            res_out += ["", "**主動式 ETF 合計加減碼**（億，股數增減×收盤價，含申贖）", ""] + \
                _tbl(["加碼", "億", "減碼", "億"], rows)
    return res_out


# ───────────── 內部人 ─────────────
FAMILY = re.compile(r"配偶|未成年")


def insider(iso, prev_iso, px, top=8):
    rows = []
    for f in sorted((D / "insider" / "transfer").glob("*.csv")):
        rows += [r for r in _read(f) if prev_iso < r["date"] <= iso]
    seen, uniq = set(), []
    for r in rows:
        k = (r["date"], r["code"], r["name"], r["method"], r["shares"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    out, notes = [], []
    trust = [r for r in uniq if r["method"] == "信託"]
    main = [r for r in uniq if r["method"] != "信託"]
    for r in main:
        sh = float(r["shares"] or 0)
        r["_amt"] = sh * px.get(r["code"], 0) / 1e8
        r["_pct"] = sh / float(r["held"]) * 100 if float(r["held"] or 0) else 0
    main.sort(key=lambda r: -r["_amt"])
    top = top + 4   # 近 5 個交易日，多列幾筆
    small = [r for r in main if r["_amt"] < 0.05 and not FAMILY.search(r["role"])]
    main = [r for r in main if r not in small]
    for r in main[:top]:
        role = f"**{r['role']}**" if FAMILY.search(r["role"]) else r["role"]
        how = r["method"].replace("(每日得轉讓股數限制)", "")
        if r["transferee"]:
            how += f"，受讓人 {r['transferee']}"
        out.append([_md(r["date"]), f"**{r['company']}（{r['code']}）**", role, r["name"], f"{float(r['shares']) / 1000:,.0f}",
                    f"{r['_amt']:,.2f}", f"{r['_pct']:.0f}%", how])
    if len(main) > top:
        notes.append(f"- 另有 {len(main) - top} 筆，合計約 {sum(r['_amt'] for r in main[top:]):,.1f} 億。")
    if small:
        notes.append(f"- 500 萬以下 {len(small)} 筆不列。")
    if trust:
        notes.append(f"- 信託 {len(trust)} 筆（多為員工獎酬或家族信託，不列入表格）。")
    res = ["## 近期內部人事件", "", "**事前申報轉讓**（近 5 個交易日，依金額）", ""]
    if out:
        res += _tbl(["申報日", "公司", "身分", "申報人", "張數", "金額（億）", "占持股", "方式"], out)
    elif not trust and not small:
        res.append("這次沒有新的事前申報轉讓。")
    if notes:
        res += [""] + notes

    # 最新月報（每月 15 日前後公布上月）
    tf = sorted((D / "insider" / "trades").glob("[0-9]*.csv"))
    if tf:
        t = [r for r in _read(tf[-1])]
        for r in t:
            p = px.get(r["code"], 0)
            r["_b"] = float(r["buy_mkt"] or 0) * p / 1e8
            r["_s"] = float(r["sell_mkt"] or 0) * p / 1e8
        mon = t[0]["month"] if t else tf[-1].stem
        row = lambda r, k, lab: [lab, f"{r['company']}（{r['code']}）", r["name"].replace("股份有限公司", ""), r["role"],
                                 f"{r[k]:,.1f}"]
        rows = [row(r, "_b", "市場買進") for r in sorted(t, key=lambda r: -r["_b"])[:4] if r["_b"] >= 0.3]
        rows += [row(r, "_s", "市場賣出") for r in sorted(t, key=lambda r: -r["_s"])[:4] if r["_s"] >= 0.3]
        if rows:
            res += ["", f"**{mon} 月報**（以 {_md(iso)} 收盤估金額）", ""] + \
                _tbl(["方向", "公司", "申報人", "身分", "金額（億）"], rows)
    return res


# ───────────── CB：近期重要時程＋新增事件（2026-11-03 Leo） ─────────────
def cb_brief(iso, prev_iso, names, days=10):
    import cb_site
    cases = cb_site.add_flow_dates(_read(D / "cb" / "cases.csv"), D)
    if not cases:
        return []
    end = (date.fromisoformat(iso) + timedelta(days=days)).isoformat()
    nm = lambda c: f"{names.get(c['code']) or c['company'].replace('股份有限公司', '')[:4]}（{c['code']}）"
    amt = lambda c: (f"{float(c['board_amount']) / 1e8:,.1f} 億" if c.get("board_amount") else
                     f"{int(c['units']) / 10000:,.1f} 億" if c.get("units") else "")
    how = lambda c: ("詢圈" if (c["method"] or c.get("board_method") or "").startswith("詢價") and "競" not in (c["method"] or "")
                     else "競拍" if "競" in (c["method"] or c.get("board_method") or "") else "")
    dead = lambda c: bool(c.get("wd_date") or c.get("stop_date"))
    lead = lambda c: f"主辦 {_short(c['lead'])}" if c.get("lead") else ""
    prem = lambda c: f"溢價 {float(c['premium_lo']):g}–{float(c['premium_hi']):g}%" if c.get("premium_lo") else ""
    join = lambda *xs: "，".join(x for x in xs if x)

    # 近期重要時程：詢圈中＋未來 days 天的詢圈／競拍、訂價、繳款、掛牌、推估詢圈
    sch = []
    for c in cases:
        if dead(c):
            continue
        m = how(c) or "承銷"
        if c["bb_start"] and c["bb_start"] <= iso <= (c["bb_end"] or c["bb_start"]):
            sch.append((iso, f"**{m}中**", c, join(f"{_md(c['bb_start'])}–{_md(c['bb_end'])}", prem(c), lead(c))))
        for k, lab, extra in (("bb_start", f"{m}開始", lambda: join(f"到 {_md(c['bb_end'])}" if c["bb_end"] else "", prem(c), lead(c))),
                              ("bb_end", f"{m}截止", lambda: lead(c)),
                              ("done_date", "訂價", lambda: f"轉換價 {float(c['conv_price']):g}" if c.get("conv_price") else ""),
                              ("pay_date", "繳款", lambda: ""),
                              ("list_date", "掛牌", lambda: ""),
                              ("list_expected", "預計掛牌", lambda: "")):
            v = c.get(k)
            if k == "list_expected" and c.get("list_date"):
                continue
            if k == "bb_end" and c["bb_start"] and c["bb_start"] <= iso:
                continue   # 已列在「詢圈中」
            if v and iso < v <= end:
                sch.append((v, lab, c, extra()))
        sib = any(x["code"] == c["code"] and x["bb_start"] and x["bb_start"] >= (c["bank_date"] or "9") for x in cases)
        if c["bank_date"] and not c["bb_start"] and not c["done_date"] and c["eff_date"] and not sib:
            est = (date.fromisoformat(c["bank_date"]) + timedelta(days=5)).isoformat()
            if iso < est <= end:
                sch.append((est, "推估開始承銷", c, f"代收行庫 {_md(c['bank_date'])} 已公告（通常 5 天內開始）"))
    sch.sort(key=lambda x: (x[0], x[1], x[2]["code"]))
    seen, rows = set(), []
    for d, lab, c, note in sch:
        k = (d, lab, c["code"])
        if k in seen:
            continue
        seen.add(k)
        rows.append([_md(d), lab, nm(c), amt(c), note])

    # 突然新增的事件：上一個交易日之後才出現的董事會決議、送件、生效、代收行庫、承銷公告、撤件
    new = defaultdict(list)
    for c in cases:
        for k, lab in (("board_date", "董事會決議"), ("filed_date", "送件"), ("eff_date", "生效"), ("bank_date", "代收行庫公告"),
                       ("nt_date", "承銷公告"), ("wd_date", "撤件"), ("stop_date", "停止")):
            v = c.get(k)
            if v and prev_iso < v <= iso:
                new[(v, lab, c["code"])].append(c)
    order = ["董事會決議", "送件", "生效", "代收行庫公告", "承銷公告", "撤件", "停止"]
    rows2 = []
    for (v, lab, code), cs in sorted(new.items(), key=lambda kv: (order.index(kv[0][1]), kv[0][0], kv[0][2])):
        c = cs[0]
        rows2.append([_md(v), f"**{lab}**", nm(c), "＋".join(sorted({join(how(x), amt(x)) for x in cs}, reverse=True)),
                      join(lead(c), prem(c) if lab == "承銷公告" else "")])

    out = ["## CB 詢圈", "", f"**近期重要時程**（進行中＋未來 {days} 天）", ""]
    out += _tbl(["日期", "事件", "公司", "規模", "說明"], rows) if rows else [f"未來 {days} 天沒有排定的時程。"]
    out += ["", "**新增事件**（上一個交易日之後才出現）", ""]
    out += _tbl(["日期", "事件", "公司", "規模", "說明"], rows2) if rows2 else ["這次沒有新增的 CB 事件。"]
    return out


# ───────────── ETF：重要時程＋近期大額調整的主動式 ETF（2026-11-03 Leo） ─────────────
def etf_brief(iso, since, days=14):
    import etf_site
    out = ["## ETF 調整", ""]
    end = (date.fromisoformat(iso) + timedelta(days=days)).isoformat()
    rows = []
    try:
        tip = etf_site.build_tip(D, ROOT)
        for x in sorted((dict(zip(tip["cols"], r)) for r in tip["rows"]), key=lambda x: (x["ann"], x["index"])):
            if not x["etfs"]:
                continue
            done = x["ann"] <= iso and (x["add"] is not None or x["del"] is not None)
            if not ((iso < x["ann"] <= end) or (done and x["eff"] and x["eff"] > iso)):
                continue
            prov = {"MSCI": "MSCI ", "FTSE": "富時 "}.get(x["prov"], "")
            prov = "" if x["index"].startswith(prov.strip() or "\0") else prov
            ad = lambda xs: "、".join(a[1] for a in (xs or [])[:5]) + (f" 等 {len(xs)} 檔" if xs and len(xs) > 5 else "")
            state = (f"已公告：納入 {ad(x['add']) or '無'}；刪除 {ad(x['del']) or '無'}" if done else "待公告")
            rows.append([_md(x["ann"]), _md(x["eff"]) if x["eff"] else "",
                         "、".join(f"{c} {tip['etfs'].get(c, '')}".strip() for c in x["etfs"][:3]),
                         prov + re.sub(r"^臺灣指數公司", "", x["index"]), state])
    except Exception as e:
        print("etf schedule:", e)
    out += [f"**重要時程**（未來 {days} 天要公告，以及已公告還沒生效的）", ""]
    out += _tbl(["公告日", "生效日", "ETF", "指數", "狀態"], rows) if rows else [f"未來 {days} 天沒有 ETF 追蹤的指數要調整。"]

    d = etf_site.build_shift(D)
    names = {e["code"]: e["name"] for e in d["etfs"]}
    ev = sorted((e for e in d["events"] if since < e["date"] <= iso and e["score"] >= d["big"]),
                key=lambda e: (e["date"], e["score"]), reverse=True)
    out += ["", f"**近期大額調整的主動式 ETF**（近 5 個交易日，扣除申購贖回後雙向換手 ≥ {d['big']:g}%）", ""]
    if not ev:
        last = next((e for e in d["events"] if e["date"] <= iso and e["score"] >= d["big"]), None)
        out.append("近 5 個交易日沒有。" + (f"上一次是 {_md(last['date'])} {last['etf']} {names.get(last['etf'], '')}"
                                          f"（{last['score']:.1f}%）。" if last else ""))
        return out
    nm = lambda xs: ("、".join(x[1] for x in xs[:6]) + (f" 等 {len(xs)} 檔" if len(xs) > 6 else "")) if xs else "無"
    mv = lambda ms: "、".join(f"{m[1]} {m[2]:+.0f}%" for m in ms[:3]) or "—"
    out += _tbl(["公布日", "ETF", "雙向換手", "新增", "剔除", "主要加碼", "主要減碼"],
                [[_md(e["date"]), f"**{e['etf']} {names.get(e['etf'], '')}**", f"{e['score']:.1f}%", nm(e["adds"]), nm(e["drops"]),
                  mv([m for m in e["moves"] if m[2] > 0]), mv([m for m in e["moves"] if m[2] < 0])] for e in ev])
    out += ["", "加減碼百分比是扣掉申贖後的股數變化；明細在 ETF 頁的「主動調倉」分頁。"]
    return out


# ───────────── 主動式 ETF 大幅調倉 ─────────────
def shift(iso, prev_iso, top=3):
    """etf_site.build_shift 的事件（扣除申購贖回後雙向換手 ≥ 大幅門檻），持股公布日落在這次的才列"""
    import etf_site
    d = etf_site.build_shift(D)
    names = {e["code"]: e["name"] for e in d["etfs"]}
    ev = [e for e in d["events"] if prev_iso < e["date"] <= iso and e["score"] >= d["big"]]
    head = ["## 主動式 ETF 大幅調倉", "",
            f"扣除申購贖回後，同時大量加碼與減碼（雙向換手 ≥ {d['big']:g}%，佔基金規模）的主動式 ETF。"
            "加減碼百分比是扣掉申贖後的股數變化。", ""]
    if not ev:
        last = next((e for e in d["events"] if e["date"] <= iso and e["score"] >= d["big"]), None)
        tail = f"上一次是 {_md(last['date'])} {last['etf']} {names.get(last['etf'], '')}（{last['score']:.1f}%）。" if last else ""
        return head + [f"這次沒有主動式 ETF 大幅調倉。{tail}"]
    nm = lambda xs: "、".join(x[1] for x in xs[:6]) + (f" 等 {len(xs)} 檔" if len(xs) > 6 else "") if xs else "無"
    mv = lambda ms: "、".join(f"{m[1]} {m[2]:+.0f}%" for m in ms[:top]) or "—"
    rows = []
    for e in sorted(ev, key=lambda e: -e["score"]):
        rows.append([f"**{e['etf']} {names.get(e['etf'], '')}**", _md(e["date"]), f"{e['score']:.1f}%",
                     nm(e["adds"]), nm(e["drops"]), mv([m for m in e["moves"] if m[2] > 0]),
                     mv([m for m in e["moves"] if m[2] < 0]), f"{e['up']} / {e['dn']}（續抱 {e['cont']}）"])
    return head + _tbl(["ETF", "公布日", "雙向換手", "新增", "剔除", "主要加碼", "主要減碼", "續抱股加 / 減"], rows)


# 2026-11-03 Leo：摘要下方只留 ETF 調整（重要時程＋近期大額調整的主動式 ETF）、CB（重要時程＋新增事件）、
# ───────────── 快出關的處置股 ─────────────
def disp_exit(iso, stems, days=4):
    """出關日在資料日 D 之後 days 個交易日內的處置股（接續處置的以最後一段為準），附出關隔天歷史統計。"""
    import alert_site
    hp = D / "no_trading_days.txt"
    hol = set(hp.read_text(encoding="utf-8").split()) if hp.exists() else set()
    disp = [x for x in _read(D / "alert" / "disposal.csv") if alert_site.is_stock(x["code"]) and x.get("end")]
    for x in disp:
        x["exit"] = alert_site.next_open(x["end"], hol)
    t = iso
    for _ in range(days):
        t = alert_site.next_open(t, hol)
    up = alert_site.upcoming_exits(disp, iso, t)
    if not up:
        return []
    st = alert_site.exit_stats(disp, D) or {"groups": []}
    g = {x["key"]: x for x in st["groups"]}
    alert_site.add_prices(up, D, iso)
    rows = []
    for c in up:
        x = g.get(c["group"])
        try:
            chg = f"{float(c['close']) / float(c['pre_close']) * 100 - 100:+.1f}%"
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            chg = ""
        rows.append([_md(c["exit"]), f"{c['code']} {c['name']}（{'市' if c['market'] == '上市' else '櫃'}）",
                     c["measure"].replace("處置", ""), chg,
                     (f"**{x['black']:.0f}%**" if x["black"] >= 60 else f"{x['black']:.0f}%") + f"（{x['label']}，開到收中位 {x['oc_med']:+.1f}%）" if x else ""])
    out = ["## 快出關的處置股", "", f"出關日在未來 {days} 個交易日內；處置期間又被處置的以最後一次為準。", ""]
    out += _tbl(["出關日", "股票", "次別", "處置期間漲跌", "出關隔天收黑（歷史）"], rows)
    out += ["", "歷史統計是改制（處置起日 2026/8/10）後同一類出關隔天收盤低於開盤的比例；第一次處置的上櫃股最明顯，第二次／再次沒有偏向。"]
    return out


# ───────────── 去槓桿進度（殺乾淨了沒） ─────────────
def delev(iso):
    """margin_site.deleverage 的燈號＋五項檢查＋台股正 2 ETF／主動式 ETF 融資（同融資頁）。"""
    import margin_site
    d = margin_site.deleverage_from_disk(D)
    if not d or d["date"] != iso:
        return []
    m, ref = d["market"], d["ref"]
    out = ["## 去槓桿進度", "",
           f"**{'🟢' if d['level'] == 3 else '🟡' if d['level'] == 2 else '🔴'} {d['label']}**（符合 {d['hits']} / {len(d['checks'])} 項）。"
           f"加權離 {_md(m['taiex_peak_date'])} 高點 {m['taiex_dd']:+.1f}%，融資張數離 {_md(m['peak_date'])} 高點 {m['dd']:+.1f}%，"
           f"估計維持率 {m['ratio']:.1f}%。"
           + (f"上一次洗盤（{_md(ref['date'])}）張數 {ref['dd']:+.1f}%、維持率低點 {ref['ratio']:.0f}%。" if ref else ""), ""]
    out += _tbl(["檢查", "現況", "達標"], [[c["k"], c["t"], "✅" if c["hit"] else "—"] for c in d["checks"]])
    pc = lambda v: "—" if v is None else f"{v:+.1f}%"
    rows = [[f"{e['code']} {e['name']}", f"{e['fin']:,.0f} 張" + ("（新高）" if e["fin"] >= e["fin_peak"] else ""), pc(e["f5"]), pc(e["f20"]),
             pc(e["u5"]), "—" if e["flow5"] is None else _yi(e["flow5"])] for e in d["etfs"]]
    a = d["active"]
    rows.append(["主動式 ETF 合計", f"{a['fin']:,.0f} 張", pc(a["f5"]), pc(a["f20"]), "", ""])
    out += [""] + _tbl(["槓桿部位", "融資餘額", "融資 5 日", "融資 20 日", "受益單位 5 日", "淨申贖 5 日"], rows)
    return out


def upcoming_events(iso, days=7):
    """未來一週重要事件（scripts/events_site.py；指數調整、處置出關另有段落，這裡不重複）"""
    import events_site as E
    ev = E.upcoming(E.build(D, ROOT, today=date.fromisoformat(iso)), days=days)
    if not ev:
        return []
    rows = [[f"{_md(e[0])}（{E.weekday(e[0])}）", e[1] or "", ("**" + e[4] + "**" if e[6] >= 3 else e[4]) + ("（估）" if e[7] else ""),
             e[5].replace("|", "／")] for e in ev]
    return ["## 未來一週重要事件", "", "時間為台灣時間；粗體＝會動到大盤的大事。完整行事曆在網站「市場行事曆」頁。", ""] + \
        _tbl(["日期", "時間", "事件", "說明"], rows)


# 重要分點買賣超、近期內部人事件；資金流向、舊版 CB／ETF 段落先不放，要放回時把名稱加回 SECTIONS（順序即網頁順序）。
SECTIONS = ("events", "delev", "disp_exit", "etf_brief", "cb_brief", "watch", "insider")


def build(day, px_files, chip_files):
    """回傳重點 Markdown 行（不含標題）。"""
    stems = [Path(f).stem for f in px_files]
    i = stems.index(day)
    iso, prev_iso = _iso(day), _iso(stems[i - 1]) if i else "0000-00-00"
    names = _names()
    px = {r["code"]: float(r["close"]) for r in _read(px_files[i]) if r.get("close") and re.match(r"^[\d.]+$", r["close"])}
    out = []
    since5 = _iso(stems[max(0, i - 5)])   # 內部人事件看近 5 個交易日
    fns = {("events" if f is upcoming_events else f.__name__): (f, a) for f, a in ((flows, (px_files, chip_files, day)), (watch, (day,)), (cb, (iso, prev_iso, names)),
                                           (etf, (iso, prev_iso, names)), (insider, (iso, since5, px)), (shift, (iso, prev_iso)),
                                           (cb_brief, (iso, prev_iso, names)), (etf_brief, (iso, since5)),
                                           (disp_exit, (iso, stems)), (delev, (iso,)), (upcoming_events, (iso,)))}
    for f, args in (fns[k] for k in SECTIONS):
        try:
            sec = f(*args)
        except Exception as e:   # 一段壞掉不影響其他段
            print(f"digest_points.{f.__name__}: {e!r}")
            sec = []
        if sec:
            out += sec + [""]
    return out


def write(day, px_files, chip_files, out_dir):
    iso = _iso(day)
    lines = [f"# 盤後重點 {iso}", ""] + build(day, px_files, chip_files)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines).rstrip() + "\n"
    (out_dir / f"{day}.md").write_text(text, encoding="utf-8")
    return lines[2:]


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    px_files = sorted(glob.glob(str(D / "20[0-9][0-9]" / "*.csv")))
    if a.date:
        px_files = [f for f in px_files if Path(f).stem <= a.date]
    chip_files = sorted(glob.glob(str(D / "chips" / "*" / "*.csv")))
    day = Path(px_files[-1]).stem
    write(day, px_files, chip_files, D / "digest" / "points")
    print((D / "digest" / "points" / f"{day}.md").read_text(encoding="utf-8"))
