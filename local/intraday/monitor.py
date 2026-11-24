"""潮汐盤中行情偵測（在自己電腦上跑）

資料來源：證交所 MIS 即時報價（上市＋上櫃，約 5 秒一筆快照），從你家的 IP 直接問。
只用 Python 內建套件，不用 pip install。

偵測：
  急拉／急殺   N 分鐘內從低點漲（或從高點跌）超過 X%
  爆量         N 分鐘成交量 >= 平常同樣分鐘數的 k 倍；或今日累積量剛超過近5日均量 x 倍
  漲停         鎖住、打開、再鎖回（附委買張數）
  跌停打開
  族群同步     同一產業鏈族群 10 分鐘內有 3 檔以上急拉（或急殺）
  自選股       watchlist.txt 裡的股票不套成交值濾網、門檻打折

輸出：畫面＋嗶聲、logs/YYYYMMDD.csv、logs/alerts.html（瀏覽器開著會自動更新）、Telegram（選用）。

用法：python monitor.py            （盤中一直跑，收盤自動結束）
      python monitor.py --test     （不管時間，跑兩輪就結束，測試連線用；--rounds=N 改輪數）
"""
import csv
import datetime as dt
import html
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
LOGS = os.path.join(HERE, "logs")
RAW = "https://raw.githubusercontent.com/b04703088/TaiwanStkInf/main/"
MIS = "https://mis.twse.com.tw/stock/"
TZ = dt.timezone(dt.timedelta(hours=8))

DEFAULT_CONFIG = {
    "liq_min_yi": 1,            # 近5日均成交值門檻（億），低於的不掃（自選股除外）
    "batch_size": 80,           # 每次向 MIS 問幾檔
    "request_gap_sec": 2.0,     # 兩次請求間隔（太快會被 MIS 暫時封鎖）
    "surge_minutes": 5,         # 急拉急殺看幾分鐘
    "surge_pct": 2.5,           # 急拉急殺門檻 %
    "vol_minutes": 5,           # 爆量看幾分鐘
    "vol_mult": 4,              # N 分鐘量 >= 平常的幾倍
    "vol_min_lots": 300,        # N 分鐘量至少幾張
    "day_vol_mult": 1.5,        # 今日累積量 >= 近5日均量幾倍（觸發一次）
    "group_window_min": 10,     # 族群同步：幾分鐘內
    "group_min_count": 3,       # 族群同步：幾檔以上
    "watch_factor": 0.6,        # 自選股門檻打幾折
    "cooldown_min": 15,         # 同一檔同一種警示多久內不重複
    "etf_premium_pct": 1.0,     # ETF 折溢價 |%| 超過多少就警示
    "etf_liq_min_yi": 0.1,      # ETF 警示只看近5日均成交值 >= 幾億（etf.html 表格另外可切換）
    "etf_every_sec": 30,        # ETF 預估淨值多久問一次
    "beep": True,
    "telegram_token": "",       # 選用：Telegram bot token
    "telegram_chat_id": "",     # 選用：你的 chat id
    "telegram_types": ["急拉", "急殺", "爆量", "漲停打開", "鎖漲停", "再鎖回", "跌停打開", "族群急拉", "族群急殺", "ETF溢價", "ETF折價"],
}


def now():
    return dt.datetime.now(TZ)


def say(msg):
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("ascii", "replace"), flush=True)


def load_config():
    path = os.path.join(HERE, "config.json")
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        say(f"已建立預設設定檔 {path}，要改門檻或加 Telegram 就改這個檔。")
    return cfg


def fetch(url, opener=None, timeout=15, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    with (opener or urllib.request.build_opener()).open(req, timeout=timeout) as r:
        return r.read()


def cached(name, url, max_age_h=12):
    """從潮汐 repo 下載參考資料，存到 cache/，半天內不重抓。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_h * 3600:
        with open(path, "rb") as f:
            return f.read()
    try:
        data = fetch(url)
    except Exception as e:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        raise RuntimeError(f"下載失敗 {url}: {e}")
    with open(path, "wb") as f:
        f.write(data)
    return data


# ---------- 參考資料：股票清單、近5日均量、族群 ----------

def load_universe(cfg):
    days, d = [], now().date()
    for _ in range(20):
        d -= dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        name = d.strftime("%Y%m%d") + ".csv"
        try:
            raw = cached("daily_" + name, f"{RAW}data/{d.year}/{name}", max_age_h=24 * 30)
        except RuntimeError:
            continue
        days.append(list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))))
        if len(days) == 5:
            break
    if not days:
        raise RuntimeError("抓不到近5日收盤資料")
    info = {}
    for rows in days:
        for r in rows:
            c = r["code"]
            x = info.setdefault(c, {"name": r["name"], "mkt": "tse" if r["market"] == "TWSE" else "otc", "vol": [], "val": []})
            try:
                x["vol"].append(float(r["volume"]) / 1000)
                x["val"].append(float(r["value"]))
            except ValueError:
                pass
    for x in info.values():
        x["avg_vol"] = sum(x["vol"]) / len(days)          # 張
        x["avg_val"] = sum(x["val"]) / len(days) / 1e8    # 億
    return info


def load_groups():
    groups = defaultdict(set)
    raw = cached("rotation_groups.csv", RAW + "config/rotation_groups.csv").decode("utf-8-sig")
    for r in csv.DictReader(line for line in io.StringIO(raw) if not line.startswith("#")):
        for c in (r.get("codes") or "").split():
            groups[r["group"]].add(c)
    raw = cached("chain.csv", RAW + "data/industry/chain.csv").decode("utf-8-sig")
    for r in csv.DictReader(io.StringIO(raw)):
        if r.get("node"):
            groups[f"{r['industry']}／{r['node']}"].add(r["code"])
    return {g: s for g, s in groups.items() if len(s) >= 3}


def load_watch():
    path = os.path.join(HERE, "watchlist.txt")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 自選股：一行一檔代號，# 開頭是註解\n2330\n")
    with open(path, encoding="utf-8") as f:
        return {ln.split()[0] for ln in f if ln.strip() and not ln.startswith("#")}


# ---------- MIS 即時報價 ----------

class Mis:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.warm()

    def warm(self):
        try:                                    # 拿 session cookie；API 沒有 cookie 也能用
            fetch(MIS + "index", self.opener)
        except Exception:
            pass

    def quotes(self, keys):
        url = (MIS + "api/getStockInfo.jsp?json=1&delay=0&_=%d&ex_ch=" % (time.time() * 1000)
               + urllib.parse.quote("|".join(keys), safe="|_."))
        data = json.loads(fetch(url, self.opener, headers={"Referer": MIS + "index"}))
        return data.get("msgArray", [])


def num(s):
    try:
        v = float(s)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def first(s):
    return num((s or "").split("_")[0])


# ---------- 偵測 ----------

class Detector:
    def __init__(self, cfg, info, groups, watch):
        self.cfg, self.info, self.watch = cfg, info, watch
        self.hist = defaultdict(deque)          # code -> deque[(ts, price, cumvol)]
        self.last_alert = {}                    # (code, type) -> ts
        self.limit_state = {}                   # code -> "up"/"down"/None
        self.was_locked = set()
        self.day_vol_done = set()
        self.recent = defaultdict(deque)        # "急拉"/"急殺" -> deque[(ts, code)]
        self.code_groups = defaultdict(list)
        for g, s in groups.items():
            for c in s:
                self.code_groups[c].append(g)
        self.groups = groups

    def th(self, code, v):
        return v * self.cfg["watch_factor"] if code in self.watch else v

    def cool(self, code, typ, ts):
        k = (code, typ)
        if ts - self.last_alert.get(k, 0) < self.cfg["cooldown_min"] * 60:
            return False
        self.last_alert[k] = ts
        return True

    def update(self, q):
        out = []
        code = q.get("c")
        price, cumvol = num(q.get("z")), num(q.get("v"))
        bid1, ask1 = first(q.get("b")), first(q.get("a"))
        up, down = num(q.get("u")), num(q.get("w"))
        if price is None:                       # 這筆快照沒成交：用委買/委賣判斷是否鎖停
            if up and bid1 == up and not ask1:
                price = up
            elif down and ask1 == down and not bid1:
                price = down
            elif self.hist[code]:               # 沿用上一筆成交價（量照樣更新）
                price = self.hist[code][-1][1]
        if price is None or cumvol is None:
            return out
        ts = int(q.get("tlong", time.time() * 1000)) / 1000
        h = self.hist[code]
        if h and ts <= h[-1][0]:
            return out
        h.append((ts, price, cumvol))
        keep = max(self.cfg["surge_minutes"], self.cfg["vol_minutes"]) * 60 + 30
        while h and ts - h[0][0] > keep:
            h.popleft()
        name = q.get("n", "")
        ref = num(q.get("y"))
        chg = (price / ref - 1) * 100 if ref else 0
        base = {"code": code, "name": name, "price": price, "chg": chg, "ts": ts}

        # 急拉／急殺
        win = [p for t, p, _ in h if ts - t <= self.cfg["surge_minutes"] * 60]
        pct = self.th(code, self.cfg["surge_pct"])
        if len(win) >= 2:
            lo, hi = min(win), max(win)
            if price >= lo * (1 + pct / 100) and self.cool(code, "急拉", ts):
                out.append({**base, "type": "急拉", "detail": f"{self.cfg['surge_minutes']}分鐘 {lo:g}→{price:g}（+{(price/lo-1)*100:.1f}%）"})
                self.recent["急拉"].append((ts, code))
            if price <= hi * (1 - pct / 100) and self.cool(code, "急殺", ts):
                out.append({**base, "type": "急殺", "detail": f"{self.cfg['surge_minutes']}分鐘 {hi:g}→{price:g}（{(price/hi-1)*100:.1f}%）"})
                self.recent["急殺"].append((ts, code))

        # 爆量
        x = self.info.get(code)
        if x and x["avg_vol"] > 0:
            vw = [(t, v) for t, _, v in h if ts - t <= self.cfg["vol_minutes"] * 60]
            if len(vw) >= 2:
                span = max(vw[-1][0] - vw[0][0], 60)
                dv = vw[-1][1] - vw[0][1]
                normal = x["avg_vol"] / 270 * span / 60
                mult = self.th(code, self.cfg["vol_mult"])
                if dv >= max(normal * mult, self.cfg["vol_min_lots"]) and self.cool(code, "爆量", ts):
                    out.append({**base, "type": "爆量", "detail": f"{span/60:.0f}分鐘 {dv:,.0f} 張，平常約 {normal:,.0f} 張（{dv/normal:.1f} 倍）"})
            if code not in self.day_vol_done and cumvol >= x["avg_vol"] * self.cfg["day_vol_mult"]:
                self.day_vol_done.add(code)
                if len(h) > 1:                  # 程式開起來時早就超過的不報
                    out.append({**base, "type": "爆量", "detail": f"今日已 {cumvol:,.0f} 張，超過近5日均量 {x['avg_vol']:,.0f} 張的 {self.cfg['day_vol_mult']} 倍"})

        # 漲跌停
        state = "up" if up and price >= up else "down" if down and price <= down else None
        prev = self.limit_state.get(code, "init")
        if state != prev:
            bidq = (q.get("g") or "").split("_")[0]
            askq = (q.get("f") or "").split("_")[0]
            if state == "up":
                typ = "再鎖回" if code in self.was_locked else "鎖漲停"
                self.was_locked.add(code)
                if prev != "init" or typ == "鎖漲停":
                    out.append({**base, "type": typ, "detail": f"委買 {bidq} 張" if bid1 == up else ""})
            elif prev == "up":
                out.append({**base, "type": "漲停打開", "detail": f"委買 {bid1 or '-'}（{bidq} 張）"})
            elif prev == "down":
                out.append({**base, "type": "跌停打開", "detail": f"委賣 {ask1 or '-'}（{askq} 張）"})
            self.limit_state[code] = state
        return out

    def group_check(self, ts):
        out = []
        win = self.cfg["group_window_min"] * 60
        for typ in ("急拉", "急殺"):
            dq = self.recent[typ]
            while dq and ts - dq[0][0] > win:
                dq.popleft()
            hits = {c for _, c in dq}
            cnt = defaultdict(set)
            for c in hits:
                for g in self.code_groups.get(c, []):
                    cnt[g].add(c)
            for g, cs in cnt.items():
                if len(cs) >= self.cfg["group_min_count"] and self.cool("G:" + g, typ, ts):
                    names = "、".join(f"{c}{self.info.get(c, {}).get('name', '')}" for c in sorted(cs))
                    out.append({"code": "", "name": g, "price": "", "chg": 0, "ts": ts, "type": "族群" + typ,
                                "detail": f"{len(cs)}/{len(self.groups[g])} 檔：{names}"})
        return out


# ---------- ETF 折溢價（證交所 ETF 即時預估淨值） ----------

class EtfNav:
    URL = MIS + "data/all_etf.txt"

    def __init__(self, cfg, info):
        self.cfg, self.info = cfg, info
        self.last = 0
        self.side = {}                          # code -> "溢價"/"折價"/None
        self.rows = []

    def poll(self, opener):
        out = []
        if time.time() - self.last < self.cfg["etf_every_sec"]:
            return None
        self.last = time.time()
        data = json.loads(fetch(self.URL + "?_=%d" % (time.time() * 1000), opener,
                                headers={"Referer": MIS + "etf_nav.jsp?ex=tse"}))
        rows, ts = {}, time.time()
        for blk in data.get("a1") or []:
            for m in blk.get("msgArray") or []:
                code = str(m.get("a") or "").strip()
                px, nav = num(m.get("e")), num(m.get("f"))
                prem = None
                try:
                    prem = float(str(m.get("g")).replace(",", ""))
                except (TypeError, ValueError):
                    pass
                if not code or px is None or nav is None or prem is None:
                    continue
                x = self.info.get(code, {})
                rows[code] = {"code": code, "name": x.get("name") or str(m.get("b") or "").strip(),
                              "px": px, "nav": nav, "prem": prem, "liq": x.get("avg_val", 0)}
        self.rows = sorted(rows.values(), key=lambda r: -abs(r["prem"]))
        th = self.cfg["etf_premium_pct"]
        for r in self.rows:
            side = "溢價" if r["prem"] >= th else "折價" if r["prem"] <= -th else None
            prev = self.side.get(r["code"], "init")
            self.side[r["code"]] = side
            if side and side != prev and r["liq"] >= self.cfg["etf_liq_min_yi"]:
                out.append({"code": r["code"], "name": r["name"], "price": r["px"], "chg": 0, "ts": ts,
                            "type": "ETF" + side, "detail": f"市價 {r['px']:g}／預估淨值 {r['nav']:g}，{side} {r['prem']:+.2f}%"})
        return out


# ---------- 輸出 ----------

class Output:
    def __init__(self, cfg, watch):
        self.cfg, self.watch = cfg, watch
        os.makedirs(LOGS, exist_ok=True)
        self.day = now().strftime("%Y%m%d")
        self.csv = os.path.join(LOGS, self.day + ".csv")
        self.html = os.path.join(LOGS, "alerts.html")
        self.rows = []
        if os.path.exists(self.csv):
            with open(self.csv, encoding="utf-8-sig") as f:
                self.rows = list(csv.reader(f))[1:]
        else:
            with open(self.csv, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerow(["時間", "類型", "代號", "名稱", "價格", "漲跌%", "說明", "自選"])

    def emit(self, alerts):
        if not alerts:
            return
        for a in alerts:
            t = dt.datetime.fromtimestamp(a["ts"], TZ).strftime("%H:%M:%S")
            star = "★" if a["code"] in self.watch else ""
            chg = f"{a['chg']:+.2f}" if a["code"] else ""
            row = [t, a["type"], a["code"], a["name"], a["price"], chg, a["detail"], star]
            self.rows.append([str(v) for v in row])
            with open(self.csv, "a", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerow(row)
            head = f"{star}【{a['type']}】{a['code']} {a['name']}" + (f" {a['price']:g} ({chg}%)" if a["code"] and a["chg"] else f" {a['price']:g}" if a["code"] else "")
            say(f"{t} {head} {a['detail']}")
            if a["type"] in self.cfg["telegram_types"] or star:
                self.telegram(f"{head}\n{a['detail']}")
        if self.cfg["beep"] and sys.platform == "win32":
            try:
                import winsound
                winsound.MessageBeep()
            except Exception:
                pass
        self.write_html()

    def write_etf(self, rows):
        if not rows:
            return
        t = now().strftime("%H:%M:%S")
        trs = "".join(
            f'<tr data-liq="{r["liq"]:.2f}"><td>{html.escape(r["code"])}</td><td>{html.escape(r["name"])}</td>'
            f'<td>{r["px"]:g}</td><td>{r["nav"]:g}</td>'
            f'<td style="color:{"#e5484d" if r["prem"] > 0 else "#30a46c"}">{r["prem"]:+.2f}%</td><td>{r["liq"]:.2f}</td></tr>'
            for r in rows)
        page = f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="15">
<title>ETF 折溢價</title><style>
body{{background:#111;color:#ddd;font:14px/1.5 system-ui,"Microsoft JhengHei",sans-serif;margin:16px}}
table{{border-collapse:collapse}}td,th{{padding:4px 10px;border-bottom:1px solid #333;text-align:right}}
td:nth-child(-n+2),th:nth-child(-n+2){{text-align:left}}th{{color:#888;font-weight:normal}}
button{{background:#222;color:#ddd;border:1px solid #444;padding:3px 10px;margin-right:4px;cursor:pointer}}button.on{{background:#3e63dd}}</style>
<h3>ETF 盤中折溢價（{t}，每 15 秒更新，依 |折溢價| 排序）</h3>
<p>近5日均成交值：<span id=f></span></p>
<table><tr><th>代號</th><th>名稱</th><th>市價</th><th>預估淨值</th><th>折溢價</th><th>近5日均成交值(億)</th></tr>{trs}</table>
<script>
var opts=[["不限",0],["≥1億",1],["≥5億",5],["≥20億",20]],cur=1;
try{{cur=+localStorage.getItem("etfliq");if(isNaN(cur)||localStorage.getItem("etfliq")===null)cur=1}}catch(e){{}}
function apply(){{document.querySelectorAll("tr[data-liq]").forEach(function(r){{r.style.display=+r.dataset.liq>=cur?"":"none"}});
document.getElementById("f").innerHTML=opts.map(function(o){{return '<button class="'+(o[1]==cur?"on":"")+'" onclick="cur='+o[1]+';try{{localStorage.setItem(\'etfliq\',cur)}}catch(e){{}};apply()">'+o[0]+'</button>'}}).join("")}}
apply();
</script>"""
        path = os.path.join(LOGS, "etf.html")
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(path + ".tmp", path)

    def telegram(self, text):
        tok, chat = self.cfg.get("telegram_token"), self.cfg.get("telegram_chat_id")
        if not (tok and chat):
            return
        try:
            body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", body, timeout=10)
        except Exception as e:
            say(f"Telegram 送出失敗：{e}")

    def write_html(self):
        color = {"急拉": "#e5484d", "鎖漲停": "#e5484d", "再鎖回": "#e5484d", "族群急拉": "#e5484d",
                 "急殺": "#30a46c", "族群急殺": "#30a46c", "漲停打開": "#f5a524", "跌停打開": "#3e93de", "爆量": "#a971f0"}
        trs = "".join(
            f'<tr><td>{html.escape(r[0])}</td><td><b style="color:{color.get(r[1], "#ccc")}">{html.escape(r[1])}</b></td>'
            f'<td>{html.escape(r[7])}{html.escape(r[2])}</td><td>{html.escape(r[3])}</td><td>{html.escape(r[4])}</td>'
            f'<td>{html.escape(r[5])}</td><td>{html.escape(r[6])}</td></tr>'
            for r in reversed(self.rows[-500:]))
        page = f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<title>盤中異動 {self.day}</title><style>
body{{background:#111;color:#ddd;font:14px/1.5 system-ui,"Microsoft JhengHei",sans-serif;margin:16px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:4px 8px;border-bottom:1px solid #333;text-align:left;white-space:nowrap}}
td:last-child{{white-space:normal}}th{{color:#888;font-weight:normal}}</style>
<h3>潮汐盤中異動 {self.day}（每 10 秒自動更新，最新在上）</h3>
<table><tr><th>時間</th><th>類型</th><th>代號</th><th>名稱</th><th>價格</th><th>漲跌%</th><th>說明</th></tr>{trs}</table>"""
        tmp = self.html + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(tmp, self.html)


# ---------- 主程式 ----------

def in_session(t):
    hm = t.hour * 100 + t.minute
    return t.weekday() < 5 and 900 <= hm <= 1335


def main():
    test = "--test" in sys.argv
    max_rounds = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--rounds=")), 2)
    cfg = load_config()
    say("載入股票清單、近5日均量、族群…")
    info = load_universe(cfg)
    groups = load_groups()
    watch = load_watch()
    stock = lambda c: len(c) == 4 and c.isdigit()
    scan = sorted(c for c, x in info.items() if stock(c) and (x["avg_val"] >= cfg["liq_min_yi"] or c in watch))
    keys = [f"{info[c]['mkt']}_{c}.tw" for c in scan]
    for c in watch - set(info):
        keys.append(f"tse_{c}.tw")
        keys.append(f"otc_{c}.tw")
    say(f"監控 {len(scan)} 檔（近5日均成交值 >= {cfg['liq_min_yi']} 億，加自選 {len(watch)} 檔），族群 {len(groups)} 個。")
    batches = [keys[i:i + cfg["batch_size"]] for i in range(0, len(keys), cfg["batch_size"])]
    say(f"每輪 {len(batches)} 次請求，約 {len(batches) * cfg['request_gap_sec']:.0f} 秒掃一輪。")

    det = Detector(cfg, info, groups, watch)
    etf = EtfNav(cfg, info)
    out = Output(cfg, watch)
    out.write_html()
    say(f"警示表：{out.html}（用瀏覽器打開）")
    say(f"ETF 折溢價表：{os.path.join(LOGS, 'etf.html')}")
    mis, rounds, fails = None, 0, 0
    while True:
        t = now()
        if not test and not in_session(t):
            if t.hour * 100 + t.minute > 1335 or t.weekday() >= 5:
                say("已收盤，結束。")
                return
            say(f"{t:%H:%M} 尚未開盤，等候中…")
            time.sleep(30)
            continue
        start, got = time.time(), 0
        for b in batches:
            try:
                if mis is None:
                    mis = Mis()
                qs = mis.quotes(b)
                got += len(qs)
                fails = 0
                alerts = []
                for q in qs:
                    alerts += det.update(q)
                out.emit(alerts)
            except Exception as e:
                fails += 1
                wait = min(60 * fails, 300)
                say(f"{now():%H:%M:%S} MIS 請求失敗（{e}），{wait} 秒後重試")
                mis = None
                time.sleep(wait)
            time.sleep(cfg["request_gap_sec"])
            try:
                if mis is not None:
                    alerts = etf.poll(mis.opener)
                    if alerts is not None:
                        out.write_etf(etf.rows)
                        out.emit(alerts)
            except Exception as e:
                say(f"{now():%H:%M:%S} ETF 預估淨值抓取失敗（{e}）")
        out.emit(det.group_check(time.time()))
        rounds += 1
        if rounds == 1 or rounds % 20 == 0:
            say(f"{now():%H:%M:%S} 第 {rounds} 輪，收到 {got} 檔報價，耗時 {time.time() - start:.0f} 秒")
        if test and rounds >= max_rounds:
            say("測試完成。")
            return


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
