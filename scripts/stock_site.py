"""個股綜合查詢：把各頁已產生的 JSON 依股票代號拆開 → data/stock/s/<代號>.json（stock.html 用）

不另外抓資料，讀 build_site.py 剛寫好的 _site/data/*（重訊、處置注意、內部人、庫藏股、CB、ETF 換股、
主動 ETF 加減碼、指數審核、外資報告、重點分點、地方主力、除權息），挑出跟這檔股票有關的動作。

  {code, name, gen, ev: [[日期, 類別, 標題, 說明, 連結], ...]}   由新到舊；日期在今天之後的是「即將發生」
類別：news 重訊、meet 股東會／法說會、div 除權息、alert 處置注意、insider 內部人、treasury 庫藏股、
      cb 可轉債、etf ETF／指數、analyst 外資報告、broker 分點
價格、法人、融資券、營收這些每天都有的數字由網頁直接讀 kline / chips / margin / fin 的個股檔。
"""
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

BACK_DAYS = 120          # 往回收幾天的動作
WATCH_MIN_AMT = 5000     # 重點分點單日買賣超至少幾仟元才列（500 萬）
ACTIVE_MIN_LOTS = 50     # 主動 ETF 單次加減碼至少幾張才列
LOCAL_TOP = 3            # 地方主力：只列該分點當天前幾大買超


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _objs(block):
    if not block:
        return []
    cols = block["cols"]
    return [dict(zip(cols, r)) for r in block["rows"]]


def _lots(sh):
    return f"{round(sh / 1000):,}" if sh is not None else "–"


def _num(x, nd=2):
    if x is None:
        return "–"
    s = f"{x:,.{nd}f}".rstrip("0").rstrip(".")
    return s


def _wan(k):  # 仟元 → 「x 億」或「x 萬」
    if k is None:
        return "–"
    return f"{k / 100000:,.2f} 億" if abs(k) >= 100000 else f"{round(k / 10):,} 萬"


def _month_end(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def collect(data: Path, today: date):
    since = (today - timedelta(days=BACK_DAYS)).isoformat()
    ev = defaultdict(list)
    names = {}

    def add(code, d, kind, title, detail="", href=""):
        if code and d and d >= since:
            ev[code].append([d, kind, title, detail or "", href])

    # 重大訊息、股東會／法說會、除權息預告
    m = _load(data / "mops" / "mops.json")
    if m:
        cat = dict(m["cats"])
        for r in _objs(m["news"]):
            names.setdefault(r["code"], r["name"])
            add(r["code"], r["date"], "news", r["subject"], (cat.get(r["cat"]) or "") + ("｜" + r["summary"] if r["summary"] else ""),
                "news.html#s=" + r["code"])
        for r in _objs(m["meets"]):
            add(r["code"], r["ev_date"], "meet", r["ev_kind"] + (f"（{r['ev_note']}）" if r["ev_note"] else ""), r["subject"],
                r["link"] or "news.html#s=" + r["code"])
        for r in _objs(m["divs"]):
            parts = [f"現金 {_num(r['cash'], 4)} 元" if r["cash"] else "", f"股票 {_num(r['stock'], 4)} 元" if r["stock"] else ""]
            add(r["code"], r["ex_date"], "div", r["kind"] + "交易日", "、".join(p for p in parts if p) +
                (f"；發放日 {r['pay_date']}" if r["pay_date"] else ""), "news.html#s=" + r["code"])
    seen_div = {(c, e[0]) for c, es in ev.items() for e in es if e[1] == "div"}
    # 過去的除權息：補上殖利率與填息天數
    dv = _load(data / "screen" / "div.json")
    if dv:
        for r in _objs(dv):
            d = str(r["date"])
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            fill = f"；{r['fill_days']} 天填息" if r["fill_days"] is not None else "；尚未填息"
            det = f"現金 {_num(r['cash'], 4)} 元，殖利率 {_num(r['yield'])}%" + fill if r["cash"] else fill[1:]
            if (r["code"], d) in seen_div:
                for e in ev[r["code"]]:
                    if e[1] == "div" and e[0] == d:
                        e[3] = det
            else:
                add(r["code"], d, "div", r["kind"] + "交易日", det, "screen.html#div")

    # 處置、注意股
    a = _load(data / "alert" / "alert.json")
    if a:
        names.update({k: v for k, v in a["names"].items() if k not in names})
        for r in _objs(a["disp"]):
            href = "alert.html#s=" + r["code"]
            add(r["code"], r["ann_date"], "alert", f"公告處置（{r['measure']}）",
                f"處置期間 {r['start']}～{r['end']}，{r['reason']}" + (f"，每 {r['interval']} 分鐘撮合一次" if r["interval"] else ""), href)
            if r["exit"]:
                add(r["code"], r["exit"], "alert", "出關（處置結束後第一個交易日）", f"處置期間 {r['start']}～{r['end']}", href)
        for r in _objs(a["att"]):
            add(r["code"], r["date"], "alert", f"注意股（第 {r['clauses']} 款）", r["info"], "alert.html#s=" + r["code"])
        near = a.get("near") or {}
        for r in _objs(near):
            add(r["code"], near.get("date"), "alert", "可能被處置", r["situation"], "alert.html#s=" + r["code"])

    # 內部人：事前申報、每月持股異動、董監質押
    ins = _load(data / "insider" / "insider.json")
    if ins:
        for r in _objs(ins["transfer"]):
            names.setdefault(r["code"], r["company"])
            add(r["code"], r["date"], "insider", f"{r['role']}{r['name']} 申報轉讓 {_lots(r['shares'])} 張",
                f"{r['method']}，轉讓期間 {r['period'] or '–'}" + (f"，受讓人 {r['transferee']}" if r["transferee"] else ""),
                "insider.html#s=" + r["code"])
        agg = defaultdict(lambda: {"bm": 0, "sm": 0, "bo": 0, "so": 0, "pa": 0, "ps": 0, "who": defaultdict(int)})
        for r in _objs(ins["trades"]):
            if r["dup"]:
                continue
            g = agg[(r["code"], r["month"])]
            g["bm"] += r["buy_mkt"] or 0
            g["sm"] += r["sell_mkt"] or 0
            g["bo"] += r["buy_other"] or 0
            g["so"] += r["sell_other"] or 0
            g["pa"] += r["pledge_add"] or 0
            g["ps"] += r["pledge_sub"] or 0
            g["who"][r["name"].split("(")[0]] += (r["buy_mkt"] or 0) - (r["sell_mkt"] or 0)
        for (code, mon), g in agg.items():
            bits = []
            if g["bm"] or g["sm"]:
                bits.append(f"集中市場買 {_lots(g['bm'])} 張、賣 {_lots(g['sm'])} 張")
            if g["bo"] or g["so"]:
                bits.append(f"其他（贈與、信託等）增 {_lots(g['bo'])} 張、減 {_lots(g['so'])} 張")
            if g["pa"] or g["ps"]:
                bits.append(f"設質 {_lots(g['pa'])} 張、解質 {_lots(g['ps'])} 張")
            if not bits:
                continue
            top = sorted(g["who"].items(), key=lambda x: -abs(x[1]))[:3]
            who = "、".join(n for n, v in top if v)
            add(code, _month_end(mon), "insider", f"{int(mon[5:])} 月內部人持股異動（每月申報）",
                "；".join(bits) + (f"。主要：{who}" if who else ""), "insider.html#s=" + code)
        for r in _objs(ins["pledge"]):
            if r["ds_ppct"] is not None and (r["ds_padd"] or r["ds_psub"]):
                add(r["code"], _month_end(r["month"]), "insider", f"{int(r['month'][5:])} 月董監質押比 {_num(r['ds_ppct'])}%",
                    f"本月設質 {_lots(r['ds_padd'])} 張、解質 {_lots(r['ds_psub'])} 張，累計質押 {_lots(r['ds_pledged'])} 張",
                    "insider.html#s=" + r["code"])

    # 庫藏股
    t = _load(data / "treasury.json")
    if t:
        purpose = {"1": "轉讓員工", "2": "股權轉換", "3": "維護股東權益"}
        for r in _objs(t):
            names.setdefault(r["code"], r["name"])
            href = "treasury.html#s=" + r["code"]
            why = "、".join(purpose.get(x, x) for x in (r["purpose"] or "").split(",") if x)
            done = f"；已完成，買了 {_lots(r['bought_shares'])} 張，執行率 {_num(r['exec_pct'])}%，均價 {_num(r['avg_price'])} 元" \
                if r["done"] == "Y" else ""
            add(r["code"], r["board_date"], "treasury", f"董事會決議買回庫藏股 {_lots(r['plan_shares'])} 張",
                f"價格 {_num(r['price_lo'])}～{_num(r['price_hi'])} 元，期間 {r['start']}～{r['end']}" + (f"，目的：{why}" if why else "") + done, href)
            if r["done"] == "Y":
                if r["end"] and r["end"] <= today.isoformat():  # 提前買完的完成日不明，重訊那筆會列出
                    add(r["code"], r["end"], "treasury", f"庫藏股買回期間結束：買了 {_lots(r['bought_shares'])} 張",
                        f"執行率 {_num(r['exec_pct'])}%，均價 {_num(r['avg_price'])} 元" + (f"；{r['reason']}" if r["reason"] else ""), href)
            elif r["end"]:
                prog = f"截至 {r['prog_date']} 已買 {_lots(r['prog_shares'])} 張" if r["prog_date"] else "執行中"
                add(r["code"], r["end"], "treasury", "庫藏股買回期間截止", prog, href)

    # 可轉債
    c = _load(data / "cb" / "cb.json")
    if c:
        for r in _objs(c):
            code, nm = r["code"], r["short"] or r["company"]
            if not code:
                continue
            series = f"（{nm}）" if nm else ""
            auc = (r["method"] or "").startswith("競")
            add(code, r["board_date"], "cb", "董事會決議發行可轉債", f"{r['type'] or ''} 約 {_wan((r['board_amount'] or 0) / 1000)}", "cb.html")
            if r["eff_date"]:
                add(code, r["eff_date"], "cb", "可轉債申報生效", r["sfb_status"] or "", "cb.html")
            if r["bb_start"]:
                add(code, r["bb_start"], "cb", ("可轉債競拍開始" if auc else "可轉債詢價圈購開始") + series,
                    f"{r['bb_start']}～{r['bb_end']}，主辦 {r['lead'] or '–'}" +
                    (f"，溢價率 {_num(r['premium_lo'])}～{_num(r['premium_hi'])}%" if r["premium_lo"] else ""), "cb-bb.html")
            if r["list_date"] or r["list_expected"]:
                add(code, r["list_date"] or r["list_expected"], "cb", "可轉債掛牌" + series,
                    f"轉換價 {_num(r['conv_price'])} 元" if r["conv_price"] else "", "cb-listed.html")

    # 被動 ETF 換股（實際偵測到的納入／剔除）
    rb = _load(data / "etf" / "rebalance.json")
    if rb:
        for e in rb["etfs"]:
            for x in e["events"]:
                for code in x[9]:
                    add(code, x[0], "etf", f"{e['name']}（{e['etf']}）納入", f"換股期間 {x[0]}～{x[1]}", f"etf.html?stock={code}")
                for code in x[10]:
                    add(code, x[0], "etf", f"{e['name']}（{e['etf']}）剔除", f"換股期間 {x[0]}～{x[1]}", f"etf.html?stock={code}")
    # 指數審核結果
    cal = _load(data / "calendar.json")
    if cal:
        for r in cal["reviews"]:
            if not r[2]:
                continue
            eff = f"，生效日 {r[3]}" if r[3] else ""
            etfs = f"，追蹤 ETF：{'、'.join(r[4][:4])}" if r[4] else ""
            for code, _n in r[6]:
                add(code, r[2], "etf", f"{r[0]} 審核納入", f"公告{eff}{etfs}", "calendar.html?q=" + code)
            for code, _n in r[7]:
                add(code, r[2], "etf", f"{r[0]} 審核刪除", f"公告{eff}{etfs}", "calendar.html?q=" + code)
    # 主動 ETF 加減碼
    ac = _load(data / "etf" / "active.json")
    if ac:
        etfs = ac["etfs"]
        byday = defaultdict(list)
        for r in _objs(ac):
            v = r["da"] if r["da"] is not None else r["d"]
            if v is not None and abs(v) >= ACTIVE_MIN_LOTS * 1000:
                byday[(r["code"], r["date"])].append((etfs[r["e"]], v))
        for (code, d), lst in byday.items():
            buy = [x for x in lst if x[1] > 0]
            sell = [x for x in lst if x[1] < 0]
            fmt = lambda xs: "、".join(f"{e['name']} {'+' if v > 0 else ''}{_lots(v)} 張" for e, v in sorted(xs, key=lambda y: -abs(y[1])))
            title = ("主動 ETF 加碼" if buy and not sell else "主動 ETF 減碼" if sell and not buy else "主動 ETF 有加有減") + f" {len(lst)} 檔"
            add(code, d, "etf", title, "；".join(p for p in [fmt(buy), fmt(sell)] if p), f"etf.html?stock={code}")

    # 外資報告、目標價共識
    an = _load(data / "analyst" / "analyst.json")
    if an:
        act = {"up": "調升", "down": "調降", "initiate": "首評", "keep": "維持"}
        for r in _objs(an["reps"]):
            tp = f"目標價 {_num(r['target'])}" + (f"（前 {_num(r['prev_target'])}）" if r["prev_target"] else "") if r["target"] else ""
            add(r["code"], r["date"], "analyst", f"{r['broker']} {act.get(r['action'], '')}{r['rating'] or ''}".strip() + (f" {tp}" if tp else ""),
                r["title"], "analyst.html#s=" + r["code"])
        for r in _objs(an["cons"]):
            if r["kind"] == "tp" and r["chg_pct"]:
                add(r["code"], r["date"], "analyst", f"目標價共識 {_num(r['prev'])} → {_num(r['value'])}（{'+' if r['chg_pct'] > 0 else ''}{_num(r['chg_pct'])}%）",
                    f"{r['analysts']} 位分析師，最高 {_num(r['high'])}、最低 {_num(r['low'])}", "analyst.html#s=" + r["code"])

    # 重點分點（watch）單日大額買賣超
    w = _load(data / "broker" / "watch.json")
    if w:
        br = w["branches"]
        byday = defaultdict(list)
        for r in _objs(w):
            net = (r["ba"] or 0) - (r["sa"] or 0)  # 仟元；張數常缺，用金額判斷
            if abs(net) >= WATCH_MIN_AMT:
                byday[(r["code"], w["days"][r["d"]])].append((br[r["b"]]["label"], net))
        for (code, d), lst in byday.items():
            lst.sort(key=lambda x: -abs(x[1]))
            tot = sum(v for _, v in lst)
            nb, ns = sum(v > 0 for _, v in lst), sum(v < 0 for _, v in lst)
            title = "重點分點 " + "、".join(x for x in [f"{nb} 家買超" if nb else "", f"{ns} 家賣超" if ns else ""] if x) + \
                f"，合計{'買' if tot >= 0 else '賣'}超約 {_wan(abs(tot))}"
            add(code, d, "broker", title, "、".join(f"{n} {'+' if v > 0 else '−'}{_wan(abs(v))}" for n, v in lst), f"broker.html?s={code}&date={d}")
    # 地方主力：最近一天前幾大買超
    lo = _load(data / "broker" / "local.json")
    if lo and "1" in lo["periods"]:
        p = lo["periods"]["1"]
        score = lo.get("score") or {}
        hits = defaultdict(list)
        for r in _objs({"cols": lo["cols"], "rows": p["rows"]}):
            for k, (code, amt) in enumerate((r["top"] or [])[:LOCAL_TOP]):
                tag = (score.get(r["bid"]) or [None])[0]
                hits[code].append((r, amt, k + 1, tag))
        for code, lst in hits.items():
            lst.sort(key=lambda x: -x[1])
            r0 = lst[0][0]
            add(code, lo["date"], "broker", f"地方主力 {len(lst)} 家大買，合計約 {_wan(sum(x[1] for x in lst))}",
                "、".join(f"{r['name']} {_wan(a)}（該分點第 {k} 大買超{'，' + t if t and t != '一般' else ''}）" for r, a, k, t in lst),
                f"broker.html?b={r0['bid']}&date={lo['date']}" if len(lst) == 1 else f"broker.html?s={code}&date={lo['date']}")
    return ev, names


def write_stock(out: Path, today: date):
    data = Path(out) / "data"
    ev, names = collect(data, today)
    idx = _load(data / "kline" / "index.json") or {}
    for s in idx.get("stocks", []):
        names[s[0]] = s[1]
    d = data / "stock" / "s"
    d.mkdir(parents=True, exist_ok=True)
    gen = today.isoformat()
    for code, es in ev.items():
        es.sort(key=lambda e: e[0], reverse=True)
        (d / f"{code}.json").write_text(json.dumps({"code": code, "name": names.get(code, ""), "gen": gen, "ev": es},
                                                    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (data / "stock" / "index.json").write_text(json.dumps({"gen": gen, "codes": sorted(ev)}, separators=(",", ":")), encoding="utf-8")
    return len(ev)


if __name__ == "__main__":
    import sys
    print(write_stock(Path(sys.argv[1] if len(sys.argv) > 1 else "_site"), date.today()))
