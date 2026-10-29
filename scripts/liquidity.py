"""資金水龍頭：盤後摘要裡的一段，判斷股市資金是在進來還是在收。

每個指標給一個燈號：🟢 還開著、🟡 轉弱、🔴 收緊。門檻寫在 RULES，可直接改。

  成交值      上市成交值 5 日均 ÷ 60 日均                       data/margin/index.csv
  融資        上市＋上櫃融資餘額 5／20 日變化                    data/margin/summary.csv
  不限用途    不限用途借貸餘額（以今日收盤價計）距 60 日高點     data/pledge/
  ETF 申贖    國內股票型 ETF（含台股主動式）申購淨額 5／20 日    data/etf/aum/
  台幣＋外資  美元兌台幣 20 日變化、外資現貨 10 日買賣超          data/macro/daily.csv
  美債美元    美 10 年債 20 日變化、美元指數 20 日變化            data/macro/daily.csv
  信用利差    美國高收益債 OAS 20 日變化（抓不到改用 HYG÷IEF）、VIX                     data/macro/daily.csv
  CB 籌資     可轉債近 30 日送件金額 vs 前 180 日月均、撤件數    data/cb/sfb.csv、bookbuilding.csv

另附個股槓桿（融資、不限用途 5 日增減）與產業鏈節點加總、近 90 日 CB 送件依產業鏈。
金額以「張數 × 1000 × 今日收盤價」估算，所以只反映張數變化、不受股價漲跌影響。
"""
import glob
from pathlib import Path

import pandas as pd

D = Path("data")
G, Y, R = "🟢", "🟡", "🔴"
RULES = {
    "turnover_red": 0.8, "turnover_yellow": 1.0,          # 5 日均 ÷ 60 日均
    "margin20_red": -3.0,                                  # 融資 20 日 %
    "ul_dd_red": -5.0,                                     # 不限用途距 60 日高點 %
    "twd_red": 1.5,                                        # 台幣 20 日貶值 %
    "us10y_bp": 30, "dxy_pct": 2.0,                        # 20 日
    "hy_red_bp": 50, "hy_yellow_bp": 25, "hyg_red": 2.0, "hyg_yellow": 1.0, "vix_red": 30, "vix_yellow": 22,
    "cb_red": 0.5, "cb_yellow": 0.8, "cb_wd_red": 3,       # 近 30 日送件 ÷ 前 180 日月均；撤件數
}
FOREIGN = r"全球|美|亞|ARK|日本|印度|歐洲|中國|越南"


def _files(sub, day, n):
    fs = sorted(f for f in glob.glob(str(D / sub / "*" / "*.csv")) if Path(f).stem <= day)
    return fs[-n:]


def _macro(iso):
    p = D / "macro" / "daily.csv"
    if not p.exists():
        return {}
    m = pd.read_csv(p)
    m = m[m.date <= iso]
    return {k: g.sort_values("date").reset_index(drop=True) for k, g in m.groupby("series")}


def _chg(s, n, mode="pct"):
    """回傳 (最新值, n 筆前到現在的變化, 最新日期)。"""
    if s is None or len(s) <= n:
        return None
    a, b = s.value.iloc[-1], s.value.iloc[-1 - n]
    return a, ((a / b - 1) * 100 if mode == "pct" else (a - b) * 100), s.date.iloc[-1]


def _bal(f, col, px):
    d = pd.read_csv(f, dtype={"code": str})[["code", "name", col]]
    d = d.merge(px, on="code")
    d["amt"] = d[col] * 1000 * d.close / 1e8
    return d


def section(day, iso, px_now, f_sum10, chain):
    """回傳 (lines, lights)。px_now：當日全市場 code, close；f_sum10：外資現貨 10 日合計（億）。"""
    rows, lights = [], []

    def add(name, light, value, rule):
        lights.append(light)
        rows.append(f"| {name} | {light} | {value} | {rule} |")

    # 1. 成交值
    idx = pd.read_csv(D / "margin" / "index.csv")
    idx = idx[idx.date <= iso]
    v = idx.value / 1e8
    ratio = v.tail(5).mean() / v.tail(60).mean()
    near_hi = idx.taiex.iloc[-1] >= idx.taiex.tail(60).max() * 0.98
    lt = R if ratio < RULES["turnover_red"] else Y if ratio < RULES["turnover_yellow"] else G
    note = "，指數近 60 日高點附近量縮" if near_hi and ratio < 0.9 else ""
    add("成交值", lt, f"5 日均 {v.tail(5).mean():,.0f} 億 ÷ 60 日均 {v.tail(60).mean():,.0f} 億 = {ratio:.2f}{note}",
        f"<{RULES['turnover_red']} 紅、<{RULES['turnover_yellow']} 黃")

    # 2. 融資（上市＋上櫃）
    sm = pd.read_csv(D / "margin" / "summary.csv")
    sm = sm[sm.date <= iso].groupby("date").fin_amount.sum() / 1e8
    c5 = (sm.iloc[-1] / sm.iloc[-6] - 1) * 100
    c20 = (sm.iloc[-1] / sm.iloc[-21] - 1) * 100
    down = 0
    for a, b in zip(sm.values[::-1], sm.values[-2::-1]):
        if a < b:
            down += 1
        else:
            break
    lt = R if c20 <= RULES["margin20_red"] or down >= 5 else Y if c5 < 0 else G
    add("融資", lt, f"{sm.iloc[-1]:,.0f} 億，5 日 {c5:+.1f}%、20 日 {c20:+.1f}%" + (f"，連 {down} 日減" if down >= 2 else ""),
        f"20 日 ≤{RULES['margin20_red']}% 或連 5 日減 紅、5 日減 黃")

    # 3. 不限用途（以今日價計，只看張數變化）
    ul_files = _files("pledge", day, 61)
    tot = []
    for f in ul_files:
        d = pd.read_csv(f, dtype={"code": str})[["code", "ul_bal"]].merge(px_now, on="code")
        tot.append((d.ul_bal * 1000 * d.close).sum() / 1e8)
    tot = pd.Series(tot)
    dd = (tot.iloc[-1] / tot.max() - 1) * 100
    u5 = (tot.iloc[-1] / tot.iloc[-6] - 1) * 100
    lt = R if dd <= RULES["ul_dd_red"] else Y if u5 < 0 else G
    add("不限用途借貸", lt, f"{tot.iloc[-1]:,.0f} 億，5 日 {u5:+.1f}%、距 60 日高點 {dd:+.1f}%",
        f"距高 ≤{RULES['ul_dd_red']}% 紅、5 日減 黃")

    # 4. ETF 申贖（用發行單位數差 × 最新淨值，缺日也算得出來）
    a = pd.concat(pd.read_csv(f, dtype={"etf": str}) for f in sorted(glob.glob(str(D / "etf" / "aum" / "*.csv"))))
    a = a[a.date <= iso].drop_duplicates(["date", "etf"], keep="last")
    dom = a[(a.category == "國內股票") | ((a.category == "主動式") & a.etf.str.endswith("A")
                                        & ~a.name.str.contains(FOREIGN))]
    dates = idx.date.tolist()

    def flow(n):
        base = dates[-1 - n] if len(dates) > n else dates[0]
        now = dom.sort_values("date").groupby("etf").tail(1).set_index("etf")
        # 基準日之前沒資料就用該檔最早一筆；之後才上市的新 ETF 整檔算流入
        srt = dom.sort_values("date")
        old = pd.concat([srt[srt.date <= base], srt.groupby("etf").head(1)]) \
            .drop_duplicates(["date", "etf"]).sort_values("date")
        old = old[old.date <= max(base, dom.date.min())].groupby("etf").tail(1).set_index("etf")
        f = ((now.units - old.units.reindex(now.index).fillna(0)) * now.nav / 1e8).dropna()
        return f, base < dom.date.min()

    f5, _ = flow(5)
    f20, short = flow(20)
    lt = R if f20.sum() < 0 else Y if f5.sum() < 0 else G
    top = f5.sort_values()
    nm = dom.drop_duplicates("etf", keep="last").set_index("etf").name
    fmt = lambda s: "、".join(f"{nm.get(k, k)} {v:+,.0f}" for k, v in s.items())
    add("國內股票 ETF 申贖", lt,
        f"5 日 {f5.sum():+,.0f} 億、20 日 {f20.sum():+,.0f} 億{'（資料不足 20 日）' if short else ''}",
        "20 日淨贖回 紅、5 日淨贖回 黃")
    etf_line = f"- ETF 5 日申購最多：{fmt(top[::-1].head(3))}；贖回最多：{fmt(top.head(3)[top.head(3) < 0]) or '無'}"

    # 5～7. 匯率、美債美元、信用利差
    mc = _macro(iso)
    twd = _chg(mc.get("usdtwd"), 20)
    if twd:
        dep = twd[1]   # 美元兌台幣上升 = 台幣貶值
        lt = R if dep >= RULES["twd_red"] and f_sum10 < 0 else Y if dep >= RULES["twd_red"] or (dep > 0 and f_sum10 < 0) else G
        add("台幣＋外資", lt, f"USD/TWD {twd[0]:.3f}（{twd[2]}），20 日台幣{'貶' if dep > 0 else '升'} {abs(dep):.1f}%；"
            f"外資現貨 10 日 {f_sum10:+,.0f} 億", f"台幣貶 ≥{RULES['twd_red']}% 且外資賣 紅、其一 黃")
    us = _chg(mc.get("us10y"), 20, "bp")
    dx = _chg(mc.get("dxy"), 20)
    if us and dx:
        k = int(us[1] >= RULES["us10y_bp"]) + int(dx[1] >= RULES["dxy_pct"])
        add("美債＋美元", [G, Y, R][k], f"美 10 年 {us[0]:.2f}%（20 日 {us[1]:+.0f}bp），美元指數 {dx[0]:.1f}（20 日 {dx[1]:+.1f}%）",
            f"10 年債 +{RULES['us10y_bp']}bp 與美元 +{RULES['dxy_pct']}% 同時 紅、其一 黃")
    hy = _chg(mc.get("hy_oas"), 20, "bp")
    ig = mc.get("ig_oas")
    vx = mc.get("vix")
    hyg, ief = mc.get("hyg"), mc.get("ief")
    if not hy and hyg is not None and ief is not None:
        # FRED 抓不到時用 HYG÷IEF：比值 20 日跌幅當利差擴大的替代
        r = hyg.merge(ief, on="date", suffixes=("_h", "_i"))
        r = r.assign(value=r.value_h / r.value_i)
        c = _chg(r, 20)
        vix = vx.value.iloc[-1] if vx is not None and len(vx) else 0
        if c:
            lt = R if c[1] <= -RULES["hyg_red"] or vix >= RULES["vix_red"] else \
                Y if c[1] <= -RULES["hyg_yellow"] or vix >= RULES["vix_yellow"] else G
            add("信用利差", lt, f"HYG÷IEF 20 日 {c[1]:+.1f}%（{c[2]}，跌＝利差擴大）、VIX {vix:.1f}",
                f"比值跌 ≥{RULES['hyg_red']}% 或 VIX ≥{RULES['vix_red']} 紅；跌 ≥{RULES['hyg_yellow']}% 或 ≥{RULES['vix_yellow']} 黃")
    if hy:
        vix = vx.value.iloc[-1] if vx is not None and len(vx) else 0
        lt = R if hy[1] >= RULES["hy_red_bp"] or vix >= RULES["vix_red"] else \
            Y if hy[1] >= RULES["hy_yellow_bp"] or vix >= RULES["vix_yellow"] else G
        igs = f"、投資級 {ig.value.iloc[-1]:.2f}%" if ig is not None and len(ig) else ""
        add("信用利差", lt, f"高收益債 {hy[0]:.2f}%（20 日 {hy[1]:+.0f}bp，{hy[2]}）{igs}、VIX {vix:.1f}",
            f"高收益 +{RULES['hy_red_bp']}bp 或 VIX ≥{RULES['vix_red']} 紅；+{RULES['hy_yellow_bp']}bp 或 ≥{RULES['vix_yellow']} 黃")
    if not mc:
        rows.append("| 台幣／美債／信用利差 | — | 尚無 data/macro/daily.csv | |")

    # 8. CB 籌資
    s = pd.read_csv(D / "cb" / "sfb.csv", dtype={"code": str})
    s["amount"] = pd.to_numeric(s.amount, errors="coerce") / 1e8
    s["filed"] = pd.to_datetime(s.filed, errors="coerce")
    t0 = pd.Timestamp(iso)
    now30 = s[(s.filed > t0 - pd.Timedelta(days=30)) & (s.filed <= t0)]
    prev = s[(s.filed > t0 - pd.Timedelta(days=210)) & (s.filed <= t0 - pd.Timedelta(days=30))]
    base = prev.amount.sum() / 6
    cr = now30.amount.sum() / base if base else float("nan")
    wd = pd.to_datetime(s.withdrawn, errors="coerce")
    nwd = int(((wd > t0 - pd.Timedelta(days=30)) & (wd <= t0)).sum())
    bb = pd.read_csv(D / "cb" / "bookbuilding.csv")
    bb["d"] = pd.to_datetime(bb.bb_start, errors="coerce")
    p60 = bb[(bb.d > t0 - pd.Timedelta(days=60)) & (bb.d <= t0)].premium_lo.mean()
    p180 = bb[(bb.d > t0 - pd.Timedelta(days=240)) & (bb.d <= t0 - pd.Timedelta(days=60))].premium_lo.mean()
    lt = R if cr < RULES["cb_red"] or nwd >= RULES["cb_wd_red"] else Y if cr < RULES["cb_yellow"] or p60 < p180 - 1 else G
    add("CB 籌資", lt, f"近 30 日送件 {len(now30)} 件 {now30.amount.sum():,.0f} 億（前 6 個月月均 {base:,.0f} 億，{cr:.1f} 倍）；"
        f"撤件 {nwd}；詢圈溢價下限 60 日均 {p60:.1f}（之前 {p180:.1f}）",
        f"<{RULES['cb_red']} 倍或撤件 ≥{RULES['cb_wd_red']} 紅、<{RULES['cb_yellow']} 倍或溢價降 1 黃")

    out = ["", "## 資金水龍頭", "",
           f"燈號：{R} {lights.count(R)}、{Y} {lights.count(Y)}、{G} {lights.count(G)}（共 {len(lights)} 項；紅＝收緊）", "",
           "| 指標 | 燈 | 數值 | 條件 |", "|---|---|---|---|"] + rows + ["", etf_line]

    # 個股槓桿與產業鏈節點
    fin = _files("margin", day, 6)
    ul = _files("pledge", day, 6)
    if len(fin) == 6 and len(ul) == 6:
        a0, a1 = _bal(fin[0], "fin_bal", px_now), _bal(fin[-1], "fin_bal", px_now)
        b0, b1 = _bal(ul[0], "ul_bal", px_now), _bal(ul[-1], "ul_bal", px_now)
        lv = a1[["code", "name", "amt"]].rename(columns={"amt": "fin"}).merge(
            a0[["code", "amt"]].rename(columns={"amt": "fin0"}), on="code", how="outer").merge(
            b1[["code", "name", "amt"]].rename(columns={"amt": "ul", "name": "n2"}), on="code", how="outer").merge(
            b0[["code", "amt"]].rename(columns={"amt": "ul0"}), on="code", how="outer")
        lv["name"] = lv.name.fillna(lv.n2)
        lv = lv[(lv.code.str.len() == 4) & ~lv.code.str.startswith("00")].fillna(0)
        lv["dfin"], lv["dul"] = lv.fin - lv.fin0, lv.ul - lv.ul0
        lv["dfin_p"] = (lv.fin / lv.fin0.where(lv.fin0 > 0) - 1) * 100
        lv["dall"] = lv.dfin + lv.dul
        f2 = lambda v: f"{v:+.1f}"

        def tbl(df, title):
            o = ["", f"## {title}", "", "| 代號 | 名稱 | 融資餘額億 | 融資5日 | 5日% | 不限用途億 | 不限用途5日 |", "|---|---|---|---|---|---|---|"]
            for r in df.itertuples():
                o.append(f"| {r.code} | {r.name} | {r.fin:,.1f} | {f2(r.dfin)} | {pct_(r.dfin_p)} | {r.ul:,.1f} | {f2(r.dul)} |")
            return o

        out += tbl(lv.sort_values("dall", ascending=False).head(10), "槓桿 5 日增加前 10（融資＋不限用途，億）")
        out += tbl(lv.sort_values("dall").head(5), "槓桿 5 日減少前 5")
        ch = chain.merge(lv, on="code")
        g = ch.groupby(["industry", "node"]).agg(n=("code", "size"), dfin=("dfin", "sum"), dul=("dul", "sum"),
                                                 fin=("fin", "sum")).reset_index()
        # 一檔大股會出現在很多節點，所以節點依融資 5 日 % 排序，不用金額
        g["p"] = g.dfin / (g.fin - g.dfin).where(g.fin > g.dfin) * 100
        g = g[(g.n >= 4) & (g.fin >= 20)]
        g["node"] = g.industry + "／" + g.node.str.replace(r"[（(].*", "", regex=True)
        for title, df in [("產業鏈節點 融資 5 日增幅前 8（餘額 ≥20 億）", g.sort_values("p", ascending=False).head(8)),
                          ("產業鏈節點 融資 5 日減幅前 5", g.sort_values("p").head(5))]:
            out += ["", f"## {title}", "", "| 節點 | 家數 | 融資5日億 | 融資5日% | 不限用途5日億 |", "|---|---|---|---|---|"]
            out += [f"| {r.node} | {r.n} | {f2(r.dfin)} | {pct_(r.p)} | {f2(r.dul)} |" for r in df.itertuples()]

    # 近 90 日 CB 送件依產業鏈
    q = s[(s.filed > t0 - pd.Timedelta(days=90)) & (s.filed <= t0)]
    ind = chain.drop_duplicates("code")[["code", "industry"]]
    q = q.merge(ind, on="code", how="left").fillna({"industry": "未分類"})
    gq = q.groupby("industry").agg(n=("code", "size"), amt=("amount", "sum")).sort_values("amt", ascending=False).head(6)
    out += ["", f"- 近 90 日 CB 送件依產業鏈（件／億）：" + "、".join(f"{k} {int(r.n)}／{r.amt:,.0f}" for k, r in gq.iterrows())]
    return out, lights


def pct_(v):
    return "—" if pd.isna(v) else f"{v:+.1f}%"
