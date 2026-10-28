"""盤後數字摘要：把當天已抓好的資料濃縮成一份短 Markdown，給每晚的判讀用。

  data/digest/YYYYMMDD.md   當天摘要
  data/digest/latest.md     最新一份（同內容）

內容：加權指數位置與均線、外資／投信現貨買賣超（近 10 日）、台指期外資未平倉、P/C、
前十大交易人、融資餘額、處置／注意股熱度、族群（官方產業與產業鏈節點）5／20 日強弱與
法人 10 日買賣超、外資／投信個股買賣超前段、20 日強勢股。

用法：python scripts/digest.py [--date YYYYMMDD]
買賣超金額 = 股數 × 當日收盤價（估算，含 ETF）。
"""
import argparse
import glob
from pathlib import Path

import pandas as pd

D = Path("data")
OUT = D / "digest"
SCALE = {"TX": 1, "MTX": 0.25, "TMF": 0.05}   # 小台 1/4 大台、微台 1/20 大台


def yi(v):
    return f"{v:+,.0f}"


def pct(v):
    return "—" if pd.isna(v) else f"{v:+.1f}%"


def load_px(f):
    d = pd.read_csv(f, dtype={"code": str})
    return d


def table(df, cols, heads):
    lines = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()

    px_files = sorted(glob.glob(str(D / "20[0-9][0-9]" / "*.csv")))
    if a.date:
        px_files = [f for f in px_files if Path(f).stem <= a.date]
    day = Path(px_files[-1]).stem
    chip_files = sorted(glob.glob(str(D / "chips" / "*" / "*.csv")))
    chip_files = [f for f in chip_files if Path(f).stem <= day]
    if not chip_files or Path(chip_files[-1]).stem != day:
        print(f"{day} 三大法人資料還沒到，不產生摘要")
        return
    iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    out = [f"# 盤後數字摘要 {iso}", "", "買賣超金額為股數×收盤價估算（億元，含 ETF）。", ""]

    # ── 大盤 ──
    idx = pd.read_csv(D / "margin" / "index.csv")
    idx = idx[idx.date <= iso].reset_index(drop=True)
    t = idx.taiex
    last = idx.iloc[-1]
    out += ["## 大盤", ""]
    if last.date != iso:
        out.append(f"（加權指數資料只到 {last.date}）")
    hi_i = t.idxmax()
    ma = {n: t.rolling(n).mean().iloc[-1] for n in (5, 20, 60, 120)}
    ma20_prev = t.rolling(20).mean().iloc[-6]
    ret = {n: (t.iloc[-1] / t.iloc[-1 - n] - 1) * 100 for n in (1, 5, 20, 60, 250) if len(t) > n}
    out.append(f"- 加權 {last.taiex:,.0f}（日 {pct(ret.get(1))}、5 日 {pct(ret.get(5))}、20 日 {pct(ret.get(20))}、"
               f"60 日 {pct(ret.get(60))}、250 日 {pct(ret.get(250))}），成交 {last.value / 1e8:,.0f} 億")
    out.append(f"- 均線 5MA {ma[5]:,.0f}／20MA {ma[20]:,.0f}（{'上彎' if ma[20] > ma20_prev else '下彎'}）"
               f"／60MA {ma[60]:,.0f}／120MA {ma[120]:,.0f}；指數距 60MA {pct((t.iloc[-1] / ma[60] - 1) * 100)}")
    out.append(f"- 資料期間最高收盤 {t[hi_i]:,.0f}（{idx.date[hi_i]}），距高點 {pct((t.iloc[-1] / t[hi_i] - 1) * 100)}")

    # ── 現貨法人 ──
    rows = []
    for f in chip_files[-10:]:
        c = pd.read_csv(f, dtype={"code": str})
        p = load_px(D / Path(f).parent.name / Path(f).name)[["code", "close"]] \
            if (D / Path(f).parent.name / Path(f).name).exists() else None
        if p is None:
            continue
        c = c.merge(p, on="code", how="left")
        v = lambda col: (c[col] * c.close).sum() / 1e8
        rows.append({"date": Path(f).stem[4:], "外資": v("f_net"), "投信": v("t_net"),
                     "自營": v("d_net"), "借券賣出": v("sbl_sell")})
    fl = pd.DataFrame(rows)
    out += ["", "## 現貨法人（億，近 10 日）", ""]
    out.append("| 日 | " + " | ".join(r["date"] for r in rows) + " |")
    out.append("|---|" + "---|" * len(rows))
    for k in ["外資", "投信", "自營", "借券賣出"]:
        out.append(f"| {k} | " + " | ".join(f"{x:+.0f}" if k != "借券賣出" else f"{x:.0f}" for x in fl[k]) + " |")
    f_sum = fl["外資"].sum()
    streak = 0
    for x in fl["外資"][::-1]:
        if (x < 0) == (fl["外資"].iloc[-1] < 0):
            streak += 1
        else:
            break
    out.append(f"\n外資 10 日合計 {yi(f_sum)} 億，連續{'賣' if fl['外資'].iloc[-1] < 0 else '買'} {streak} 日；"
               f"投信 10 日合計 {yi(fl['投信'].sum())} 億。")

    # ── 期權 ──
    inst = pd.read_csv(D / "futures" / "inst.csv")
    inst = inst[(inst.date <= iso) & inst["product"].isin(SCALE)]
    inst = inst.assign(oi=inst.oi_net * inst["product"].map(SCALE))
    foi = inst[inst.who == "foreign"].groupby("date").oi.sum().tail(20)
    pcr = pd.read_csv(D / "futures" / "pcr.csv")
    pcr = pcr[pcr.date <= iso]
    lg = pd.read_csv(D / "futures" / "large.csv")
    lg = lg[(lg.date <= iso) & (lg.month == "all") & (lg.kind == "all")]
    tx = pd.read_csv(D / "futures" / "tx.csv")
    tx = tx[tx.date <= iso]
    out += ["", "## 期權", ""]
    out.append(f"- 外資台指期未平倉淨口數（折大台）{foi.iloc[-1]:+,.0f}，前一日 {foi.iloc[-2]:+,.0f}，"
               f"20 日最低 {foi.min():+,.0f}（{foi.idxmin()}）、最高 {foi.max():+,.0f}（{foi.idxmax()}）")
    if len(tx) and len(idx):
        out.append(f"- 台指期近月 {tx.iloc[-1].close:,.0f}（{tx.iloc[-1].contract}），對現貨價差 "
                   f"{tx.iloc[-1].close - last.taiex:+,.0f}")
    pl = pcr.tail(5)
    out.append("- P/C 未平倉比近 5 日：" + "、".join(f"{r.pc_oi:.0f}%" for r in pl.itertuples()))
    if len(lg):
        r = lg.iloc[-1]
        out.append(f"- 前十大交易人淨部位 {r.top10_long - r.top10_short:+,}，前五大 {r.top5_long - r.top5_short:+,}")

    # ── 融資、投機熱度 ──
    sm = pd.read_csv(D / "margin" / "summary.csv")
    sm = sm[(sm.date <= iso) & (sm.market == "TWSE")].reset_index(drop=True)
    mx = sm.fin_amount.idxmax()
    cur = sm.iloc[-1]
    m5 = sm.iloc[-6] if len(sm) > 5 else cur
    out += ["", "## 融資與投機熱度", ""]
    out.append(f"- 上市融資 {cur.fin_amount / 1e8:,.0f} 億（{cur.date}），5 日 {yi((cur.fin_amount - m5.fin_amount) / 1e8)} 億；"
               f"資料期間最高 {sm.fin_amount[mx] / 1e8:,.0f} 億（{sm.date[mx]}），距高點 "
               f"{pct((cur.fin_amount / sm.fin_amount[mx] - 1) * 100)}；融券 {cur.sht_lots:,} 張")
    dis = pd.read_csv(D / "alert" / "disposal.csv")
    att = pd.read_csv(D / "alert" / "attention.csv")
    dm = dis.groupby(dis.ann_date.str[:7]).size().tail(4)
    am = att.groupby(att.date.str[:7]).size().tail(4)
    out.append("- 處置股公告每月：" + "、".join(f"{k} {v}" for k, v in dm.items())
               + "；注意股每月：" + "、".join(f"{k} {v}" for k, v in am.items()))

    # ── 個股與族群 ──
    def four(f):
        d = load_px(f)
        return d[d.code.str.len() == 4]
    i_now = px_files.index(str(D / day[:4] / f"{day}.csv"))
    now = four(px_files[i_now])
    m = now[["code", "name", "close", "value"]].copy()
    for k, back in (("r5", 5), ("r20", 20)):
        if i_now - back >= 0:
            prev = four(px_files[i_now - back])[["code", "close"]].rename(columns={"close": k})
            m = m.merge(prev, on="code", how="left")
            m[k] = (m.close / m[k] - 1) * 100
    cs = []
    for f in chip_files[-10:]:
        c = pd.read_csv(f, dtype={"code": str})[["code", "f_net", "t_net"]]
        p = load_px(D / Path(f).parent.name / Path(f).name)[["code", "close"]]
        c = c.merge(p, on="code")
        c["f10"] = c.f_net * c.close / 1e8
        c["t10"] = c.t_net * c.close / 1e8
        cs.append(c[["code", "f10", "t10"]])
    m = m.merge(pd.concat(cs).groupby("code").sum().reset_index(), on="code", how="left").fillna({"f10": 0, "t10": 0})
    m["val"] = m.value / 1e8

    off = pd.read_csv(D / "industry" / "official.csv", dtype={"code": str})[["code", "industry"]]
    g = m.merge(off, on="code").groupby("industry").agg(
        n=("code", "size"), val=("val", "sum"), r5=("r5", "median"), r20=("r20", "median"),
        f10=("f10", "sum"), t10=("t10", "sum")).reset_index()
    g = g[g.val >= 10].sort_values("r20", ascending=False)
    g["share"] = g.val / g.val.sum() * 100
    fmt = lambda df: df.assign(**{k: df[k].map(lambda v: f"{v:+.1f}") for k in ("r5", "r20")},
                               **{k: df[k].map(lambda v: f"{v:+.0f}") for k in ("f10", "t10")},
                               val=df.val.map(lambda v: f"{v:,.0f}"),
                               share=df.share.map(lambda v: f"{v:.1f}") if "share" in df else None)
    out += ["", "## 官方產業（中位數報酬、法人 10 日億）", ""]
    out += table(fmt(g), ["industry", "r5", "r20", "val", "share", "f10", "t10"],
                 ["產業", "5日%", "20日%", "成交億", "占比%", "外資", "投信"])

    ch = pd.read_csv(D / "industry" / "chain.csv", dtype={"code": str}).drop_duplicates(["code", "node"])
    x = ch.merge(m, on="code")
    n = x.groupby(["industry", "node"]).agg(
        n=("code", "size"), val=("val", "sum"), r5=("r5", "median"), r20=("r20", "median"),
        f10=("f10", "sum"), t10=("t10", "sum")).reset_index()
    n = n[(n.n >= 4) & (n.val >= 20)]
    n["node"] = n.industry + "／" + n.node.str.replace(r"[（(].*", "", regex=True)
    out += ["", "## 產業鏈節點 20 日最強 10", ""]
    out += table(fmt(n.sort_values("r20", ascending=False).head(10)), ["node", "r5", "r20", "val", "f10", "t10"],
                 ["節點", "5日%", "20日%", "成交億", "外資", "投信"])
    out += ["", "## 產業鏈節點 20 日最弱 10", ""]
    out += table(fmt(n.sort_values("r20").head(10)), ["node", "r5", "r20", "val", "f10", "t10"],
                 ["節點", "5日%", "20日%", "成交億", "外資", "投信"])

    sc = ["code", "name", "close", "r5", "r20", "val", "f10", "t10"]
    sh = ["代號", "名稱", "收盤", "5日%", "20日%", "成交億", "外資10日", "投信10日"]
    sfmt = lambda df: df.assign(**{k: df[k].map(lambda v: f"{v:+.1f}") for k in ("r5", "r20")},
                                **{k: df[k].map(lambda v: f"{v:+.0f}") for k in ("f10", "t10")},
                                val=df.val.map(lambda v: f"{v:,.0f}"), close=df.close.map(lambda v: f"{v:g}"))
    for title, df in [
        ("外資 10 日買超前 10", m.sort_values("f10", ascending=False).head(10)),
        ("外資 10 日賣超前 10", m.sort_values("f10").head(10)),
        ("投信 10 日買超前 10", m.sort_values("t10", ascending=False).head(10)),
        ("投信 10 日賣超前 5", m.sort_values("t10").head(5)),
        ("20 日強勢股（成交 ≥20 億，依成交額）", m[(m.val >= 20) & (m.r20 >= 8)].sort_values("val", ascending=False).head(12)),
    ]:
        out += ["", f"## {title}", ""]
        out += table(sfmt(df), sc, sh)

    OUT.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out) + "\n"
    (OUT / f"{day}.md").write_text(text, encoding="utf-8")
    (OUT / "latest.md").write_text(text, encoding="utf-8")
    print(f"wrote {OUT / (day + '.md')} ({len(text)} chars)")


if __name__ == "__main__":
    main()
