"""大盤頁（site/market.html，版面參考 toalpha 市場頁）→ data/market.json

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
CONTRIB_N = 60      # 指數貢獻走勢天數（期間加總另外回看到今年第一天）
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
    out = {r["date"]: _f(r["taiex"]) for r in _read(p)} if p.exists() else {}
    for r in _mkt(data_dir, "taiex"):   # fetch_market.py 的指數檔（2010 起，含開高低）
        if _f(r["close"]):
            out.setdefault(r["date"], _f(r["close"]))
    return out


def _mkt(data_dir, name):
    p = Path(data_dir) / "market" / f"{name}.csv"
    return _read(p) if p.exists() else []


def _ohlc(data_dir, name):
    return [[r["date"]] + [_f(r[k]) for k in ("open", "high", "low", "close")] for r in _mkt(data_dir, name) if _f(r["close"])]


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
        st = dict(n=0, up=0, dn=0, lu=0, ld=0, nh=0, nl=0, a20=0, a60=0, a200=0, b20=0, b60=0, b200=0, val=0.0, sret=0.0, fl=0)
        twse = []
        for r in rows:
            code = r["code"]
            st["val"] += _f(r.get("value")) or 0
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
            st["fl"] += ret == 0
            st["sret"] += ret
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
            twse.append((code, r["name"], c - ch, ret, r["market"]))
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


def contrib(days, taiex, shares, mkt="TWSE"):
    """逐日貢獻點數；再依期間（1／5／20／60 日、今年）加總每檔。mkt＝TWSE（加權指數）或 TPEx（櫃買指數）。"""
    if len(days) < 2 or not shares:
        return None
    last_d = max((d for d, _, _ in days if taiex.get(d)), default=None)
    if not last_d:
        return None
    jan = last_d[:4] + "-01-01"
    start = next((i for i, (d, _, _) in enumerate(days) if d >= jan), len(days) - CONTRIB_N)
    start = max(1, min(start, len(days) - CONTRIB_N))
    # 股數只有最新一份；分割／減資（參考價和前一日收盤差 30% 以上）之前的日子要把股數換回當時的
    last_px, ev = {}, {}   # 停牌換股時中間會缺好幾天，所以用「最後一次收盤」比
    for i in range(start - 1, len(days)):
        for c, _, pc, r, _ in days[i][2]:
            pv = last_px.get(c)
            if i >= start and pv and pc and not 0.7 <= pc / pv <= 1.3:
                ev.setdefault(i, []).append((c, pc / pv))
            last_px[c] = pc * (1 + r)
    fac, adj = {}, [None] * len(days)
    for i in range(len(days) - 1, start - 1, -1):
        adj[i] = dict(fac)
        for c, x in ev.get(i, []):
            fac[c] = fac.get(c, 1) * x
    out, names = [], {}
    for i in range(start, len(days)):
        d, _, tw = days[i]
        tw = [x[:4] for x in tw if x[4] == mkt]
        pd_ = days[i - 1][0]
        pi, ci = taiex.get(pd_), taiex.get(d)
        if not pi or not ci:
            continue
        fa = adj[i]
        mc = {c: shares[c] * fa.get(c, 1) * pc for c, _, pc, _ in tw if shares.get(c)}
        tot = sum(mc.values())
        if not tot:
            continue
        top = sorted(mc, key=mc.get, reverse=True)[:10]
        pts, w = {}, {}
        for c, n, _, r in tw:
            if c in mc and abs(r) <= 0.105:   # 新上市前 5 日沒有漲跌幅限制、參考價失真，不計
                names[c] = n
                pts[c] = pi * mc[c] / tot * r
                w[c] = mc[c] / tot * 100
        out.append({"date": d, "act": ci - pi, "est": sum(pts.values()), "top": top, "pts": pts, "w": w,
                    })
    if not out:
        return None
    last = out[-1]
    cur_top = last["top"]
    r2 = lambda v: round(v, 2)  # noqa: E731
    periods = []
    for key, lab, n in (("1", last["date"][5:].replace("-", "/"), 1), ("5", "5 日", 5), ("20", "20 日", 20),
                        ("60", "60 日", 60), ("ytd", "今年", None)):
        seg = out[-n:] if n else [o for o in out if o["date"] >= jan]
        if not seg:
            continue
        agg = {}
        for o in seg:
            for c, v in o["pts"].items():
                agg[c] = agg.get(c, 0) + v
        act = sum(o["act"] for o in seg)
        tsmc = agg.get("2330", 0)
        top10 = sum(agg.get(c, 0) for c in cur_top if c != "2330")
        est = sum(agg.values())
        rows = sorted(([c, names.get(c, ""), r2(last["w"].get(c, 0)), r2(v)] for c, v in agg.items() if abs(v) >= 0.05),
                      key=lambda r: -abs(r[3]))
        periods.append({"k": key, "lab": lab, "from": seg[0]["date"], "to": seg[-1]["date"], "act": r2(act), "est": r2(est),
                        "tsmc": r2(tsmc), "top10": r2(top10), "rest": r2(est - tsmc - top10), "rows": rows})
    ser = []
    for o in out[-CONTRIB_N:]:
        t = o["pts"].get("2330", 0)
        t10 = sum(o["pts"].get(c, 0) for c in o["top"] if c != "2330")
        ser.append([o["date"], r2(t), r2(t10), r2(o["est"] - t - t10), r2(o["act"])])
    return {"date": last["date"], "top": cur_top, "cols": ["code", "name", "w", "pts"], "periods": periods, "series": ser}


def _pct_all(vals, v, hi=True):
    """v 在 vals（全部歷史）中的百分位：hi=True 表示「低於或等於 v 的比例」。"""
    w = [x for x in vals if x is not None]
    if v is None or len(w) < PCT_MIN:
        return None
    return round(sum(1 for x in w if x <= v) / len(w) * 100)


def _chips_flow(data_dir, dates):
    """三大法人買賣超金額（億，上市＋上櫃全部證券）＝每檔買賣超股數 × 當日收盤，逐日加總。"""
    out = []
    for d in dates:
        y, ymd = d[:4], d.replace("-", "")
        cp, pp = Path(data_dir) / "chips" / y / f"{ymd}.csv", Path(data_dir) / y / f"{ymd}.csv"
        if not cp.exists() or not pp.exists():
            continue
        close = {r["code"]: _f(r["close"]) for r in _read(pp)}
        f = t = dl = 0.0
        for r in _read(cp):
            c = close.get(r["code"])
            if not c:
                continue
            f += ((_f(r["f_net"]) or 0) + (_f(r["fd_net"]) or 0)) * c
            t += (_f(r["t_net"]) or 0) * c
            dl += (_f(r["d_net"]) or 0) * c
        out.append([d, round(f / 1e8, 1), round(t / 1e8, 1), round(dl / 1e8, 1)])
    return out


def _inst_official(data_dir):
    """交易所公布的三大法人買賣金額（億，上市＋上櫃）：外資含外資自營商、自營商＝自行＋避險。兩個市場都有才算。"""
    by = {}
    for r in _mkt(data_dir, "inst"):
        f = (_f(r["f"]) or 0) + (_f(r["fd"]) or 0)
        t = _f(r["t"]) or 0
        dl = (_f(r["d_self"]) or 0) + (_f(r["d_hedge"]) or 0)
        by.setdefault(r["date"], {})[r["market"]] = (f, t, dl)
    return {d: [round(sum(v[k] for v in m.values()) / 1e8, 1) for k in range(3)] for d, m in by.items() if len(m) == 2}


def _valuation(data_dir, taiex):
    """大盤估值：每週取最後一筆（回補是每週一筆、之後每天一筆），百分位和近 10 年比。"""
    rows = [[r["date"], _f(r["pe"]), _f(r["pb"]), _f(r["dy"]), _f(r["mcap"])] for r in _mkt(data_dir, "val") if _f(r["pe"])]
    if not rows:
        return None
    from datetime import date as _d
    wk = {}
    for r in rows:
        wk[_d.fromisoformat(r[0]).isocalendar()[:2]] = r
    w = sorted(wk.values())
    last = rows[-1]
    ten = [r for r in w if r[0] >= f"{int(last[0][:4]) - 10}{last[0][4:]}"]

    def stat(k, hi=True):
        xs = [r[k] for r in ten if r[k] is not None]
        if len(xs) < 50 or last[k] is None:
            return None
        return round(sum(1 for x in xs if x <= last[k]) / len(xs) * 100)
    pes = sorted(r[1] for r in ten)
    m = sum(pes) / len(pes)
    sd = math.sqrt(sum((x - m) ** 2 for x in pes) / len(pes))
    return {"date": last[0], "pe": last[1], "pb": last[2], "dy": last[3], "mcap": last[4],
            "p_pe": stat(1), "p_pb": stat(2), "p_dy": stat(3), "med": round(pes[len(pes) // 2], 2), "mean": round(m, 2), "sd": round(sd, 2),
            "since": w[0][0], "from10": ten[0][0] if ten else None,
            "series": [[r[0], r[1], r[2], r[3], taiex.get(r[0])] for r in w if r[0] < last[0]] + [[last[0], last[1], last[2], last[3], taiex.get(last[0])]]}


def _vix(data_dir):
    rows = [[r["date"], _f(r["close"])] for r in _mkt(data_dir, "vix") if _f(r["close"])]
    if not rows:
        return None
    y1 = [r[1] for r in rows[-250:]]
    return {"date": rows[-1][0], "now": rows[-1][1], "prev": rows[-2][1] if len(rows) > 1 else None,
            "p1y": round(sum(1 for x in y1 if x <= rows[-1][1]) / len(y1) * 100), "rows": rows[-OUT_N:]}


def _big_holders(data_dir):
    """集保大戶（1000 張以上）持股比例週變化：比上週增加／減少 ≥ 1 個百分點的檔數（普通股；總股數變動 >5% 的當作增減資略過）。"""
    files = sorted((Path(data_dir) / "tdcc").glob("*.csv"))
    out, prev = [], None
    for f in files:
        cur = {r["code"]: (_f(r["p1000"]), _f(r["shares"])) for r in _read(f) if STOCK.match(r["code"])}
        if prev:
            up = dn = 0
            for c, (p, sh) in cur.items():
                q = prev.get(c)
                if p is None or not q or q[0] is None or not sh or not q[1] or abs(sh / q[1] - 1) > 0.05:
                    continue
                up += p - q[0] >= 1
                dn += p - q[0] <= -1
            d = f.stem
            out.append([f"{d[:4]}-{d[4:6]}-{d[6:]}", up, dn])
        prev = cur
    return out


def _margin_total(data_dir):
    p = Path(data_dir) / "margin" / "summary.csv"
    if not p.exists():
        return []
    by = {}
    for r in _read(p):
        v = _f(r["fin_amount"])
        if v:
            by.setdefault(r["date"], {})[r["market"]] = v
    return [[d, round(sum(m.values()) / 1e8, 1)] for d, m in sorted(by.items()) if len(m) == 2]


def _fut(data_dir):
    """外資台指淨未平倉（大台約當口：大台＋小台/4＋微台/20）與選擇權 Put/Call 未平倉比。"""
    fdir = Path(data_dir) / "futures"
    fx = {}
    if (fdir / "inst.csv").exists():
        mul = {"TX": 1, "MTX": 0.25, "TMF": 0.05}
        for r in _read(fdir / "inst.csv"):
            if r["who"] == "foreign" and r["product"] in mul and _f(r["oi_net"]) is not None:
                fx[r["date"]] = fx.get(r["date"], 0) + _f(r["oi_net"]) * mul[r["product"]]
    pcr = {}
    if (fdir / "pcr.csv").exists():
        pcr = {r["date"]: _f(r["pc_oi"]) for r in _read(fdir / "pcr.csv")}
    ds = sorted(set(fx) | set(pcr))
    return [[d, None if fx.get(d) is None else round(fx[d]), pcr.get(d)] for d in ds][-OUT_N:]


def overview(data_dir, days, taiex):
    """大盤頁的 KPI、寬度與成交值長序列、法人金額、融資餘額、期貨。"""
    tdays = [x for x in days if taiex.get(x[0])]
    if not tdays:
        return None
    dates = [d for d, _, _ in tdays]
    n = len(dates)
    adl, ew, mk = 0, 100.0, []
    for d, st, _ in tdays:
        adl += st["up"] - st["dn"]
        ew *= 1 + (st["sret"] / st["n"] if st["n"] else 0)
        pr = lambda k: round(st[f"a{k}"] / st[f"b{k}"] * 100, 1) if st[f"b{k}"] > 500 else None  # noqa: E731
        mk.append([d, taiex[d], round(st["val"] / 1e8), st["up"], st["dn"], adl, round(ew, 3), st["nh"], st["nl"],
                   pr(20), pr(60), pr(200), st["lu"], st["ld"], st["fl"]])
    cols = ["date", "taiex", "val", "up", "dn", "adl", "ew", "nh", "nl", "a20", "a60", "a200", "lu", "ld", "flat"]
    last = mk[-1]
    a60s = [r[10] for r in mk if r[10] is not None]
    srt = sorted(a60s)
    q = lambda p: srt[min(len(srt) - 1, int(p * len(srt)))] if srt else None  # noqa: E731
    upr = [r[3] / (r[3] + r[4] + r[14]) * 100 if r[3] + r[4] else None for r in mk]
    nhnl = [r[7] - r[8] if r[9] is not None else None for r in mk]
    bt = {"a20": [last[9], _pct_all([r[9] for r in mk], last[9])],
          "a60": [last[10], _pct_all(a60s, last[10])],
          "a200": [last[11], _pct_all([r[11] for r in mk], last[11])],
          "upr": [None if upr[-1] is None else round(upr[-1], 1), _pct_all(upr, upr[-1])],
          "nhnl": [nhnl[-1], _pct_all(nhnl, nhnl[-1])],
          "band60": [q(0.1), q(0.9)], "since": next((r[0] for r in mk if r[10] is not None), None)}
    flow = _chips_flow(data_dir, dates[-250:])
    off = _inst_official(data_dir)
    flow = [[r[0]] + (off[r[0]] + [1] if r[0] in off else r[1:] + [0]) for r in flow]
    for d in sorted(set(off) - {r[0] for r in flow}):
        if d >= (flow[0][0] if flow else d):
            flow.append([d] + off[d] + [1])
    flow.sort()
    mg = _margin_total(data_dir)
    fut = _fut(data_dir)
    v20 = sum(r[2] for r in mk[-21:-1]) / 20 if n > 21 else None
    k = {"date": last[0], "taiex": last[1], "chg": round(last[1] - mk[-2][1], 2) if n > 1 else None,
         "ath": max(v for v in taiex.values() if v), "val": last[2], "v20": None if v20 is None else round(v20),
         "up": last[3], "dn": last[4], "lu": last[12], "ld": last[13], "flat": last[14]}
    if flow:
        k["fnet_d"] = flow[-1][0]
        k["fnet"] = flow[-1][1]
        k["fnet_off"] = flow[-1][4]
        k["fnet5"] = round(sum(r[1] for r in flow[-5:]), 1)
    tp = _ohlc(data_dir, "tpex")
    if len(tp) > 1:
        k["tpex"] = [tp[-1][0], tp[-1][4], round(tp[-1][4] - tp[-2][4], 2), max(r[4] for r in tp)]
    if mg:
        k["mg"] = mg[-1]
        k["mg_chg"] = round(mg[-1][1] - mg[-2][1], 1) if len(mg) > 1 else None
    val = {r[0]: r[2] for r in mk}
    tx = _ohlc(data_dir, "taiex") or [[r[0], None, None, None, r[1]] for r in mk]
    return {"cols": cols, "mk": mk[-750:], "taiex_all": [r + [val.get(r[0])] for r in tx], "tpex_all": tp, "bt": bt, "kpi": k,
            "flow": flow, "margin": mg, "fut": fut, "val": _valuation(data_dir, taiex), "vix": _vix(data_dir),
            "big": _big_holders(data_dir)}


def build(data_dir):
    data_dir = Path(data_dir)
    days = breadth(data_dir)
    if not days:
        return None
    taiex = _taiex(data_dir)
    return {"fear": fear(days, taiex, _margin_ratio(data_dir)),
            "retail": retail(data_dir, taiex),
            "contrib": contrib(days, taiex, _shares(data_dir)),
            "contrib_otc": contrib(days, {r[0]: r[4] for r in _ohlc(data_dir, "tpex")}, _shares(data_dir), "TPEx"),
            "ov": overview(data_dir, days, taiex)}


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
    for p in c["periods"]:
        print("contrib", p["k"], p["from"], p["to"], p["act"], p["est"], p["tsmc"], p["top10"], p["rows"][:3])
    o = j["ov"]
    print("kpi", o["kpi"])
    print("bt", o["bt"])
    print("flow", o["flow"][-2:], "margin", o["margin"][-2:], "fut", o["fut"][-2:])
    print("size", len(json.dumps(j, ensure_ascii=False, separators=(",", ":"))))
