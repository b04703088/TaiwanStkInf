"""data/mops/news/*.csv → 網頁用 data/mops/mops.json（news.html 用）。

  news   最近 NEWS_DAYS 天所有上市櫃重訊（新到舊），含內容摘要
  meets  股東會、法說會：開會日在 PAST_DAYS 天前之後的（含未來），同一場只留最新一次公告；
         法說會另外併入觀測站法說會專區（data/mops/calls.csv，有簡報連結）
  divs   除權息：證交所／櫃買中心除權除息預告表（data/mops/exright.csv）＋除權息重訊，同一檔同一天合併
  cats   分類代碼 → 中文
"""
import csv
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

NEWS_DAYS = 30
PAST_DAYS = 30
NEWS = ["date", "time", "code", "name", "market", "cat", "sub", "subject", "ev_kind", "ev_date", "summary"]
MEETS = ["ev_date", "code", "name", "market", "ev_kind", "ev_note", "date", "subject", "link"]
DIVS = ["ex_date", "code", "name", "market", "kind", "cash", "stock", "pay_date"]
MEET_KINDS = {"常會", "臨時會", "法說會"}
DIV_KINDS = {"除權", "除息", "除權息"}
CATS = [("shm", "股東會"), ("call", "法說會"), ("board", "董事會決議"), ("div", "股利"), ("fin", "財報營收"),
        ("hr", "人事異動"), ("legal", "訴訟調查"), ("attn", "注意處置"), ("buyback", "庫藏股"), ("capital", "增減資籌資"), ("ma", "取得處分併購"),
        ("clarify", "澄清報導"), ("other", "其他")]
FILE_URL = "https://mopsov.twse.com.tw/nas/STR/{}"
REDO = re.compile(r"更正|變更|延期|改期|順延|補充|新增議案|修正")


def read_news(data_dir):
    rows = []
    for f in sorted((Path(data_dir) / "mops" / "news").glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].csv")):
        with f.open(encoding="utf-8") as fp:
            rows += list(csv.DictReader(fp))
    return rows


def _read(p):
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def meetings(rows, since, calls=()):
    """股東會／法說會公告 → 每一場一列。
    股東常會：同一家一年一次，以最新一次公告為準（更正日期、新增議案都會再公告一次）。
    股東臨時會：主旨寫更正／延期等，取代同一家前一次還沒開的臨時會；其餘以日期區分。
    法說會：同一家同一天只留最新一次公告。"""
    ev = sorted((r for r in rows if r.get("ev_kind") in MEET_KINDS and r.get("ev_date")), key=lambda r: (r["date"], r["time"]))
    out = {}
    for r in ev:
        if r["ev_kind"] == "常會":
            k = (r["code"], "常會", r["ev_date"][:4])
        elif r["ev_kind"] == "臨時會":
            if REDO.search(r["subject"]):
                for k0 in [k0 for k0, v in out.items() if k0[:2] == (r["code"], "臨時會") and v["ev_date"] >= r["date"]]:
                    del out[k0]
            k = (r["code"], "臨時會", r["ev_date"])
        else:
            k = (r["code"], r["ev_kind"], r["ev_date"])
        out[k] = r
    for c in calls:  # 法說會專區：補沒發重訊的場次、加簡報連結
        c = dict(c, link=FILE_URL.format(c["file"]) if c.get("file") else c.get("video", ""))
        k = (c["code"], "法說會", c["date"])
        r = out.get(k)
        if r:
            out[k] = dict(r, link=c.get("link") or r.get("link", ""))
        else:
            out[k] = {"ev_date": c["date"], "code": c["code"], "name": c["name"], "market": c.get("market", ""), "ev_kind": "法說會",
                      "ev_note": " ".join(x for x in (c.get("time", ""), c.get("place", "")) if x)[:40],
                      "date": c.get("ann_date", ""), "time": "", "subject": c.get("summary") or "法說會", "link": c.get("link", "")}
    res = [r for r in out.values() if r["ev_date"] >= since]
    res.sort(key=lambda r: (r["ev_date"], r["ev_note"].split(" ")[0] if r["ev_kind"] == "法說會" else "", r["code"]))
    return res


def dividends(rows, exright, since):
    """除權息預告表＋除權息重訊 → 每檔每個除權息交易日一列；預告表為主，缺的金額用重訊補。"""
    out = {}
    for r in sorted((r for r in rows if r.get("ev_kind") in DIV_KINDS and r.get("ev_date")), key=lambda r: (r["date"], r["time"])):
        cash = re.search(r"現金 ([\d.]+)", r.get("ev_note") or "")
        stock = re.search(r"股票 ([\d.]+)", r.get("ev_note") or "")
        pay = re.search(r"發放 (\S+)", r.get("ev_note") or "")
        out[(r["code"], r["ev_date"])] = {"ex_date": r["ev_date"], "code": r["code"], "name": r["name"], "market": r["market"],
                                          "kind": r["ev_kind"], "cash": cash.group(1) if cash else "",
                                          "stock": stock.group(1) if stock else "", "pay_date": pay.group(1) if pay else ""}
    for e in exright:
        k = (e["code"], e["ex_date"])
        old = out.get(k, {})
        out[k] = {**old, **{c: e.get(c) for c in DIVS if e.get(c)}}
        for c in DIVS:
            out[k].setdefault(c, "")
    res = [r for r in out.values() if r["ex_date"] >= since]
    res.sort(key=lambda r: (r["ex_date"], r["code"]))
    return res


def build(rows, today=None, exright=(), calls=()):
    if not rows:
        return None
    gen = max(r["date"] for r in rows)
    today = today or date.fromisoformat(gen)
    since = (today - timedelta(days=NEWS_DAYS)).isoformat()
    news = sorted((r for r in rows if r["date"] > since), key=lambda r: (r["date"], r["time"], r["code"]), reverse=True)
    past = (today - timedelta(days=PAST_DAYS)).isoformat()
    meets = meetings(rows, past, calls)
    divs = dividends(rows, exright, past)
    return {
        "generated": gen,
        "first": min(r["date"] for r in rows),
        "cats": CATS,
        "news": {"cols": NEWS, "rows": [[(r.get(k) if r.get(k) != "-" else None) or None for k in NEWS] for r in news]},
        "meets": {"cols": MEETS, "rows": [[r.get(k) or None for k in MEETS] for r in meets]},
        "divs": {"cols": DIVS, "rows": [[_num(k, r.get(k)) for k in DIVS] for r in divs]},
    }


def _num(k, v):
    if k in ("cash", "stock"):
        try:
            f = float(v)
            return f or None
        except (TypeError, ValueError):
            return None
    return v or None


def write_mops(data_dir, out_path, today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    d = Path(data_dir) / "mops"
    payload = build(read_news(data_dir), today, _read(d / "exright.csv"), _read(d / "calls.csv"))
    if payload is None:
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
