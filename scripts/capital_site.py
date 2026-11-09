"""現增／GDR 追蹤頁（site/capital.html）→ data/capital.json

從公開資訊觀測站重訊（data/mops/news，fetch_mops_news.py）挑出公司「自己」辦現金增資或參與發行海外存託憑證（GDR／ADR）的公告，
依主旨判斷走到哪一步：
  board   董事會決議辦理
  record  訂定認股基準日（價格還沒定）
  priced  訂價（發行條件、補充公告發行價格、承銷價格）
  paid    收足股款／增資基準日（完成）
  cancel  撤銷
不算：代子公司公告、認購子公司或別家公司的現增、私募、初次上市櫃前現增、員工認購、資金運用計畫變更。
同一家公司取最近一次董事會決議以後的公告當一個案子（資料起點前就決議的，從看得到的第一則開始）。

欄位
  新股股數    從摘要「規模」抓（擬發行／上限／暫定都算，GDR 常只寫「暫訂」）；抓不到留空
  占股本      新股股數 ÷ 集保總股數（近似發行股數）
  相當幾天量  新股股數 ÷ 近 20 日平均成交股數
  決議後超額  董事會決議（或第一則公告）後第一個交易日起，股價累計漲跌 − 同市場普通股平均累計漲跌
"""
import csv
import json
import re
from pathlib import Path

STOCK = re.compile(r"^[1-9]\d{3}$")
EXCL = re.compile(r"子公司|私募|初次上(市|櫃)|上櫃前|上市前|員工認購|認購.{0,20}現金增資|參與.{0,20}現金增資|現金增資.{0,6}(子|孫)公司|資金運用計畫|"
                  r"運用計畫|代.{0,20}公告|公告.{0,4}代|改列|掛牌前|臺灣存託憑證|台灣存託憑證|股利|減資|公司債|放棄認購|催繳(?!期間屆滿)|代收|存儲價款|延長")
CAP = re.compile(r"現金增資|存託憑證|GDR|ADR|承銷價格")
STAGES = [("cancel", re.compile(r"撤銷|撤回|終止")),
          ("paid", re.compile(r"收足股款|增資基準日|催繳期間屆滿|股票發放|掛牌")),
          ("priced", re.compile(r"發行條件|發行價格|承銷價格|完成訂價|訂價")),
          ("record", re.compile(r"認股基準日")),
          ("board", re.compile(r"董事會.{0,6}決議|決議.{0,10}(現金增資|存託憑證)"))]
STAGE_N = {"board": "董事會決議", "record": "定認股基準日", "priced": "已訂價", "paid": "已收足股款", "cancel": "撤銷"}


def _f(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _read(p):
    with open(p, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def stage_of(r):
    s = re.sub(r"\s+", "", r["subject"])
    if r.get("sub") or EXCL.search(s) or not CAP.search(s):
        return None
    for k, rx in STAGES:
        if rx.search(s):
            if k == "record" and re.search(r"價格[：:][^；]*?\d+(\.\d+)?\s*元", r.get("summary") or "") and "補充" in s:
                return "priced"
            return k
    return None


def parse_shares(summary):
    m = re.search(r"規模[：:]([^；]*)", summary or "")
    t = m.group(1) if m else ""
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(仟|千|萬)?股", t)
    if not m:
        return None
    n = _f(m.group(1))
    if n is None:
        return None
    return n * {"仟": 1e3, "千": 1e3, "萬": 1e4}.get(m.group(2), 1)


def parse_price(summary):
    m = re.search(r"價格[：:]([^；]*)", summary or "")
    t = m.group(1) if m else ""
    if re.search(r"實際發行價格(將|俟|於|僅)|參酌|授權|呈奉|俟", t) and not re.search(r"\d+(\.\d+)?\s*元", t):
        return None
    m = re.search(r"(?:新(?:台|臺)幣|NT\$)?\s*(\d+(?:\.\d+)?)\s*元", t)
    return _f(m.group(1)) if m else None


def price_days(data_dir):
    files = [f for f in sorted(Path(data_dir).glob("[0-9][0-9][0-9][0-9]/[0-9]*.csv"), key=lambda p: p.name) if len(f.stem) == 8]
    return files


def build(data_dir):
    data_dir = Path(data_dir)
    rows = []
    for f in sorted((data_dir / "mops" / "news").glob("[0-9]*-[0-9]*.csv")):
        rows += _read(f)
    if not rows:
        return None
    first = min(r["date"] for r in rows)
    ev = []
    for r in rows:
        st = stage_of(r)
        if st and STOCK.match(r["code"]):
            ev.append((r["date"], r["time"], r["code"], r["name"], r["market"], st, re.sub(r"\s+", "", r["subject"]), r.get("summary") or ""))
    ev.sort()
    # 依公司切案子：最近一次 board 以後
    by = {}
    for e in ev:
        by.setdefault(e[2], []).append(e)
    files = price_days(data_dir)
    since = first.replace("-", "")
    files = [f for f in files if f.stem >= since]
    days = [f"{f.stem[:4]}-{f.stem[4:6]}-{f.stem[6:]}" for f in files]
    ret, avg, px, vol20 = {}, {}, {}, {}
    for d, f in zip(days, files):
        rr, agg = {}, {}
        for r in _read(f):
            c, ch = _f(r["close"]), _f(r["change"])
            if not c or ch is None or c - ch <= 0:
                continue
            v = ch / (c - ch)
            rr[r["code"]] = v
            px[r["code"]] = (c, r["name"], r["market"])
            if STOCK.match(r["code"]):
                a = agg.setdefault(r["market"], [0.0, 0])
                a[0] += v
                a[1] += 1
        ret[d], avg[d] = rr, {m: a[0] / a[1] for m, a in agg.items()}
    for f in files[-20:]:
        for r in _read(f):
            v = _f(r["volume"])
            if v:
                vol20[r["code"]] = vol20.get(r["code"], 0) + v / 20
    tdcc = sorted((data_dir / "tdcc").glob("*.csv"))
    shares = {r["code"]: _f(r["shares"]) for r in _read(tdcc[-1])} if tdcc else {}

    def cum(code, d0, time0="00:00"):
        """d0 公告後（13:30 後算隔天）起的累計漲跌與超額（%）。"""
        start = d0 if time0 < "13:30" else d0 + "~"
        r_, x_ = 1.0, 1.0
        mk = None
        for d in days:
            if d < start or code not in ret[d]:
                continue
            mk = mk or px.get(code, (0, 0, "TWSE"))[2]
            r_ *= 1 + ret[d][code]
            x_ *= 1 + avg[d].get(mk, 0)
        return round((r_ - 1) * 100, 1), round((r_ - x_) * 100, 1)

    cases = []
    for code, es in by.items():
        bi = max((i for i, e in enumerate(es) if e[5] == "board"), default=0)
        es = es[bi:]
        stg = es[-1][5]
        order = ["board", "record", "priced", "paid", "cancel"]
        stg = max((e[5] for e in es), key=order.index)
        board = next((e for e in es if e[5] == "board"), None)
        rec = next((e for e in es if e[5] == "record"), None)
        pr = next((e for e in reversed(es) if e[5] == "priced"), None)
        paid = next((e for e in es if e[5] == "paid"), None)
        kind = "GDR" if any(re.search(r"存託憑證|GDR|ADR", e[6]) for e in es) else "現增"
        sh = next((x for x in (parse_shares(e[7]) for e in reversed(es)) if x), None)
        price = next((x for x in (parse_price(e[7]) for e in reversed(es) if e[5] in ("priced", "record", "paid")) if x), None)
        cl, name, mk = px.get(code, (None, es[-1][3], None))
        s0 = shares.get(code)
        base = board or es[0]
        r_all, x_all = cum(code, base[0], base[1])
        pr_r = cum(code, pr[0], pr[1]) if pr else (None, None)
        cases.append({
            "code": code, "name": name, "kind": kind, "stage": stg, "board": board[0] if board else None,
            "first": es[0][0], "record": rec[0] if rec else None, "priced": pr[0] if pr else None, "paid": paid[0] if paid else None,
            "price": price, "shares": round(sh / 1000) if sh else None,
            "dil": round(sh / s0 * 100, 2) if sh and s0 else None,
            "amt": round(sh * cl / 1e8, 1) if sh and cl else None,
            "days": round(sh / vol20[code], 1) if sh and vol20.get(code) else None,
            "close": cl, "vs_price": round((cl / price - 1) * 100, 1) if cl and price else None,
            "r": r_all, "x": x_all, "pr_r": pr_r[0], "pr_x": pr_r[1],
            "last": es[-1][0], "last_subj": es[-1][6][:80], "n": len(es),
        })
    cases.sort(key=lambda c: c["last"], reverse=True)
    return {"date": days[-1] if days else None, "first": first, "stages": STAGE_N, "cases": cases}


def write(data_dir, out_path):
    j = build(data_dir)
    if j is None:
        return
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    j = build(Path(__file__).resolve().parent.parent / "data")
    from collections import Counter
    print(j["date"], j["first"], len(j["cases"]), Counter((c["kind"], c["stage"]) for c in j["cases"]))
    for c in j["cases"][:40]:
        print(c["code"], c["name"], c["kind"], c["stage"], c["board"], c["priced"], c["price"], c["shares"], c["dil"], c["days"], c["x"], c["vs_price"], "|", c["last_subj"][:40])
