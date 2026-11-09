"""權值股槓桿頁（heavy.html）：0050 成分股的漲跌、融資、不限用途借貸與兩者合計。

輸出 data/heavy.json：
  date     結算日（融資、不限用途、股價三者都有的最後一個交易日）
  periods  {"5": 起算日, "20": …, "60": …}（往回幾個交易日）
  cols/rows 每檔一列：
    code name w(0050 權重%) g(族群) close
    f u          融資、不限用途餘額（張）
    fv uv        融資、不限用途餘額 × 收盤（億元）
    fr ur        估計維持率（%，來自 cost_site：移動平均成本、成數 60%）
    fl ul        融資使用率、不限用途使用率（餘額 ÷ 限額，%）
    p{n}         [漲跌%, 距區間最高價%, 起算日融資張數, 起算日不限用途張數]，n = 5／20／60

權值股＝0050 最新持股；族群用 config/heavy_groups.csv（產業鏈／細分族群，不用官方產業分類），
沒列到的用產業價值鏈平台第一個產業。
"""
import csv
import json
from pathlib import Path

PERIODS = (5, 20, 60)


def _read(p):
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _r(v, n=1):
    return None if v is None else round(v, n)


def _files(d, sub):
    return {p.stem: p for p in Path(d).glob(f"{sub}/[0-9][0-9][0-9][0-9]/[0-9]*.csv")}


def _groups(d, root):
    g = {}
    p = Path(root) / "config" / "heavy_groups.csv"
    if p.exists():
        g = {r["code"]: r["group"] for r in _read(p)}
    ch = Path(d) / "industry" / "chain.csv"
    fb = {}
    if ch.exists():
        for r in _read(ch):
            fb.setdefault(r["code"], r["industry"])
    return g, fb


def build(data_dir, root=None, cost=None):
    d = Path(data_dir)
    root = root or d.parent
    etf = sorted((d / "etf" / "0050").glob("[0-9]*.csv"))
    if not etf:
        return None
    hold = [r for r in _read(etf[-1]) if _f(r.get("weight"))]
    codes = {r["code"] for r in hold}
    px_f = {p.stem: p for p in d.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")}
    mf, uf = _files(d, "margin"), _files(d, "pledge")
    days = sorted(set(px_f) & set(mf) & set(uf))
    if len(days) < 2:
        return None
    days = days[-(max(PERIODS) + 1):]
    end = days[-1]

    px = {}  # day -> {code: (close, high)}
    for k in days:
        px[k] = {r["code"]: (_f(r["close"]), _f(r["high"])) for r in _read(px_f[k]) if r["code"] in codes}

    def bal(k, sub, col, lim=None):
        out = {}
        for r in _read((mf if sub == "m" else uf)[k]):
            if r["code"] in codes:
                out[r["code"]] = (_f(r.get(col)) or 0, _f(r.get(lim)) if lim else None)
        return out

    m_now, u_now = bal(end, "m", "fin_bal", "fin_limit"), bal(end, "u", "ul_bal", "ul_limit")
    refs = {n: days[-1 - n] for n in PERIODS if len(days) > n}
    m_old = {n: bal(k, "m", "fin_bal") for n, k in refs.items()}
    u_old = {n: bal(k, "u", "ul_bal") for n, k in refs.items()}

    ratio = {"m": {}, "u": {}}
    if cost:
        for key, sec in (("m", "margin"), ("u", "ul")):
            s = cost.get(sec) or {}
            if s.get("date", "").replace("-", "") == end:
                cols = s["cols"]
                for row in s["rows"]:
                    x = dict(zip(cols, row))
                    ratio[key][x["code"]] = x.get("ratio")

    grp, fb = _groups(d, root)
    rows = []
    for h in hold:
        c = h["code"]
        now = px[end].get(c)
        if not now or not now[0]:
            continue
        close = now[0]
        f, fl = m_now.get(c, (0, None))
        u, ul = u_now.get(c, (0, None))
        row = [c, h["name"].rstrip("*").strip(), _f(h["weight"]), grp.get(c) or fb.get(c) or "其他", close,
               int(f), int(u), _r(f * close / 1e5, 2), _r(u * close / 1e5, 2),
               ratio["m"].get(c), ratio["u"].get(c),
               _r(f / fl * 100, 2) if fl else None, _r(u / ul * 100, 2) if ul else None]
        for n in PERIODS:
            k = refs.get(n)
            b = px.get(k, {}).get(c) if k else None
            if not b or not b[0]:
                row.append(None)
                continue
            win = days[days.index(k) + 1:]
            hi = max((px[x][c][1] or 0) for x in win if c in px[x]) or None
            row.append([_r((close / b[0] - 1) * 100, 2), _r((close / hi - 1) * 100, 2) if hi else None,
                        int(m_old[n].get(c, (0,))[0]), int(u_old[n].get(c, (0,))[0])])
        rows.append(row)
    rows.sort(key=lambda r: -r[2])
    iso = lambda k: f"{k[:4]}-{k[4:6]}-{k[6:]}"
    return {"date": iso(end), "etf_date": etf[-1].stem, "periods": {str(n): iso(k) for n, k in refs.items()},
            "cols": ["code", "name", "w", "g", "close", "f", "u", "fv", "uv", "fr", "ur", "fl", "ul"] + [f"p{n}" for n in PERIODS],
            "rows": rows}


def write_heavy(data_dir, out_path, root=None, cost=None):
    p = build(data_dir, root, cost)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(p, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cost_site
    D = Path(__file__).resolve().parents[1] / "data"
    p = build(D, cost=cost_site.build(D))
    print(p["date"], p["periods"], len(p["rows"]))
    for r in p["rows"][:5]:
        print(r)
