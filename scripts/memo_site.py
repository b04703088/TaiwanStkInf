"""法說會 memo 頁（site/memo.html）→ data/memo.json

memo 由每晚的「潮汐法說 memo」排程（Claude）讀 data/conf/text、data/conf/img 寫成 data/conf/memo/<key>.md，
開頭是簡單的 front matter：
  ---
  code: 2454
  name: 聯發科
  date: 2026-10-30
  time: 14:00
  tone: 偏樂觀            樂觀／偏樂觀／中性／偏保守／保守
  headline: 一句話重點
  ---
這裡補上法說後的股價反應（同 mops_site：13:30 以後開的從隔天算；超額＝減同市場普通股平均），
並依語氣統計平均超額，累積幾季後可以看語氣有沒有用。
"""
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mops_site  # noqa: E402

TONES = ["樂觀", "偏樂觀", "中性", "偏保守", "保守"]


def _read(p):
    if not Path(p).exists():
        return []
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def parse(text):
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for ln in text[3:end].strip().splitlines():
                if ":" in ln:
                    k, v = ln.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = text[end + 4:].lstrip("\n")
    return meta, body.strip()


def build(data_dir):
    data_dir = Path(data_dir)
    cdir = data_dir / "conf"
    idx = {r["key"]: r for r in _read(cdir / "index.csv")}
    memos = []
    for p in sorted((cdir / "memo").glob("*.md")):
        meta, body = parse(p.read_text(encoding="utf-8"))
        ix = idx.get(p.stem, {})
        code = meta.get("code") or ix.get("code")
        d = meta.get("date") or ix.get("date")
        if not code or not d:
            continue
        memos.append({"key": p.stem, "code": code, "name": meta.get("name") or ix.get("name") or "",
                      "market": ix.get("market") or ("otc" if meta.get("market") == "otc" else "sii"),
                      "date": d, "time": meta.get("time") or ix.get("time") or "",
                      "place": ix.get("place") or "", "tone": meta.get("tone") or "", "headline": meta.get("headline") or "",
                      "liq": float(ix["liq"]) if ix.get("liq") else None, "body": body})
    if not memos and not idx:
        return None
    since = (min([m["date"] for m in memos] + [date.today().isoformat()]))
    rets = mops_site.daily_returns(data_dir, (date.fromisoformat(since) - timedelta(days=3)).isoformat())
    mops_site.add_reaction(memos, rets)
    memos.sort(key=lambda m: (m["date"], m["time"], m["code"]), reverse=True)
    have = {m["key"] for m in memos}
    pending = [{"key": k, "code": r["code"], "name": r["name"], "date": r["date"], "liq": float(r["liq"] or 0), "status": r["status"]}
               for k, r in idx.items() if k not in have and r["status"] != "dup"]
    pending.sort(key=lambda r: (r["date"], r["liq"]), reverse=True)
    stats = []
    for t in TONES:
        g = [m for m in memos if m["tone"] == t]
        e1 = [m["ex1"] for m in g if m.get("ex1") is not None]
        e5 = [m["ex5"] for m in g if m.get("ex5") is not None]
        stats.append({"tone": t, "n": len(g),
                      "ex1": round(sum(e1) / len(e1), 2) if e1 else None, "win1": round(sum(1 for x in e1 if x > 0) / len(e1) * 100) if e1 else None,
                      "ex5": round(sum(e5) / len(e5), 2) if e5 else None, "win5": round(sum(1 for x in e5 if x > 0) / len(e5) * 100) if e5 else None})
    return {"px_date": max(rets) if rets else None, "tones": TONES, "stats": stats,
            "memos": memos, "pending": pending[:80]}


def write(data_dir, out_path):
    j = build(data_dir)
    if j is None:
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    j = build(Path(__file__).resolve().parent.parent / "data")
    print(j and (j["px_date"], len(j["memos"]), len(j["pending"]), j["stats"]))
    for m in (j or {}).get("memos", [])[:5]:
        print(m["date"], m["code"], m["name"], m["tone"], m.get("ex1"), m.get("ex5"), m["headline"])
