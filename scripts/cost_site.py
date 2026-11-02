"""估計持股成本（cost.html）：主動式 ETF、融資、不限用途借貸的平均成本與維持率。

輸出 data/cost.json：
  etf      主動式 ETF 對各股的估計平均成本（每檔 ETF × 每檔股票），etf_agg 為全部主動式 ETF 合計
  margin   個股融資估計平均成本、維持率、130% 追繳價
  ul       個股不限用途借貸（股票質借）估計設質均價、維持率、130% 追繳價
  calib    大盤校驗：Σ(融資張數 × 估計成本 × 融資成數) 對比官方融資金額

估計方式（移動平均成本法）：
  · 價格用當日成交均價 VWAP（成交金額 ÷ 成交股數），比收盤更接近當天實際成交成本；
    兩次持股公布之間隔了好幾天時，用這段期間的合計 VWAP。
  · 增加的部位以 VWAP 計入成本；減少的部位以當時平均成本扣除（平均成本不變）。
  · 資料第一天既有的部位（起始部位）沒有成本資訊，以當天收盤計，並追蹤它還剩幾成（base）：
    起始部位佔比越高，估計越不可靠。
  · 維持率 ＝ 收盤 ÷ (平均成本 × 成數)；追繳價 ＝ 平均成本 × 成數 × 130%。
    融資成數：上市、上櫃都用 60%（大盤校驗兩市場的官方融資金額都約是估計值的 88%，比例一致）；不限用途：假設 60%（券商自訂，實際常低於此，維持率會更高）。
  · 配股（除權）、分割、面額變更、減資：股數 ×m、平均成本 ÷m（總成本不變，m 由 data/adjust/events.csv 推算），
    不然配股後股數暴增會被當成用市價買進、成本嚴重高估；融資／借貸的公布張數不含配股（配股進擔保品），
    只把每股成本 ÷m。現金股利不調整成本。調降成數、停止融資的個股未處理。
"""
import csv
import json
import re
from pathlib import Path

from etf_site import date_of, read_holdings

FIN_RATIO = {"TWSE": 0.6, "TPEx": 0.6}
UL_RATIO = 0.6
CALL = 1.3
TW = re.compile(r"^\d{4,6}[A-Z]?$")


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _r(v, n=2):
    return None if v is None else round(v, n)


class Prices:
    """每日行情：{date: {code: (market, close, volume, value)}}，只在需要時讀檔。"""

    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.files = {date_of(f): f for f in self.dir.glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv")}
        self.days = sorted(self.files)
        self.cache = {}

    def day(self, d):
        if d not in self.cache:
            out = {}
            f = self.files.get(d)
            if f:
                for r in _read(f):
                    c = _f(r.get("close"))
                    if c:
                        out[r["code"]] = (r["market"], c, _f(r.get("volume")) or 0, _f(r.get("value")) or 0)
            self.cache[d] = out
        return self.cache[d]

    def vwap(self, code, days):
        """多日合計 VWAP；沒有成交時退回最後一天收盤。"""
        vol = val = 0.0
        last = None
        for d in days:
            x = self.day(d).get(code)
            if x:
                vol += x[2]
                val += x[3]
                last = x[1]
        return val / vol if vol > 0 and val > 0 else last

    def close(self, code, d):
        x = self.day(d).get(code)
        return x[1] if x else None

    def between(self, a, b):
        """交易日 a < d ≤ b。"""
        return [d for d in self.days if a < d <= b]


def share_events(data_dir):
    """{日期: {代號: 股數倍數 m}}：除權、除權息（扣掉現金部分）、分割、反分割、面額變更、減資。"""
    p = Path(data_dir) / "adjust" / "events.csv"
    out = {}
    if not p.exists():
        return out
    for r in _read(p):
        if r["kind"] == "除息":
            continue
        f, prev, ref, cash = _f(r.get("factor")), _f(r.get("prev_close")), _f(r.get("ref_price")), _f(r.get("cash")) or 0
        if not f or f <= 0:
            continue
        m = (prev - cash) / ref if r["kind"] == "除權息" and prev and ref else 1 / f
        if abs(m - 1) > 0.005:
            d = out.setdefault(r["date"], {})
            d[r["code"]] = d.get(r["code"], 1) * m
    return out


class Book:
    """一個部位的移動平均成本；base＝起始部位還剩多少股。"""

    __slots__ = ("sh", "avg", "base", "buy_sh", "buy_val")

    def __init__(self, sh, px, base=True):
        self.sh, self.avg, self.base = sh, px, (sh if base else 0.0)
        self.buy_sh, self.buy_val = (0.0, 0.0) if base else (sh, sh * px)  # 起算後累計買進（不扣賣出）

    def scale(self, m):
        """配股／分割：股數 ×m、成本 ÷m。"""
        self.sh *= m
        self.base *= m
        self.buy_sh *= m
        self.avg /= m

    def move(self, new_sh, px):
        """部位變成 new_sh：增加以 px 計成本，減少則按比例扣除（含起始部位）。"""
        if new_sh > self.sh:
            if px is not None:
                self.avg = (self.sh * self.avg + (new_sh - self.sh) * px) / new_sh
                self.buy_sh += new_sh - self.sh
                self.buy_val += (new_sh - self.sh) * px
        elif new_sh < self.sh and self.sh > 0:
            self.base *= new_sh / self.sh
        self.sh = new_sh

    def flow(self, out, buy, px):
        """融資／借貸：先扣掉償還（按平均成本），再加入新增（以 px 計）。"""
        if self.sh > 0 and out > 0:
            keep = max(self.sh - out, 0)
            self.base *= keep / self.sh
            self.sh = keep
        if buy > 0 and px is not None:
            self.avg = (self.sh * self.avg + buy * px) / (self.sh + buy) if self.sh > 0 else px
            self.sh += buy


def volume_ex_dt(data_dir, prices, n=5):
    """近 n 個交易日成交股數扣掉現股當沖（data/chips 的 dt_vol；當沖資料晚兩天定案，缺的那天用全部成交量）。
    回傳 ({代號: 股數}, 交易日清單, 有當沖資料的天數)。"""
    days = prices.days[-n:]
    out, ok = {}, 0
    for d in days:
        f = Path(data_dir) / "chips" / d[:4] / (d.replace("-", "") + ".csv")
        dt = {r["code"]: _f(r.get("dt_vol")) or 0 for r in _read(f)} if f.exists() else {}
        ok += bool(dt)
        for c, x in prices.day(d).items():
            out[c] = out.get(c, 0) + max(x[2] - min(dt.get(c, 0), x[2]), 0)
    return out, days, ok


# ---------------- 主動式 ETF ----------------
def build_etf(data_dir, prices, events=None):
    events = events or {}
    etf_dir = Path(data_dir) / "etf"
    with (etf_dir / "etf_list.csv").open(encoding="utf-8") as fp:
        actives = [r for r in csv.DictReader(fp) if r["kind"] == "active"]
    etfs, rows = [], []
    agg = {}
    latest = prices.days[-1] if prices.days else None
    vol5, vdays, vok = volume_ex_dt(data_dir, prices)
    mult = lambda sh, c: round(sh / vol5[c], 2) if vol5.get(c) else None  # noqa: E731  停損倍數＝持股 ÷ 近 5 日成交量（扣當沖）
    for info in actives:
        files = sorted((etf_dir / info["etf"]).glob("[0-9]*.csv"))
        if not files:
            continue
        books, names, prev_d = {}, {}, None
        for f in files:
            d, h = date_of(f), read_holdings(f)
            span = prices.between(prev_d, d) if prev_d else [d]
            for c in set(books) | set(h):
                if not TW.match(c):
                    continue
                sh = (h.get(c) or {}).get("sh")
                if c in h and sh is None:
                    continue
                sh = sh or 0
                if c in h:
                    names[c] = h[c]["name"]
                b = books.get(c)
                if b is None:
                    if sh <= 0:
                        continue
                    if prev_d is None:  # 起始部位：以當天收盤計
                        px = prices.close(c, d) or prices.vwap(c, span)
                        if px:
                            books[c] = Book(sh, px)
                    else:
                        px = prices.vwap(c, span)
                        if px:
                            books[c] = Book(sh, px, base=False)
                    continue
                for x in span:
                    if c in events.get(x, {}):
                        b.scale(events[x][c])
                b.move(sh, prices.vwap(c, span))
                if b.sh <= 0:
                    del books[c]
            prev_d = d
        last = read_holdings(files[-1])
        ago = {n: read_holdings(files[-1 - n]) if len(files) > n else {} for n in (5, 20)}

        def chg(c, n):  # 近 n 份持股的張數增減（配股、分割會讓數字跳動）
            if not ago[n]:
                return None
            return round(((last.get(c) or {}).get("sh") or 0) / 1000 - ((ago[n].get(c) or {}).get("sh") or 0) / 1000)
        e = len(etfs)
        etfs.append([info["etf"], info["name"], date_of(files[0]), prev_d, len(files)])
        for c, b in books.items():
            close = prices.close(c, latest) or prices.close(c, prev_d)  # 一律用最新收盤比較，各 ETF 公布日不同
            if close is None:
                continue
            w = (last.get(c) or {}).get("w")
            bpx = b.buy_val / b.buy_sh if b.buy_sh else None
            rows.append([e, c, names.get(c, ""), round(b.sh / 1000), w, _r(b.avg), close,
                         _r((close / b.avg - 1) * 100, 1), round(b.base / b.sh * 100) if b.sh else None,
                         round(b.buy_sh / 1000), _r(bpx), chg(c, 5), chg(c, 20), mult(b.sh, c)])
            a = agg.setdefault(c, {"name": names.get(c, ""), "sh": 0.0, "cost": 0.0, "base": 0.0, "n": 0, "close": close,
                                   "buy_sh": 0.0, "buy_val": 0.0, "d5": 0, "d20": 0})
            a["d5"] += chg(c, 5) or 0
            a["d20"] += chg(c, 20) or 0
            a["sh"] += b.sh
            a["cost"] += b.sh * b.avg
            a["base"] += b.base
            a["n"] += 1
            a["buy_sh"] += b.buy_sh
            a["buy_val"] += b.buy_val
    agg_rows = []
    for c, a in agg.items():
        avg = a["cost"] / a["sh"]
        agg_rows.append([c, a["name"], a["n"], round(a["sh"] / 1000), _r(avg), a["close"],
                         _r((a["close"] / avg - 1) * 100, 1), round(a["base"] / a["sh"] * 100),
                         round(a["sh"] * a["close"]), round(a["buy_sh"] / 1000),
                         _r(a["buy_val"] / a["buy_sh"]) if a["buy_sh"] else None, a["d5"], a["d20"], mult(a["sh"], c)])
    agg_rows.sort(key=lambda x: -x[8])
    return {"etfs": etfs, "etf_cols": ["code", "name", "start", "date", "n"],
            "cols": ["e", "code", "name", "lots", "w", "cost", "close", "pnl", "base", "buy", "buy_px", "d5", "d20", "mult"], "rows": rows,
            "agg_cols": ["code", "name", "n", "lots", "cost", "close", "pnl", "base", "val", "buy", "buy_px", "d5", "d20", "mult"], "agg": agg_rows,
            "vol_days": [vdays[0], vdays[-1]] if vdays else None, "vol_dt_days": vok}


# ---------------- 融資、不限用途 ----------------
def _track(files, prices, out_f, buy_f, bal_f, events=None):
    events = events or {}
    """逐日追蹤 {(market, code): Book}，回傳 (books, 最後一天 rows, 最後日期, 起算日)。"""
    books, rows, d, start = {}, {}, None, None
    for f in files:
        rs = _read(f)
        if not rs:
            continue
        d = rs[0]["date"]
        start = start or d
        day = prices.day(d)
        rows = {}
        for r in rs:
            k = (r["market"], r["code"])
            rows[k] = r
            bal = _f(r.get(bal_f)) or 0
            x = day.get(r["code"])
            px = (x[3] / x[2]) if x and x[2] > 0 and x[3] > 0 else (x[1] if x else None)
            b = books.get(k)
            if b is None or b.sh <= 0:
                if bal > 0 and x:
                    first = d == start  # 起算日既有餘額：成本以收盤計；之後才出現的以當天 VWAP 計
                    books[k] = Book(bal, x[1] if first else px, base=first)
                continue
            m = events.get(d, {}).get(r["code"])
            if m:  # 融資／擔保餘額張數不因配股改變，配股進擔保品：維持率要用每股成本 ÷m 算
                b.avg /= m
            b.flow(sum(_f(r.get(o)) or 0 for o in out_f), _f(r.get(buy_f)) or 0, px)
            if abs(b.sh - bal) > max(1, bal * 0.001):  # 收支對不上（資料修正、合併等）：以公布餘額為準
                b.move(bal, px)
    return books, rows, d, start


def _cost_rows(books, rows, prices, d, ratio_of, bal_f, extra=None):
    out = []
    day = prices.day(d)
    for k, r in rows.items():
        b = books.get(k)
        bal = _f(r.get(bal_f)) or 0
        x = day.get(k[1])
        if not b or bal <= 0 or not x:
            continue
        close, q = x[1], ratio_of(k[0])
        call_px = b.avg * q * CALL
        row = [k[0], k[1], r.get("name", "").strip(), close, int(bal), round(bal * 1000 * close), _r(b.avg),
               round(close / (b.avg * q) * 100), _r(call_px), _r((call_px / close - 1) * 100, 1),
               round(b.base / b.sh * 100) if b.sh else None]
        if extra:
            row += extra(k, r)
        out.append(row)
    out.sort(key=lambda x: -x[5])
    return out


COST_COLS = ["market", "code", "name", "close", "bal", "val", "cost", "ratio", "call", "call_dist", "base"]


def build_margin(data_dir, prices, events=None):
    files = sorted(Path(data_dir).glob("margin/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if not files:
        return None, None
    books, rows, d, start = _track(files, prices, ("fin_sell", "fin_cash"), "fin_buy", "fin_bal", events)
    # 5 日前餘額：看最近有沒有大量新增（新增的成本最準）
    ago = _read(files[-6]) if len(files) > 5 else []
    prev = {(r["market"], r["code"]): _f(r.get("fin_bal")) for r in ago}

    def extra(k, r):
        p, b = prev.get(k), _f(r.get("fin_bal"))
        return [None if p is None or b is None else int(b - p)]

    rows_out = _cost_rows(books, rows, prices, d, FIN_RATIO.get, "fin_bal", extra)
    # 大盤校驗：估計借款 Σ(張數 × 1000 × 成本 × 成數) vs 官方融資金額
    calib = []
    sp = Path(data_dir) / "margin" / "summary.csv"
    if sp.exists():
        official = {r["market"]: _f(r["fin_amount"]) for r in _read(sp) if r["date"] == d}
        for m in ("TWSE", "TPEx"):
            est = sum(b.sh * 1000 * b.avg * FIN_RATIO[m] for k, b in books.items()
                      if k[0] == m and (_f(rows.get(k, {}).get("fin_bal")) or 0) > 0)
            mv = sum((_f(r.get("fin_bal")) or 0) * 1000 * (prices.close(k[1], d) or 0) for k, r in rows.items() if k[0] == m)
            calib.append([m, _r(est / 1e8, 1), _r((official.get(m) or 0) / 1e8, 1), _r(mv / 1e8, 1)])
    return {"date": d, "start": start, "cols": COST_COLS + ["b5"], "rows": rows_out}, calib


def build_ul(data_dir, prices, events=None):
    files = sorted(Path(data_dir).glob("pledge/[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)
    if not files:
        return None
    books, rows, d, start = _track(files, prices, ("ul_sell", "ul_cash", "ul_swap"), "ul_new", "ul_bal", events)

    def extra(k, r):
        lim = _f(r.get("ul_limit"))
        bal = _f(r.get("ul_bal")) or 0
        return [round(bal / lim * 100, 1) if lim else None]

    return {"date": d, "start": start, "cols": COST_COLS + ["use"],
            "rows": _cost_rows(books, rows, prices, d, lambda m: UL_RATIO, "ul_bal", extra)}


def build(data_dir):
    prices, ev = Prices(data_dir), share_events(data_dir)
    margin, calib = build_margin(data_dir, prices, ev)
    return {"params": {"fin_ratio": FIN_RATIO, "ul_ratio": UL_RATIO, "call": CALL * 100},
            "etf": build_etf(data_dir, prices, ev), "margin": margin, "ul": build_ul(data_dir, prices, ev), "calib": calib}


def write_cost(data_dir, out_path):
    payload = build(data_dir)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    p = build(Path(__file__).resolve().parents[1] / "data")
    print(json.dumps(p["calib"], ensure_ascii=False))
    print(len(p["etf"]["rows"]), len(p["margin"]["rows"]), len(p["ul"]["rows"]))
    for r in p["etf"]["agg"][:12]:
        print(r)
    for r in p["margin"]["rows"][:8]:
        print(r)
    for r in p["ul"]["rows"][:8]:
        print(r)
    sys.exit(0)
