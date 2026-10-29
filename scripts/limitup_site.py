"""漲停頁（limitup.html）用的 JSON：最近 DAYS 個交易日每天的漲停股。

  data/limitup.json
    days    [YYYYMMDD...]
    count   {"lu": [每天收漲停家數], "touch": [觸及漲停但打開家數], "ld": [收跌停家數]}
    cols    rows 的欄位
    rows    {YYYYMMDD: [[...], ...]}，每天每檔一列
              state  1＝收在漲停（鎖住），0＝盤中觸及漲停但收盤打開
              streak 連續收漲停天數（含當天；打開的是 0）
              next   隔天收盤漲跌幅（%），最新一天是 null
    tags    {code: [[產業鏈產業...], [細分族群...]]}

漲停價＝參考價×1.1，依漲停價所在的升降單位無條件捨去；參考價＝收盤－漲跌（除權息當天就是除權息參考價）。
最高價超過推算漲停價的（新股上市前 5 天無漲跌幅限制、參考價另行調整）不列入。
只算上市櫃普通股（4 碼、1–9 開頭，含 KY、DR）。
"""
import csv
import json
import re
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

import industry_site

DAYS = 20
LOOK = 60  # 算連板往回看幾天
STOCK = re.compile(r"^[1-9]\d{3}$")
COLS = ["code", "name", "market", "state", "close", "chg", "vol", "value", "streak", "next"]
TICKS = [(10, "0.01"), (50, "0.05"), (100, "0.1"), (500, "0.5"), (1000, "1")]


def tick(p):
    for lim, t in TICKS:
        if p < lim:
            return Decimal(t)
    return Decimal("5")


def limit(ref, up=True):
    raw = ref * (Decimal("1.1") if up else Decimal("0.9"))
    mode = ROUND_FLOOR if up else ROUND_CEILING
    t = tick(raw)
    p = (raw / t).to_integral_value(mode) * t
    if tick(p) != t:  # 剛好跨過升降單位的分界
        t = tick(p)
        p = (raw / t).to_integral_value(mode) * t
    return p


def _d(s):
    try:
        return Decimal(s.replace(",", ""))
    except Exception:
        return None


def scan_day(path):
    """回傳 ({code: 當天資料}, 收跌停家數)。"""
    out, ld = {}, 0
    with Path(path).open(encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            code = r["code"].strip()
            if not STOCK.match(code):
                continue
            c, ch, h, lo = _d(r["close"]), _d(r["change"]), _d(r["high"]), _d(r["low"])
            if None in (c, ch, h, lo):
                continue
            ref = c - ch
            if ref <= 0:
                continue
            ref_val = float(ref)
            info = {"name": r["name"].strip(), "market": "上市" if r["market"] == "TWSE" else "上櫃",
                    "close": float(c), "chg": round(float(ch) / ref_val * 100, 2)}
            lu = limit(ref)
            if lu <= h <= lu:  # 最高價剛好是漲停價（超過代表沒有漲跌幅限制或參考價另算）
                info.update(state=1 if c >= lu else 0,
                            vol=round((_d(r["volume"]) or 0) / 1000),
                            value=round(float(_d(r["value"]) or 0) / 1e8, 2))
            if c == limit(ref, up=False) and lo == c:
                ld += 1
            out[code] = info
    return out, ld


def build(data_dir, ind=None):
    files = sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name)[-(LOOK + 1):]
    if not files:
        return None
    seq = []
    for p in files:
        day, ld = scan_day(p)
        seq.append((int(p.stem), day, ld))

    streak = {}
    days, rows, count = [], {}, {"lu": [], "touch": [], "ld": []}
    show_from = len(seq) - DAYS
    for i, (d, day, ld) in enumerate(seq):
        new = {}
        for code, s in day.items():
            if s.get("state") == 1:
                new[code] = streak.get(code, 0) + 1
        streak = new
        if i < show_from:
            continue
        nxt = seq[i + 1][1] if i + 1 < len(seq) else None
        out = []
        for code, s in day.items():
            if "state" not in s:
                continue
            n = nxt.get(code, {}).get("chg") if nxt is not None else None
            out.append([code, s["name"], s["market"], s["state"], s["close"], s["chg"],
                        s["vol"], s["value"], streak.get(code, 0), n])
        out.sort(key=lambda r: (-r[3], -r[8], -r[7]))
        days.append(d)
        rows[str(d)] = out
        count["lu"].append(sum(r[3] for r in out))
        count["touch"].append(sum(1 - r[3] for r in out))
        count["ld"].append(ld)

    tags = {}
    if ind:
        seen = {r[0] for v in rows.values() for r in v}
        for code in seen:
            s = ind["stocks"].get(code)
            if not s or not s[2]:
                continue
            inds, subs = [], []
            for k in s[2]:
                node = ind["nodes"][k]
                if node[0] not in inds:
                    inds.append(node[0])
                label = node[3] or node[2]
                if label and label not in subs:
                    subs.append(label)
            other = lambda x: x.startswith("其他")  # noqa: E731
            tags[code] = [sorted(inds, key=other), sorted(subs, key=other)]
    return {"date": days[-1], "days": days, "count": count, "cols": COLS, "rows": rows, "tags": tags}


def write_limitup(data_dir, out_path):
    payload = build(data_dir, industry_site.build(data_dir))
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    p = write_limitup(root / "data", sys.argv[1] if len(sys.argv) > 1 else root / "_site" / "data" / "limitup.json")
    print(p["date"], "漲停", p["count"]["lu"][-1], "打開", p["count"]["touch"][-1], "跌停", p["count"]["ld"][-1])
