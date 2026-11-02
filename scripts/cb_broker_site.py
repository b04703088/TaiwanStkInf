"""CB 常客分點頁（cb-broker.html）的資料 → data/cb/broker.json

  regulars  研究結果（research/data/cb_regulars.json，由 research/cb_site_static.py 產生）
  stages    各流程階段累積超額報酬（同上）
  只列有詢圈的案件；純競拍不列（Leo 2026-11-02）
  live      進行中 CB 案件：各階段分點買賣超前 15 名（data/cb/brokers.csv，fetch_cb_broker.py 每晚更新），
            標出常客分點（config/cb_regulars.csv）有沒有進場、在哪一段進場，以及整段期間買超／賣超最多的分點
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

STAGES = ["s0", "s1", "s2", "s3", "s4"]


def _read(p):
    p = Path(p)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _names(data_dir):
    return {r["code"]: r["abbr"] or r["name"] for r in _read(Path(data_dir) / "cb" / "companies.csv")}


def _stage_now(c, last):
    """目前走到哪一段"""
    pd = c["done_date"] or c["bb_end"]
    if pd and pd <= last:
        return "已訂價"
    if c["bb_start"] and c["bb_start"] <= last:
        return "詢圈中"
    if c["eff_date"] and c["eff_date"] <= last:
        return "已生效"
    if c["filed_date"] and c["filed_date"] <= last:
        return "審查中"
    return "已決議"


def build_live(data_dir, regulars):
    data_dir = Path(data_dir)
    rows = _read(data_dir / "cb" / "brokers.csv")
    cases = {c["id"]: c for c in _read(data_dir / "cb" / "cases.csv")}
    names = _names(data_dir)
    reg = {(g["broker"], g["side"]): g for g in regulars}
    last = max((r["d2"] for r in rows), default="")

    # 同一檔同時辦詢圈＋競拍（日期相同）合併成一列
    groups = defaultdict(list)
    for i in {r["id"] for r in rows}:
        c = cases.get(i)
        if c:
            groups[(c["code"], c["board_date"] or c["filed_date"] or c["bb_start"])].append(i)

    live = []
    for (code, _), ids in groups.items():
        cs = [cases[i] for i in ids]
        if not any(x["method"] == "詢價圈購" for x in cs):   # 只看有詢圈的案件（純競拍不列）
            continue
        c = sorted(cs, key=lambda x: x["method"] != "詢價圈購")[0]
        wins = {}
        net = defaultdict(lambda: defaultdict(int))   # (broker, side) → stage → net
        for r in rows:
            if r["id"] != c["id"]:
                continue
            wins[r["win"]] = [r["d1"], r["d2"]]
            if r["bid"]:
                net[(r["broker"], r["side"])][r["win"]] = int(r["net"])
        hits = []
        for (b, side), g in reg.items():
            sign = 1 if side == "B" else -1
            st = {w: v for w, v in net.get((b, side), {}).items() if v * sign > 0}
            if st:
                hits.append({"broker": b, "side": side, "tier": g["tier"], "lots": sum(st.values()),
                             "entry": next(w for w in STAGES if w in st), "by": st})
        hits.sort(key=lambda h: (h["tier"] != "常客", STAGES.index(h["entry"])))
        tot = defaultdict(int)
        for (b, side), st in net.items():
            for v in st.values():
                tot[b] += v
        top_b = sorted(((b, v) for b, v in tot.items() if v > 0), key=lambda x: -x[1])[:3]
        top_s = sorted(((b, v) for b, v in tot.items() if v < 0), key=lambda x: x[1])[:3]
        live.append({"code": code, "name": names.get(code) or c["company"][:4],
                              "stage": _stage_now(c, last),
                     "dates": {"board": c["board_date"], "filed": c["filed_date"], "eff": c["eff_date"],
                               "start": c["bb_start"], "price": c["done_date"] or c["bb_end"]},
                     "lead": c["lead"].replace("股份有限公司", "").replace("綜合證券", "").replace("證券", ""),
                     "wins": wins, "hits": hits, "top_b": top_b, "top_s": top_s})
    order = {"詢圈中": 0, "已生效": 1, "審查中": 2, "已決議": 3, "已訂價": 4}
    live.sort(key=lambda x: (-sum(h["tier"] == "常客" for h in x["hits"]), -len(x["hits"]),
                             order.get(x["stage"], 9), x["dates"]["start"] or "9", x["code"]))
    return live, last


def write_cb_broker(data_dir, root, out_path):
    root = Path(root)
    p = root / "research" / "data" / "cb_regulars.json"
    static = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"regulars": [], "stages": []}
    regulars = static["regulars"]
    # 常客清單以 config 為準（研究結果沒有的分點也列出，只是沒有歷史統計）
    cfg = _read(root / "config" / "cb_regulars.csv")
    known = {(g["broker"], g["side"]) for g in regulars}
    regulars += [{"broker": g["broker"], "side": g["side"], "tier": g["tier"], "note": g["note"], "n": 0,
                  "entry": {}, "cases": []} for g in cfg if (g["broker"], g["side"]) not in known]
    live, last = build_live(data_dir, regulars)
    out = {"last": last, "regulars": regulars, "stages": static.get("stages", []),
           "stage_labels": static.get("stage_labels", {}), "sample": static.get("sample", {}), "live": live}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out
