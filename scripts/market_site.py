"""大盤溫度頁（site/market.html）→ data/market.json

三塊：
  fear     恐慌度：6 個指標各自換算成「近 5 年（資料不足就用全部）百分位」，0＝最平靜、100＝最恐慌，
           分數＝有資料的指標平均（至少 4 個才算）。
             vol    加權指數近 20 日實際波動（年化）           高＝恐慌
             dd     加權指數離近一年（250 日）最高收盤         低＝恐慌
             ld     跌停家數比例（5 日平均）                    高＝恐慌
             nl     創 52 週新低家數比例（5 日平均）            高＝恐慌
             a200   站上 200 日線家數比例                       低＝恐慌
             mr     大盤估計融資維持率（margin_site 同算法）    低＝恐慌（融資資料 2025-07 起）
           個股＝上市櫃普通股（代號 1～9 開頭 4 碼）；用每日「漲跌 ÷ 參考價」連乘的還原價，除權息不算跌。
  retail   散戶台指多空比：小台＋微台全市場未平倉扣掉三大法人＝散戶。
           散戶淨部位 ＝ −(三大法人淨未平倉)；多空比 ＝ 散戶淨部位 ÷ 全市場未平倉（%）。
           合併時微台 5 口＝小台 1 口（微台 2024-07-29 上市，之前只有小台）。
  contrib  誰在推指數（上市）：每檔貢獻點數 ＝ 前一日加權指數 × 前一日市值權重 × 當日漲跌幅。
           股數用最新一份集保股權分散表的集保總股數（近似發行股數）；合計會和實際漲跌有小誤差。
"""
import csv
import json
import math
import re
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import margin_site  # noqa: E402

STOCK = re.compile(r"^[1-9]\d{3}$")
PCT_WIN = 1250      # 百分位回看（約 5 年）
PCT_MIN = 120       # 少於這麼多天的歷史就不算百分位
OUT_N = 500         # 走勢圖保留天數（約 2 年）
CONTRIB_N = 60      # 指數貢獻走勢天數
BANDS = [(20, "平靜"), (40, "正常"), (60, "緊張"), (80, "恐慌"), (101, "極度恐慌")]
COMPS = [  # key, 名稱, 單位, 高＝恐慌?
    ("vol", "加權指數實際波動（近 20 日，年化）", "%", True),
    ("dd", "加權指數離近一年高點", "%", False),
    ("ld", "跌停家數比例（5 日平均）", "%", True),
    ("nl", "創 52 週新低家數比例（5 日平均）", "%", True),
    ("a200", "站上 200 日線的比例", "%", False),
    ("mr", "大盤估計融資維持率", "%", False),
]


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def price_files(data_dir):
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    return [f for f in files if len(f.stem) == 8]


def band(s):
    if s is None:
        return None
    return next(n for b, n in BANDS if s < b)


def _taiex(data_dir):
    p = Path(data_dir) / "margin" / "index.csv"
    return {r["date"]: _f(r["taiex"]) for r in _read(p)} if p.exists() else {}


def _shares(data_dir):
    files = sorted((Path(data_dir) / "tdcc").glob("*.csv"))
    if not files:
        return {}
    return {r["code"]: _f(r["shares"]) for r in _read(files[-1]) if _f(r.get("shares"))}


def breadth(data_dir):
    """逐日：家數、上漲、下跌、漲停、跌停、新高、新低、站上 20/60/200 日線家數；以及上市每檔 (代號, 名稱, 前收, 漲跌幅)。"""
    hist = {}   # code -> [還原價序列, 前綴和, 最大值單調佇列, 最小值單調佇列]（佇列放索引）
    days = []
    for f in price_files(data_dir):
        rows = _read(f)
        if not rows:
            continue
        d = rows[0]["date"]
        st = dict(n=0, up=0, dn=0, lu=0, ld=0, nh=0, nl=0, a20=0, a60=0, a200=0, b20=0, b60=0, b200=0)
        twse = []
        for r in rows:
            code = r["code"]
            if not STOCK.match(code):
                continue
            c, ch = _f(r["close"]), _f(r["change"])
            if not c or ch is None or c - ch <= 0:
                continue
            ret = ch / (c - ch)
            h = hist.get(code)
            if h is None:
                h = hist[code] = [[100.0], [0.0, 100.0], deque([0]), deque([0])]
            px, ps, qmax, qmin = h
            k = len(px)          # 新值的索引；前面有 k 筆
            a = px[-1] * (1 + ret)
            st["n"] += 1
            st["up"] += ret > 0
            st["dn"] += ret < 0
            st["lu"] += ret >= 0.095
            st["ld"] += ret <= -0.095
            while qmax and qmax[0] < k - 250:
                qmax.popleft()
            while qmin and qmin[0] < k - 250:
                qmin.popleft()
            if k >= 241:
                st["nh"] += a > px[qmax[0]]
                st["nl"] += a < px[qmin[0]]
            for n in (20, 60, 200):
                if k >= n:
                    st[f"b{n}"] += 1
                    st[f"a{n}"] += a > (ps[k] - ps[k - n + 1] + a) / n
            px.append(a)
            ps.append(ps[-1] + a)
            while qmax and px[qmax[-1]] <= a:
                qmax.pop()
            qmax.append(k)
            while qmin and px[qmin[-1]] >= a:
                qmin.pop()
            qmin.append(k)
            if r["market"] == "TWSE":
                twse.append((code, r["name"], c - ch, ret))
        days.append((d, st, twse))
    return days


def pct_rank(vals, i, hi):
    """vals[i] 在前 PCT_WIN 天（含當天）中的恐慌百分位。hi=True：值越高越恐慌。"""
    v = vals[i]
    if v is None:
        return None
    w = [x for x in vals[max(0, i - PCT_WIN + 1):i + 1] if x is not None]
    if len(w) < PCT_MIN:
        return None
    le = sum(1 for x in w if (x <= v if hi else x >= v))
    return round(le / len(w) * 100)


def fear(days, taiex, mratio):
    dates = [d for d, _, _ in days]
    tx = [taiex.get(d) for d in dates]
    raw = {k: [None] * len(dates) for k, *_ in COMPS}
    ld_r = [st["ld"] / st["n"] * 100 if st["n"] else None for _, st, _ in days]
    nl_r = [st["nl"] / st["b200"] * 100 if st["b200"] > 500 else None for _, st, _ in days]  # 有一年歷史的檔數夠多才算
    for i in range(len(dates)):
        if i >= 20 and all(tx[j] for j in range(i - 20, i + 1)):
            lr = [math.log(tx[j] / tx[j - 1]) for j in range(i - 19, i + 1)]
            m = sum(lr) / 20
            raw["vol"][i] = math.sqrt(sum((x - m) ** 2 for x in lr) / 19) * math.sqrt(252) * 100
        if tx[i] and i >= 60:
            hi = max(x for x in tx[max(0, i - 249):i + 1] if x)
            raw["dd"][i] = (tx[i] / hi - 1) * 100
        for k, src in (("ld", ld_r), ("nl", nl_r)):
            w = [x for x in src[max(0, i - 4):i + 1] if x is not None]
            raw[k][i] = sum(w) / len(w) if len(w) == 5 else None
        st = days[i][1]
        raw["a200"][i] = st["a200"] / st["b200"] * 100 if st["b200"] > 500 else None
        raw["mr"][i] = mratio.get(dates[i])
    pc = {k: [pct_rank(raw[k], i, hi) for i in range(len(dates))] for k, _, _, hi in COMPS}
    score = []
    for i in range(len(dates)):
        got = [pc[k][i] for k, *_ in COMPS if pc[k][i] is not None]
        score.append(round(sum(got) / len(got)) if len(got) >= 4 else None)
    last = len(dates) - 1
    while last > 0 and score[last] is None:
        last -= 1
    r1 = lambda v, n=1: None if v is None else round(v, n)  # noqa: E731
    at = lambda arr, j: arr[j] if 0 <= j < len(arr) else None  # noqa: E731
    comps = [{"k": k, "name": nm, "unit": u, "hi": hi,
              "now": r1(raw[k][last], 2), "prev": r1(at(raw[k], last - 1), 2), "week": r1(at(raw[k], last - 5), 2),
              "p": pc[k][last], "pp": at(pc[k], last - 1), "pw": at(pc[k], last - 5),
              "s60": [r1(x, 2) for x in raw[k][max(0, last - 59):last + 1]]}
             for k, nm, u, hi in COMPS]
    first = next((i for i, s in enumerate(score) if s is not None), last)
    lo = max(first, last - OUT_N + 1)
    series = [[dates[i], score[i], tx[i]] for i in range(lo, last + 1)]
    # 歷次進入極度恐慌（≥80 且前 20 天都 <80）
    ext = []
    for i in range(first, last + 1):
        if score[i] is not None and score[i] >= 80 and all((score[j] or 0) < 80 for j in range(max(first, i - 20), i)):
            ext.append([dates[i], score[i], r1(raw["dd"][i])])
    br = [[dates[i]] + [round(days[i][1][f"a{n}"] / days[i][1][f"b{n}"] * 100, 1) if days[i][1][f"b{n}"] > 500 else None
                        for n in (20, 60, 200)] + [days[i][1]["nh"], days[i][1]["nl"], days[i][1]["up"], days[i][1]["dn"]]
          for i in range(lo, last + 1)]
    return {"date": dates[last], "score": score[last], "band": band(score[last]),
            "prev": at(score, last - 1), "week": at(score, last - 5), "month": at(score, last - 20),
            "since": dates[first], "comps": comps, "series": series, "extreme": ext[-12:], "breadth": br,
            "bands": [[b, n] for b, n in BANDS]}


def _margin_ratio(data_dir):
    try:
        mdir = Path(data_dir) / "margin"
        days = margin_site.load_days(data_dir, 100000)
        summary = _read(mdir / "summary.csv") if (mdir / "summary.csv").exists() else []
        index = _read(mdir / "index.csv") if (mdir / "index.csv").exists() else []
        rows = margin_site.market_series(data_dir, days, summary, index)
        i = margin_site.MARKET_COLS.index("all_ratio")
        return {r[0]: r[i] for r in rows if r[i]}
    except Exception as e:  # noqa: BLE001
        print(f"market_site: 維持率算不出來 {e!r}", file=sys.stderr)
        return {}


def retail(data_dir, taiex):
    fdir = Path(data_dir) / "futures"
    if not (fdir / "inst.csv").exists() or not (fdir / "mini.csv").exists():
        return None
    net, fx = {}, {}
    for r in _read(fdir / "inst.csv"):
        v = _f(r["oi_net"])
        if v is None:
            continue
        if r["product"] in ("MTX", "TMF"):
            k = (r["date"], r["product"])
            net[k] = net.get(k, 0) + v
        elif r["product"] == "TX" and r["who"] == "foreign":
            fx[r["date"]] = v
    oi = {(r["date"], r["product"]): _f(r["oi_all"]) for r in _read(fdir / "mini.csv")}
    rows = []
    for d in sorted({d for d, _ in oi}):
        m_oi, t_oi = oi.get((d, "MTX")), oi.get((d, "TMF"))
        m_n, t_n = net.get((d, "MTX")), net.get((d, "TMF"))
        if not m_oi or m_n is None:
            continue
        mr = -m_n / m_oi * 100
        tr = -t_n / t_oi * 100 if t_oi and t_n is not None else None
        den = m_oi + (t_oi / 5 if t_oi and t_n is not None else 0)
        cr = -(m_n + (t_n / 5 if t_oi and t_n is not None else 0)) / den * 100
        rows.append([d, round(cr, 2), round(mr, 2), None if tr is None else round(tr, 2),
                     None if fx.get(d) is None else int(fx[d]), taiex.get(d),
                     int(-(m_n + (t_n / 5 if t_n is not None else 0)))])
    if not rows:
        return None
    w = [r[1] for r in rows[-250:]]
    last = rows[-1]
    p = round(sum(1 for x in w if x <= last[1]) / len(w) * 100)
    flips = [r[0] for a, r in zip(rows[-OUT_N - 1:], rows[-OUT_N:]) if (a[1] > 0) != (r[1] > 0)]
    return {"date": last[0], "now": last[1], "prev": rows[-2][1] if len(rows) > 1 else None, "p1y": p,
            "cols": ["date", "ratio", "mtx", "tmf", "fx_tx", "taiex", "net"], "rows": rows[-OUT_N:], "flips": flips}


def contrib(days, taiex, shares):
    if len(days) < 2 or not shares:
        return None
    out = []
    for i in range(max(1, len(days) - CONTRIB_N), len(days)):
        d, _, tw = days[i]
        pd_ = days[i - 1][0]
        pi, ci = taiex.get(pd_), taiex.get(d)
        if not pi or not ci:
            continue
        mc = {c: shares[c] * pc for c, _, pc, _ in tw if shares.get(c)}
        tot = sum(mc.values())
        if not tot:
            continue
        top = sorted(mc, key=mc.get, reverse=True)[:10]
        rows = [[c, n, round(r * 100, 2), round(mc[c] / tot * 100, 3), round(pi * mc[c] / tot * r, 2)] for c, n, _, r in tw if c in mc]
        pts = {r[0]: r[4] for r in rows}
        out.append({"date": d, "prev": pi, "close": ci, "act": round(ci - pi, 2), "est": round(sum(pts.values()), 2),
                    "tsmc": round(pts.get("2330", 0), 2), "top10": round(sum(pts.get(c, 0) for c in top if c != "2330"), 2),
                    "top": top, "rows": rows})
    if not out:
        return None
    last = out[-1]
    last["rows"].sort(key=lambda r: -abs(r[4]))
    return {"date": last["date"], "prev": last["prev"], "close": last["close"], "act": last["act"], "est": last["est"],
            "tsmc": last["tsmc"], "top10": last["top10"], "top": last["top"],
            "cols": ["code", "name", "ret", "w", "pts"], "rows": last["rows"],
            "series": [[o["date"], o["tsmc"], o["top10"], round(o["est"] - o["tsmc"] - o["top10"], 2), o["act"]] for o in out]}


def build(data_dir):
    data_dir = Path(data_dir)
    days = breadth(data_dir)
    if not days:
        return None
    taiex = _taiex(data_dir)
    return {"fear": fear(days, taiex, _margin_ratio(data_dir)),
            "retail": retail(data_dir, taiex),
            "contrib": contrib(days, taiex, _shares(data_dir))}


def write(data_dir, out_path):
    j = build(data_dir)
    if j is None:
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    import time
    t = time.time()
    j = build(Path(__file__).resolve().parent.parent / "data")
    f = j["fear"]
    print(f"{time.time() - t:.1f}s", f["date"], f["score"], f["band"], f["since"])
    for c in f["comps"]:
        print(c["name"], c["now"], c["p"])
    print("extreme", f["extreme"])
    print("retail", j["retail"] and {k: j["retail"][k] for k in ("date", "now", "p1y")})
    c = j["contrib"]
    print("contrib", c["date"], c["act"], c["est"], c["tsmc"], c["top10"], c["rows"][:5])
