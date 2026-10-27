#!/usr/bin/env python3
"""內部人持股異動：董監事、經理人、10% 大股東每月的買賣（事後申報），以及持股轉讓事前申報。

資料來源（公開資訊觀測站／證交所／櫃買中心，公開免登入）
  1. 股權異動彙總表 IRB110（每月一份，上市 sii／上櫃 otc，約每月 22 日公布上個月）
       https://siis.twse.com.tw/publish/<sii|otc>/<民國年>IRB110_<月>.HTM
     只有每家公司的合計，用來篩出「這個月內部人持股有變動」的公司。
  2. 內部人持股異動事後申報表（觀測站 query6_1，每家公司每個月）
       POST https://mops.twse.com.tw/mops/api/query6_1
     每位內部人的「本月增加／減少」，分成 集中市場（自有股數(集中)）與 其他原因（贈與、信託、繼承、員工認股…）。
     只查第 1 步篩出「內部人持股有增加」的公司（約 350 家，觀測站一家要好幾秒，約 25 分鐘），
     中途停掉（--max-minutes）會存進度，下次接著查。
  3. 持股轉讓事前申報（每天，OpenAPI 只給最新一天，所以要每天抓、累積）
       https://openapi.twse.com.tw/v1/opendata/t187ap12_L
       https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O

輸出
  data/insider/irb110/<YYYYMM>_<sii|otc>.csv   code, company, issued, ds_add, ds_sub, ds_held, ds_pct, mgr_held, major_held
  data/insider/trades/<YYYYMM>.csv             每位內部人當月有變動的持股（只留普通股）
      month, market, code, company, role, name, held_prev, buy_mkt, buy_other, sell_mkt, sell_other, held_now, pledged, note
      buy_mkt / sell_mkt = 集中市場買進／賣出股數（策略主要看這兩欄）；配偶及未成年子女的列，name 為「本人姓名(配偶/子女)」
      dup：夫妻都是內部人時，「甲的配偶」那列就是乙本人的買賣，會重複出現；這種列填上乙的名字，加總時要略過
  data/insider/transfer/<YYYY>.csv             事前申報（預定在市場上賣出或贈與、信託…）
      date, market, code, company, role, name, method, shares, held, after, daily_max, transferee, period

用法：
  python fetch_insider.py                  事前申報（今天）＋ 最近 3 個月還沒抓過的月報
  python fetch_insider.py --month 2026-08  重抓某個月
  python fetch_insider.py --skip-monthly   只抓事前申報
"""
import argparse
import csv
import html
import re
import sys
import time
from datetime import date
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "insider"
IRB_URL = "https://siis.twse.com.tw/publish/{mkt}/{roc}IRB110_{mm}.HTM"
MOPS_API = "https://mops.twse.com.tw/mops/api/"
TRANSFER_URLS = [("sii", "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"),
                 ("otc", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O")]
DELAY = 0.3

IRB_COLS = ["code", "company", "issued", "ds_add", "ds_sub", "ds_held", "ds_pct", "mgr_held", "major_held"]
TRADE_COLS = ["month", "market", "code", "company", "role", "name", "held_prev", "buy_mkt", "buy_other",
              "sell_mkt", "sell_other", "held_now", "pledged", "note", "dup", "pledge_add", "pledge_sub"]
TRADE_INTS = ["held_prev", "buy_mkt", "buy_other", "sell_mkt", "sell_other", "held_now", "pledged", "pledge_add", "pledge_sub"]
TRANSFER_COLS = ["date", "market", "code", "company", "role", "name", "method", "shares", "held", "after",
                 "daily_max", "transferee", "period"]

_TR = re.compile(r"<TR>(.*?)</TR>", re.S | re.I)
_TD = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
_CODE = re.compile(r"^\s*([0-9]{4})(?![0-9])\s*(.*)$")


def _read(p):
    if not Path(p).exists():
        return []
    with Path(p).open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _write(p, cols, rows):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _int(s):
    v = C.num(s)
    return int(v) if v is not None else 0


def ym_add(ym, k):
    y, m = ym
    m += k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return y, m


# ---------------- 1. 股權異動彙總表 ----------------
def parse_irb110(page):
    rows = []
    for tr in _TR.findall(page):
        tds = [html.unescape(re.sub(r"<[^>]+>", "", t)).strip() for t in _TD.findall(tr)]
        if len(tds) != 8:
            continue
        m = _CODE.match(tds[0])
        if not m:
            continue
        rows.append({"code": m.group(1), "company": m.group(2).strip(), "issued": _int(tds[1]),
                     "ds_add": _int(tds[2]), "ds_sub": _int(tds[3]), "ds_held": _int(tds[4]),
                     "ds_pct": C.num(tds[5]), "mgr_held": _int(tds[6]), "major_held": _int(tds[7])})
    return rows


def irb110(y, m, mkt):
    """回傳 [rows] 或 None（還沒公布）。已抓過的直接讀檔。"""
    p = OUT / "irb110" / f"{y}{m:02d}_{mkt}.csv"
    if p.exists():
        return [{**r, **{k: _int(r[k]) for k in IRB_COLS[2:] if k != "ds_pct"}} for r in _read(p)]
    url = IRB_URL.format(mkt=mkt, roc=y - 1911, mm=f"{m:02d}")
    try:
        raw = C.http(url, raw=True, retries=2)
    except C.AdapterError as e:
        if "404" in str(e):
            return None
        raise
    rows = parse_irb110(raw.decode("cp950", errors="replace"))
    if not rows:
        return None
    _write(p, IRB_COLS, rows)
    return rows


def candidates(cur, prev):
    """這個月董監有「增加」、或經理人／大股東持股比上個月多的公司（約 350 家）。
    只賣不買的公司不查：賣出另有每天的事前申報，而且觀測站一家要好幾秒，全部查一個月要近一小時。"""
    before = {r["code"]: r for r in prev or []}
    out = []
    for r in cur:
        p = before.get(r["code"])
        if r["ds_add"] or (p and (r["mgr_held"] > p["mgr_held"] or r["major_held"] > p["major_held"])):
            out.append(r)
    return out


# ---------------- 2. 事後申報表 ----------------
# query6_1 的 24 欄（titles 有完整名稱）
I_ROLE, I_NAME, I_KIND, I_PREV = 0, 1, 2, 4
I_ADD_MKT, I_ADD_OTHER, I_SUB_MKT, I_SUB_OTHER, I_NOW, I_PLEDGE, I_NOTE = 8, 9, 13, 14, 18, 21, 23
I_PLEDGE_ADD, I_PLEDGE_SUB = 12, 17   # 本月增加／減少 底下的「設定質權股數」「解除質權股數」


def mops(api, body):
    d = C.http(MOPS_API + api, body=body, headers={"Referer": "https://mops.twse.com.tw/mops/"}, retries=3)
    if not isinstance(d, dict) or d.get("code") != 200:
        raise C.AdapterError(f"{api} {body}: {str(d)[:160]}")
    return d.get("result") or {}


def parse_query6(res, y, m, market, code, company):
    """事後申報表 → 有變動的內部人。同一人兼多個身分只留一列（身分用「、」合併）。"""
    raw_titles = res.get("titles") or []
    titles = [t.get("main", "") for t in raw_titles]
    subs = lambda i: "".join(s.get("main", "") for s in raw_titles[i].get("sub") or [])  # noqa: E731
    if titles and (len(titles) < 14 or "本月增加" not in titles[8] or "本月實際自有持有股數" not in titles[10]
                   or "設定質權" not in subs(8) or "解除質權" not in subs(9)):
        raise C.AdapterError(f"query6_1 {code} 欄位變了：{titles}")
    month = f"{y}-{m:02d}"
    out, seen, principal = [], {}, ""
    for row in res.get("data") or []:
        if len(row) < 24:
            continue
        role, name = (row[I_ROLE] or "").strip(), (row[I_NAME] or "").strip()
        spouse = "配偶" in role
        if not spouse:
            principal = name
        if (row[I_KIND] or "").strip() != "普通股":
            continue
        who = f"{principal}(配偶/子女)" if spouse else name
        if not who:
            continue
        vals = {"held_prev": _int(row[I_PREV]), "buy_mkt": _int(row[I_ADD_MKT]), "buy_other": _int(row[I_ADD_OTHER]),
                "sell_mkt": _int(row[I_SUB_MKT]), "sell_other": _int(row[I_SUB_OTHER]),
                "held_now": _int(row[I_NOW]), "pledged": _int(row[I_PLEDGE]),
                "pledge_add": _int(row[I_PLEDGE_ADD]), "pledge_sub": _int(row[I_PLEDGE_SUB])}
        if not any(vals[k] for k in ("buy_mkt", "buy_other", "sell_mkt", "sell_other", "pledge_add", "pledge_sub")):
            continue
        short_role = re.sub(r"之配偶及未成年子女$", "", role).replace("本人", "")
        # 同一人（或同一家投資公司）兼多個身分、或「利用他人名義持有」另列一行時，同一筆買賣會重複出現，只記一次
        key = (re.sub(r"\s+", " ", who).upper(), vals["buy_mkt"], vals["buy_other"], vals["sell_mkt"], vals["sell_other"],
               vals["pledge_add"], vals["pledge_sub"])
        if key in seen:
            r = seen[key]
            if short_role not in r["role"].split("、"):
                r["role"] += "、" + short_role
            continue
        r = {"month": month, "market": market, "code": code, "company": company, "role": short_role,
             "name": who, **vals, "note": (row[I_NOTE] or "").strip()}
        seen[key] = r
        out.append(r)
    mark_dups(out)
    return out


def _dup_key(r):
    return (r["code"], r["buy_mkt"], r["buy_other"], r["sell_mkt"], r["sell_other"],
            r.get("pledge_add", 0), r.get("pledge_sub", 0))


def mark_dups(rows):
    """配偶列的買賣和同公司另一位內部人本人完全相同 → 視為同一筆（夫妻都是內部人），dup 填那個人。"""
    own = {}
    for r in rows:
        if "(配偶/子女)" not in r["name"]:
            own.setdefault(_dup_key(r), r["name"])
    for r in rows:
        r.setdefault("dup", "")
        if "(配偶/子女)" in r["name"]:
            who = own.get(_dup_key(r))
            if who and who != r["name"].replace("(配偶/子女)", ""):
                r["dup"] = who
    return rows


def fetch_month(y, m, force=False, deadline=None):
    """回傳 True = 這個月完成；False = 還沒公布或還沒查完（進度已存）。"""
    out_p = OUT / "trades" / f"{y}{m:02d}.csv"
    part_p, done_p = out_p.with_suffix(".part.csv"), out_p.with_suffix(".done.txt")
    if out_p.exists() and not force:
        return True
    py, pm = ym_add((y, m), -1)
    cand = []
    for mkt in ("sii", "otc"):
        cur = irb110(y, m, mkt)
        if cur is None:
            print(f"{y}-{m:02d} {mkt} 股權異動彙總表還沒公布", flush=True)
            return False
        prev = irb110(py, pm, mkt)
        cand += [(mkt, r["code"], r["company"]) for r in candidates(cur, prev)]
    rows = [{**r, **{k: _int(r.get(k)) for k in TRADE_INTS}} for r in _read(part_p)]
    done = set(done_p.read_text(encoding="utf-8").split()) if done_p.exists() else set()
    todo = [c for c in cand if c[1] not in done]
    print(f"{y}-{m:02d}：內部人持股增加的公司 {len(cand)} 家（已查 {len(done)}），逐家查事後申報表", flush=True)
    failed = []

    def save_part():
        _write(part_p, TRADE_COLS, rows)
        done_p.write_text("\n".join(sorted(done)), encoding="utf-8")

    for i, (mkt, code, company) in enumerate(todo, 1):
        if deadline and time.time() > deadline:
            save_part()
            print(f"{y}-{m:02d}：時間到，已查 {len(done)}/{len(cand)} 家，進度已存，下次接著查", flush=True)
            return False
        try:
            res = mops("query6_1", {"companyId": code, "dataType": "2", "year": str(y - 1911),
                                    "month": f"{m:02d}", "subsidiaryCompanyId": ""})
            rows += parse_query6(res, y, m, mkt, code, res.get("companyAbbreviation") or company)
            done.add(code)
        except C.AdapterError as e:
            failed.append(code)
            print(f"  {code} 失敗：{e}", file=sys.stderr)
        if i % 50 == 0:
            save_part()
            print(f"  {i}/{len(todo)}", flush=True)
        time.sleep(DELAY)
    if len(failed) > max(5, 0.05 * len(cand)):
        save_part()
        print(f"{y}-{m:02d}：失敗 {len(failed)} 家，太多了，先存進度（下次重查失敗的）", flush=True)
        return False
    rows.sort(key=lambda r: (r["code"], -(r["buy_mkt"] - r["sell_mkt"])))
    _write(out_p, TRADE_COLS, rows)
    part_p.unlink(missing_ok=True)
    done_p.unlink(missing_ok=True)
    n_buy = sum(1 for r in rows if r["buy_mkt"] > r["sell_mkt"])
    print(f"{y}-{m:02d}：{len(rows)} 筆異動（集中市場淨買進 {n_buy} 筆），失敗 {len(failed)} 家 -> {out_p}")
    return True


# ---------------- 3. 事前申報 ----------------
def _g(r, *keys):
    for k in keys:
        if k in r and r[k] not in (None, ""):
            return str(r[k]).strip()
    return ""


def norm_transfer(r, market):
    return {"date": C.iso(_g(r, "出表日期", "Date")), "market": market,
            "code": _g(r, "公司代號", "SecuritiesCompanyCode"), "company": _g(r, "公司名稱", "CompanyName"),
            "role": _g(r, "申報人身分", "申請人身分"), "name": _g(r, "姓名"),
            "method": _g(r, "預定轉讓方式及股數-轉讓方式"),
            "shares": _int(_g(r, "預定轉讓總股數-自有持股", "預定轉讓方式及股數-轉讓股數")),
            "held": _int(_g(r, "目前持有股數-自有持股")), "after": _int(_g(r, "預定轉讓後持股-自有持股")),
            "daily_max": _int(_g(r, "每日於盤中交易最大得轉讓股數")), "transferee": _g(r, "受讓人"),
            "period": _g(r, "有效轉讓期間")}


def fetch_transfers():
    new = []
    for market, url in TRANSFER_URLS:
        try:
            data = C.http(url, retries=3)
        except C.AdapterError as e:
            print(f"事前申報 {market} 失敗：{e}", file=sys.stderr)
            continue
        new += [norm_transfer(r, market) for r in data or [] if isinstance(r, dict)]
    by_year = {}
    for r in new:
        if r["date"] and r["code"]:
            by_year.setdefault(r["date"][:4], []).append(r)
    added = 0
    for y, rows in by_year.items():
        p = OUT / "transfer" / f"{y}.csv"
        old = _read(p)
        key = lambda r: (r["date"], r["code"], r["name"], r["method"], str(r["shares"]))  # noqa: E731
        have = {key(r) for r in old}
        fresh = [r for r in rows if key(r) not in have]
        if fresh:
            allr = old + fresh
            allr.sort(key=lambda r: (r["date"], r["code"], r["name"]))
            _write(p, TRANSFER_COLS, allr)
            added += len(fresh)
    print(f"事前申報：取得 {len(new)} 筆，新增 {added} 筆", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", help="只抓這個月（YYYY-MM），已抓過也重抓")
    ap.add_argument("--months", type=int, default=3, help="檢查最近幾個月（預設 3）")
    ap.add_argument("--skip-monthly", action="store_true")
    ap.add_argument("--skip-transfer", action="store_true")
    ap.add_argument("--max-minutes", type=float, default=40, help="月報最多查幾分鐘，時間到存進度（預設 40）")
    a = ap.parse_args(argv)
    if not a.skip_transfer:
        fetch_transfers()
    if a.skip_monthly:
        return 0
    deadline = time.time() + a.max_minutes * 60
    if a.month:
        y, m = (int(x) for x in a.month.split("-"))
        fetch_month(y, m, force=True, deadline=deadline)
        return 0
    today = date.today()
    for k in range(1, a.months + 1):   # 由新到舊：最新的月份最有用
        y, m = ym_add((today.year, today.month), -k)
        if not fetch_month(y, m, deadline=deadline) and time.time() > deadline:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
