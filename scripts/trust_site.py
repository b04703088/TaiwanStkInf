"""data/chips/（三大法人）＋每日股價 → 投信買賣超頁（trust.html）。

  data/trust/index.json        {dates: [最近 KEEP 個交易日，由舊到新], totals: {date: [合計億元, 買超家數, 賣超家數]}}
  data/trust/<YYYY-MM-DD>.json {date, cols, rows}：當天投信有買賣的每一檔（買賣超 ≠ 0）

欄位（張數已除 1000；比率是 %）：
  t    當日買賣超（張）          amt  當日金額（億元，股數 × 收盤估算）
  r1   當日買賣超 ÷ 當日成交量   r1x  同上，但分母扣掉現股當沖
  t5   近 5 日累計（張）         r5 / r5x  近 5 日累計 ÷ 近 5 日成交量（扣當沖）
  t20  近 20 日累計（張）        ts   連買（+）／連賣（−）天數
當沖股數空白代表該股不能當沖或沒有當沖，視為 0。
"""
import json
from pathlib import Path

from chips_site import _f, _read, chip_files, prices_for, streak

KEEP = 20       # 網頁可以切換的天數
LOOK = 60       # 往回讀幾天（算連買天數、20 日累計）
COLS = ["code", "name", "market", "close", "pct", "value", "t", "amt", "r1", "r1x", "t5", "r5", "r5x", "t20", "ts"]


def _pct(a, b):
    return round(a / b * 100, 2) if b else None


def _day_prices(data_dir, d):
    """{code: (close, volume 股, 漲跌 %)}。"""
    p = Path(data_dir) / d[:4] / (d.replace("-", "") + ".csv")
    if not p.exists():
        return {}
    out = {}
    for r in _read(p):
        c, v, ch = _f(r.get("close")), _f(r.get("volume")), _f(r.get("change"))
        if c:
            prev = c - ch if ch is not None else None
            out[r["code"]] = (c, v or 0, round(ch / prev * 100, 2) if prev else None)
    return out


def build(data_dir, keep=KEEP, look=LOOK):
    days = []
    for f in chip_files(data_dir)[-(keep + look):]:
        rows = _read(f)
        if rows:
            d = rows[0]["date"]
            days.append((d, {r["code"]: r for r in rows}, _day_prices(data_dir, d)))
    if not days:
        return None, {}
    out, totals = {}, {}
    for idx in range(max(0, len(days) - keep), len(days)):
        d, dd, px = days[idx]
        win = days[max(0, idx - look + 1): idx + 1]
        rows, tot, nb, ns = [], 0.0, 0, 0
        for code, r in sorted(dd.items()):
            t = _f(r.get("t_net"))
            if not t:
                continue
            close, vol, pct = px.get(code, (None, 0, None))

            def hist(k, n):
                return [_f(x.get(code, {}).get(k)) for _, x, _ in win[-n:]]

            def vols(n):
                v = dt = 0.0
                for _, x, p in win[-n:]:
                    vv = p.get(code, (None, 0, None))[1]
                    v += vv
                    dt += min(_f(x.get(code, {}).get("dt_vol")) or 0, vv)
                return v, dt

            ts_all = hist("t_net", look)
            t5 = sum(x for x in ts_all[-5:] if x)
            t20 = sum(x for x in ts_all[-20:] if x)
            v1, dt1 = vols(1)
            v5, dt5 = vols(5)
            amt = round(t * close / 1e8, 2) if close else None
            if amt is not None:
                tot += t * close
            nb += t > 0
            ns += t < 0
            rows.append([code, r["name"], "上市" if r["market"] == "TWSE" else "上櫃", close, pct,
                         round(close * vol / 1e8, 2) if close and vol else None,
                         round(t / 1000), amt, _pct(t, v1), _pct(t, v1 - dt1),
                         round(t5 / 1000), _pct(t5, v5), _pct(t5, v5 - dt5), round(t20 / 1000), streak(ts_all)])
        out[d] = {"date": d, "cols": COLS, "rows": rows}
        totals[d] = [round(tot / 1e8, 2), nb, ns]
    return {"dates": list(out), "totals": totals}, out


def write_trust(data_dir, out_dir):
    idx, per = build(data_dir)
    if idx is None:
        return
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    (out / "index.json").write_text(dump(idx), encoding="utf-8")
    for d, p in per.items():
        (out / f"{d}.json").write_text(dump(p), encoding="utf-8")


if __name__ == "__main__":
    import sys
    write_trust(Path(__file__).resolve().parent.parent / "data", sys.argv[1] if len(sys.argv) > 1 else "_site/data/trust")
