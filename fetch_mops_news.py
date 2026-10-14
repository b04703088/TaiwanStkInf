#!/usr/bin/env python3
"""公開資訊觀測站 重大訊息（上市＋上櫃）：每天所有重訊主旨，分類後存檔；股東會、法說會再讀內容抓開會日期。

資料來源（公開、免登入；跟 fetch_cb_pre.py 用同一組新版觀測站 API）
  https://mops.twse.com.tw/mops/api/t05st02          某一天所有公司的重訊主旨（上市、上櫃、興櫃、公開發行）
  https://mops.twse.com.tw/mops/api/t05st02_detail   單則重訊內容（符合條款、事實發生日、說明）

分類（只看主旨，見 classify()）
  shm 股東會、call 法說會、board 董事會決議、div 股利、fin 財報營收、attn 注意處置、legal 訴訟調查、hr 人事異動、
  buyback 庫藏股、capital 增減資／籌資、ma 取得處分／併購、clarify 澄清媒體報導、other 其他
  sub=1 表示「代子公司公告」（多半是子公司背書保證、取得設備，網頁可以隱藏）

另外兩個來源
  https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL     上市除權除息預告表
  https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost      上櫃除權除息預告表
  https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1          法說會一覽表（本月、下月；含簡報檔名、影音連結）

讀內容的（一天幾十則，不會太多）：
  股東會召開公告（董事會決議召開股東常會／臨時會）→ 股東會日期、常會／臨時會、召開方式
  法說會公告 → 法說會日期、時間、地點
  董事會決議、股利、股東會決議、庫藏股、增減資、併購、人事 → 一行重點摘要（summary）；股利另抓除權息日

輸出 data/mops/
  news/<YYYY-MM>.csv  date, time, code, name, market, cat, sub, subject, enter_date, serial,
                      ev_kind, ev_date, ev_note, summary
                      ev_*：股東會（常會／臨時會）、法說會、除權息的日期與說明，其餘留空
  exright.csv         ex_date, code, name, market, kind, cash, stock（預告表；留 60 天）
  calls.csv           date, time, code, name, market, place, summary, file, video（法說會一覽；留 60 天）
  days.txt            已查詢完的日期（今天、昨天每次都重抓；其餘抓過就跳過）
  sources.json        最後執行時間、錯誤、回補進度

用法
  python fetch_mops_news.py                                   # 今天、昨天＋回補還沒抓過的（預設回補 60 天）
  python fetch_mops_news.py --since 2026-01-01 --max-minutes 50   # 回補更早（可分次跑，會接續）
  註：查某天清單會順便拿到前一天晚上發的重訊；股東會旺季一天要讀上百則內容，約 3～4 分鐘
"""
import argparse
import csv
import html
import json
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "mops"
MOPS_API = "https://mops.twse.com.tw/mops/api/"
MARKETS = {"sii": "上市", "otc": "上櫃"}  # 興櫃（rotc）、公開發行（pub）不收
RECENT = 2  # 今天、昨天每次都重抓
DELAY = 0.4

COLS = ["date", "time", "code", "name", "market", "cat", "sub", "subject", "enter_date", "serial",
        "ev_kind", "ev_date", "ev_note", "summary"]
SUMMARY_CATS = {"board", "div", "shm", "buyback", "capital", "ma", "hr"}  # 這些分類（非代子公司）讀內容做摘要

CATS = [  # (代碼, 中文, 主旨規則)；順序有意義，前面的先比對
    ("shm", "股東會", r"股東(?:常|臨時)?會|代行股東會"),
    ("call", "法說會", r"法人說明會|法說會|業績說明會|投資人說明會|投資人會議|投資論壇|CEO\s?Week|受邀參加"),
    ("buyback", "庫藏股", r"買回(?:本公司|公司)?(?:股份|股票|庫藏)|庫藏股"),
    ("div", "股利", r"股利|配息|除權|除息|盈餘分配|盈餘分派|資本公積.{0,6}發放|現金減資.{0,8}(?:基準日|退還)"),
    ("fin", "財報營收", r"財務報告|財務報表|財報|自結|營收|營業收入|營業額|業績資料|營運成績|銷售情形|損益|每股盈餘|EPS|獲利|"
                     r"季報|年報|會計師.{0,8}(?:更換|查核|核閱)"),
    ("attn", "注意處置", r"注意交易資訊|變更交易方法|處置(?:有價證券|股票|期間)|列為處置|股價異常|分盤交易"),
    ("legal", "訴訟調查", r"搜索|調查局|檢調|羈押|起訴|訴訟|判決|仲裁|裁罰|罰鍰|假扣押|強制執行"),
    ("hr", "人事異動", r"董事長|副?總經理|執行長|發言人|財務主管|會計主管|稽核主管|研發主管|公司治理主管|"
                   r"(?:獨立)?董事.{0,8}(?:辭|異動|變動|解任|改選|補選|當選|變更)|董事.{0,4}監察人|監察人.{0,6}(?:辭|異動|變動)|"
                   r"薪資報酬委員|審計委員|經理人.{0,6}(?:異動|變動|辭)|法人董事.{0,4}(?:改派|指派)|技術長|營運長|策略長|"
                   r"(?:營運|業務|重要)主管.{0,4}異動|委員.{0,4}異動"),
    ("capital", "增減資籌資", r"增資|減資|私募|公司債|發行新股|新股發行|現增|存託憑證|GDR|ECB|募集|承銷|上市櫃?.{0,4}申請|掛牌|員工認股權|限制員工權利新股|轉換價格"),
    ("ma", "取得處分併購", r"(?:取得|處分|出售|購置|購買|租賃|承租|出租)(?!.{0,4}(?:許可|認證|專利|訂單|執照)).{0,14}"
                         r"(?:有價證券|股權|股份|股票|資產|不動產|土地|廠房|廠房|設備|機器|使用權|子公司|公司|大樓|房地)|"
                         r"擬取得|合併案|吸收合併|收購|併購|分割|公開收購|股份轉換|策略聯盟|增加投資|轉投資|合資|投資設立|長期租賃|訂購.{0,6}設備|供營業用"),
    ("clarify", "澄清報導", r"澄清|媒體報導|報載|新聞報導|說明.{0,6}報導"),
    ("board", "董事會決議", r"董事會"),
]
CAT_RE = [(k, re.compile(p)) for k, _, p in CATS]
SUB_RE = re.compile(r"^(?:\(?(?:更正|補充)(?:公告)?\)?)?\s*代(?!理).{1,30}?公告|子公司.{0,30}公告")


# ---------------- 小工具 ----------------
def roc_date(s):
    """1150917、115/09/17、115-9-17、115年9月17日 → 2026-09-17；西元 2026/09/17 也可以"""
    s = unicodedata.normalize("NFKC", s or "").strip()
    m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", s) or \
        re.search(r"(?<!\d)(\d{2,4})\s*[/.\-年]\s*(\d{1,2})\s*[/.\-月]\s*(\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    if y < 1000:
        y += 1911
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def norm(s):
    """HTML 字元參照（&#12079; 這種康熙部首）解開＋全形轉半形"""
    return unicodedata.normalize("NFKC", html.unescape(s or ""))


def clean(s):
    return re.sub(r"\s+", "", norm(s))


def classify(subject):
    s = clean(subject)
    for k, rx in CAT_RE:
        if k == "shm" and re.search(r"股東(?:常|臨時)?會(?:決議)?(?:通過之|授權)", s):
            continue  # 「不繼續辦理 114 年股東常會通過之私募案」是籌資，不是股東會
        if rx.search(s):
            return k
    return "other"


def is_sub(subject):
    return "1" if SUB_RE.search(clean(subject)) else ""


def shm_notice(subject):
    """主旨是「召開股東會」的公告（不是股東會決議事項、也不是股東會通過的案子後續）。"""
    s = clean(subject)
    if not re.search(r"股東(?:常|臨時)?會", s):
        return False
    if re.search(r"決議事項|重要決議|股東(?:常|臨時)?會(?:決議|通過)|會議決議|延會|(?:不繼續|終止|停止)辦理", s):
        return False
    return bool(re.search(r"召開|召集|股東(?:常|臨時)?會(?:相關|日期|召開|議案|事宜|召集)", s))


def call_notice(subject):
    s = clean(subject)
    return bool(re.search(r"法人說明會|法說會|業績說明會", s)) and not re.search(r"簡報|影音|錄音|內容|摘要|更正", s)


def _after(text, labels, n=60):
    """找第一個「標籤…：」後面的文字（到換行為止）。"""
    for lb in labels:
        m = re.search(rf"{lb}[^:：\n]{{0,40}}[:：]\s*([^\n]{{0,{n}}})", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def parse_shm(subject, text):
    """股東會召開公告內容 → (常會/臨時會, 日期, 召開方式)"""
    t = norm(text)
    d = roc_date(_after(t, ["股東會召開日期", "股東(?:常|臨時)會(?:召開)?日期", "召開日期", "開會日期"]))
    s = clean(subject)
    kind = "臨時會" if "臨時" in s or re.search(r"股東臨時會", t[:300]) else "常會"
    how = _after(t, ["股東會召開方式"], 30)
    how = "視訊" if how.startswith("視訊股東會") else "視訊輔助" if "視訊輔助" in how else ""
    return kind, d, how


def parse_call(text):
    """法說會公告內容 → (日期, 說明)：「1.召開法人說明會之日期:115/10/20」「2.…時間:14時00分」「3.…地點:…」"""
    t = norm(text)
    d = roc_date(_after(t, ["法人說明會之日期", "法說會之?日期", "說明會日期", "召開日期", "日期"]))
    tm = _after(t, ["法人說明會之時間", "法說會之?時間", "時間"], 20)
    m = re.search(r"(\d{1,2})\s*[時:：]\s*(\d{2})?", tm)
    hhmm = f"{int(m.group(1)):02d}:{m.group(2) or '00'}" if m else ""
    place = _after(t, ["法人說明會之地點", "法說會之?地點", "地點"], 40)
    place = re.sub(r"https?://\S*|[。;；].*$", "", place).strip(" ,，、")[:30]
    return d, " ".join(x for x in (hhmm, place) if x)


# ---------------- 重訊內容 → 摘要 ----------------
DATE_ONLY = re.compile(r"^\d{2,4}[/-]\d{1,2}[/-]\d{1,2}$")
NOISE = re.compile(r"^(?:無|不適用|N/?A|NA|－|-|—|否|無。|不適用。)$", re.I)


def fields(text):
    """「1.標籤:內容」編號欄位 → [(標籤, 內容)]；內容可跨行，到下一個編號為止。"""
    t = norm(text).replace("\r", "")
    out = []
    for m in re.finditer(r"(?m)^\s*(\d{1,2})\s*[.、]\s*([^:：]{1,90}?)\s*[:：]([\s\S]*?)(?=^\s*\d{1,2}\s*[.、]\s*[^:：]{1,90}?[:：]|\Z)", t):
        v = re.sub(r"\s+", " ", m.group(3)).strip()
        out.append((re.sub(r"\s+", "", m.group(2)), v))
    return out


def _short(v, n=48):
    v = re.sub(r"\s+", " ", v).strip(" ;；。,，")
    return v if len(v) <= n else v[:n - 1] + "…"


def _pick(fs, rules, n=3):
    """依 rules（標籤關鍵字, 顯示名稱）挑欄位；內容是「無／不適用」的略過。"""
    out, used = [], set()
    for kw, show in rules:
        for lb, v in fs:
            if "日期" in lb and not re.search("期間|日", show or "期間"):
                continue  # 「…達一定標準之日期」這種欄位不是要找的數字
            if re.search(r"公司名稱|與公司關係", lb) or DATE_ONLY.match(v or ""):
                continue
            if re.search(kw, lb) and v and not NOISE.match(v) and v not in used and not any(o.startswith(show + "：") for o in out):
                m = re.search(r"交易總金額[^:：]{0,6}[:：]\s*([\d,]+)", v)
                v2 = f"{m.group(1)} 元" if m else v
                out.append(f"{show}：{_short(v2)}" if show else _short(v2))
                used.add(v)
                break
        if len(out) >= n:
            break
    return out


def per_share(text):
    m = re.search(r"每股[^0-9。；;]{0,16}?(\d+(?:\.\d+)?)\s*元", text or "")
    return f"{float(m.group(1)):.4f}".rstrip("0").rstrip(".") if m else ""  # 0.9999999376 → 1


def parse_div(text):
    """除權息公告內容 → {kind, ex_date, cash, stock, pay_date}（每股金額，元）"""
    fs = dict(fields(text))
    g = lambda kw: next((v for k, v in fs.items() if re.search(kw, k)), "")
    kind = re.sub(r"[^除權息]", "", g(r"除權.?息類別"))[:3]
    body = g(r"股利種類及金額|發放.*股利")
    cash = per_share(body.split("現金股利", 1)[1] if "現金股利" in body else (body if "股票股利" not in body else ""))
    stock = per_share(body.split("股票股利", 1)[1].split("現金股利", 1)[0]) if "股票股利" in body else ""
    if "調整後" in body:  # 調整配息率：取調整後
        cash = per_share(body.split("調整後", 1)[1]) or cash
    return {"kind": kind if kind in ("除權", "除息", "除權息") else "", "ex_date": roc_date(g(r"除權.?息.?交易日")),
            "cash": cash, "stock": stock, "pay_date": roc_date(g(r"現金股利發放日期"))}


def summarize(cat, subject, text):
    """重訊內容 → 一行重點（最多約 140 字）"""
    fs = fields(text)
    if not fs:
        return _short(norm(text), 120) if text else ""
    s = clean(subject)
    if cat == "div" and re.search(r"元/股", norm(text)):  # 董事會決議股利分派（還沒有除權息日）
        t = norm(text)
        cash = sum(float(x) for x in re.findall(r"(?:盈餘分配之現金股利|法定盈餘公積發放之現金|資本公積發放之現金)\(元/股\)\s*[:：]\s*([\d.]+)", t))
        stock = sum(float(x) for x in re.findall(r"(?:盈餘轉增資配股|法定盈餘公積轉增資配股|資本公積轉增資配股)\(元/股\)\s*[:：]\s*([\d.]+)", t))
        yr = _after(t, ["股利所屬年\\(季\\)度", "股利所屬年度"], 20)
        f = lambda v: f"{v:.4f}".rstrip("0").rstrip(".")
        return "・".join(x for x in (f"{yr}" if yr else "", f"現金 {f(cash)} 元", f"股票 {f(stock)} 元" if stock else "") if x)
    if cat == "div":
        d = parse_div(text)
        parts = [f"現金 {d['cash']} 元" if d["cash"] else "", f"股票 {d['stock']} 元" if d["stock"] else "",
                 f"{d['kind'] or '除權息'}交易日 {d['ex_date']}" if d["ex_date"] else "", f"發放 {d['pay_date']}" if d["pay_date"] else ""]
        parts = [p for p in parts if p] or _pick(fs, [(r"股利|盈餘分配|分派", "")])
        return "・".join(parts)
    if cat == "shm":
        rules = [(r"盈餘分配|盈虧撥補", "盈餘分配"), (r"董監事選舉|選舉", "選舉"), (r"重要決議事項$|^重要決議事項", ""),
                 (r"其他事項", "其他"), (r"章程", "章程")]
    elif cat == "buyback":
        rules = [(r"預定買回之?數量|本次已買回股份數量|本次買回股份數量", "股數"), (r"區間價格|平均每股買回價格", "價格"),
                 (r"預定買回之?期間|實際買回期間", "期間"), (r"買回.{0,4}目的", "目的"), (r"總金額", "金額")]
    elif cat == "hr":
        rules = [(r"舊任者", "舊任"), (r"新任者", "新任"), (r"異動原因|變動原因", "原因"), (r"人員別|職務", "職務")]
    elif cat == "ma":
        rules = [(r"標的物|證券名稱|名稱及性質", "標的"), (r"交易總金額|交易金額|總金額", "金額"),
                 (r"交易相對人", "對象"), (r"目的", "目的")]
    elif cat == "capital":
        rules = [(r"發行總額|私募股數|發行股數|增資金額|募集金額|發行金額|減資金額", "規模"), (r"發行價格|私募價格|轉換價格", "價格"),
                 (r"種類|名稱", "種類"), (r"資金用途|用途|目的|變動原因", "用途"), (r"緣由", "")]
    else:  # board 與其他
        rules = [(r"投資計畫內容|計畫內容|內容|標的", ""), (r"預計投資金額|金額", "金額"), (r"變動緣由|緣由|原因|決議事項", ""),
                 (r"目的|用途", "目的")]
    out = _pick(fs, rules)
    if not out:
        out = [_short(v) for lb, v in fs if v and not NOISE.match(v) and not re.search(r"日期|事實發生日|公司名稱|與公司關係", lb)][:2]
    return "；".join(out)[:140]


# ---------------- 觀測站 ----------------
def mops(api, body):
    d = C.http(MOPS_API + api, body=body, headers={"Referer": "https://mops.twse.com.tw/mops/"}, retries=3)
    if not isinstance(d, dict) or d.get("code") != 200:
        raise C.AdapterError(f"{api} {body}: {str(d)[:120]}")
    return d.get("result") or {}


def parse_list(result):
    """t05st02 回傳 → [{date,time,code,name,market,cat,sub,subject,enter_date,serial}]（只留上市櫃）"""
    out = []
    for x in result.get("data") or []:
        if len(x) < 6:
            continue
        p = (x[5] or {}).get("parameters", {}) if isinstance(x[5], dict) else {}
        mk = p.get("marketKind", "")
        if mk not in MARKETS:
            continue
        subj = re.sub(r"\s+", " ", norm(x[4])).strip()
        out.append({"date": roc_date(x[0]), "time": (x[1] or "").strip(), "code": (x[2] or "").strip(),
                    "name": (x[3] or "").strip(), "market": mk, "cat": classify(subj), "sub": is_sub(subj),
                    "subject": subj, "enter_date": str(p.get("enterDate", "")), "serial": str(p.get("serialNumber", "")),
                    "ev_kind": "", "ev_date": "", "ev_note": "", "summary": ""})
    return out


def detail(ev):
    det = mops("t05st02_detail", {"companyId": ev["code"], "marketKind": ev["market"],
                                  "enterDate": ev["enter_date"], "serialNumber": int(ev["serial"] or 1)})
    row = (det.get("data") or [[]])[0]
    return row[9] if len(row) > 9 else ""


def enrich(ev):
    """讀內容：股東會召開、法說會 → ev_kind / ev_date / ev_note；除權息公告 → ev_kind=除息等、ev_date=交易日；
    SUMMARY_CATS → summary。回傳是否有呼叫 API。"""
    if ev["sub"]:
        return False
    if ev["cat"] == "shm" and shm_notice(ev["subject"]):
        kind, d, how = parse_shm(ev["subject"], detail(ev))
        ev.update(ev_kind=kind, ev_date=d, ev_note=how)
        return True
    if ev["cat"] == "call" and call_notice(ev["subject"]):
        d, note = parse_call(detail(ev))
        ev.update(ev_kind="法說會", ev_date=d, ev_note=note)
        return True
    if ev["cat"] in SUMMARY_CATS:
        text = detail(ev)
        ev["summary"] = summarize(ev["cat"], ev["subject"], text) or "-"  # "-"：讀過但沒有可摘要的內容
        if ev["cat"] == "div":
            d = parse_div(text)
            if d["ex_date"]:
                ev.update(ev_kind=d["kind"] or "除權息", ev_date=d["ex_date"],
                          ev_note="・".join(x for x in (f"現金 {d['cash']}" if d["cash"] else "", f"股票 {d['stock']}" if d["stock"] else "",
                                                       f"發放 {d['pay_date']}" if d["pay_date"] else "") if x))
        return True
    return False


def fetch_days(days, budget_s, prev):
    """逐日抓；prev = {(代號, enterDate, 序號): 舊資料}，已有開會日期的沿用、不重抓內容。
    注意：查某一天的清單也會包含前一天晚上發的重訊（發言日期是前一天）。回傳 (events, 完成的日期, 錯誤)"""
    t0, events, done, errors = time.time(), [], [], []
    for d in days:
        if time.time() - t0 > budget_s:
            break
        try:
            res = mops("t05st02", {"year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"})
        except C.AdapterError as e:
            errors.append(f"{d} 重訊清單：{e}")
            continue
        evs = parse_list(res)
        t1, nd = time.time(), 0
        for ev in evs:
            p = prev.get((ev["code"], ev["enter_date"], ev["serial"]))
            if p and (p.get("ev_date") or p.get("summary")):  # 讀過內容的沿用
                ev.update(ev_kind=p["ev_kind"], ev_date=p["ev_date"], ev_note=p["ev_note"], summary=p.get("summary") or "")
                continue
            try:
                if enrich(ev):
                    nd += 1
                    time.sleep(DELAY)
            except Exception as e:  # noqa: BLE001
                print(f"  {ev['code']} {ev['date']} 重訊內容失敗：{e}", file=sys.stderr)
        events += evs
        done.append(d.isoformat())
        print(f"  {d} {len(evs)} 則、讀內容 {nd} 則（{time.time() - t1:.0f} 秒）", flush=True)
        time.sleep(DELAY)
    return events, done, errors


# ---------------- 除權除息預告表 ----------------
TWSE_EXR = "https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL"
TPEX_EXR = "https://www.tpex.org.tw/openapi/v1/tpex_exright_prepost"
EXR_COLS = ["ex_date", "code", "name", "market", "kind", "cash", "stock"]


def _f(v):
    try:
        x = float(str(v).replace(",", ""))
    except ValueError:
        return ""
    return f"{x:.6f}".rstrip("0").rstrip(".") if x else ""


def parse_exright(rows, market):
    """證交所 TWT48U_ALL／櫃買 tpex_exright_prepost → [{ex_date, code, name, market, kind, cash, stock}]
    stock：無償配股率（股/股）× 面額 10 元，換成「每股配股 X 元」的習慣說法"""
    out = []
    for r in rows or []:
        g = lambda *ks: next((str(r[k]).strip() for k in ks if r.get(k) not in (None, "")), "")
        code = g("Code", "SecuritiesCompanyCode")
        d = roc_date(g("Date", "ExRrightsExDividendDate"))
        k = g("Exdividend", "ExRrightsExDividend").replace("除", "")
        if not code or not d:
            continue
        ratio = _f(g("StockDividendRatio"))
        out.append({"ex_date": d, "code": code, "name": g("Name", "CompanyName"), "market": market,
                    "kind": {"息": "除息", "權": "除權", "權息": "除權息"}.get(k, "除權息"), "cash": _f(g("CashDividend")),
                    "stock": _f(float(ratio) * 10) if ratio else ""})
    return out


def fetch_exright():
    out, errs = [], []
    for url, mk in ((TWSE_EXR, "sii"), (TPEX_EXR, "otc")):
        try:
            out += parse_exright(C.http(url), mk)
        except C.AdapterError as e:
            errs.append(f"除權息預告表 {mk}：{e}")
    return out, errs


# ---------------- 法說會一覽表（觀測站法說會專區） ----------------
CALLS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"  # 新版站的同名頁面也是轉呼叫這個
CALL_COLS = ["date", "time", "code", "name", "market", "place", "summary", "file", "video"]
FILE_URL = "https://mopsov.twse.com.tw/nas/STR/{}"


def _txt(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def parse_calls(page, market):
    """法說會一覽表 HTML → [{date, time, code, name, market, place, summary, file, video}]"""
    out = []
    for row in re.findall(r"<tr[^>]*data-type='body'[^>]*>(.*?)</tr>", page or "", re.S):
        td = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(td) < 6:
            continue
        f = re.search(r'fileName\.value="([^"]+)"', td[6]) if len(td) > 6 else None
        v = re.search(r"href='(https?://[^']+)'", td[9]) if len(td) > 9 else None
        d = roc_date(_txt(td[2]))
        if not d:
            continue
        out.append({"date": d, "time": _txt(td[3])[:5], "code": _txt(td[0]), "name": _txt(td[1]), "market": market,
                    "place": _txt(td[4])[:60], "summary": _txt(td[5])[:120], "file": f.group(1) if f else "",
                    "video": v.group(1) if v else ""})
    return out


def fetch_calls(today):
    """本月與下個月公告的法說會（上市、上櫃）。"""
    out, errs = [], []
    nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    for mk in MARKETS:
        for d in (today, nxt):
            try:
                page = C.http(CALLS_URL, form={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": mk,
                                               "year": str(d.year - 1911), "month": f"{d.month:02d}", "co_id": ""}, as_json=False)
                out += parse_calls(page, mk)
            except C.AdapterError as e:
                errs.append(f"法說會一覽表 {mk} {d:%Y-%m}：{e}")
            time.sleep(DELAY)
    return out, errs


# ---------------- 存檔 ----------------
def read_all(out=OUT):
    rows = []
    for f in sorted((out / "news").glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].csv")):
        with f.open(encoding="utf-8") as fp:
            rows += list(csv.DictReader(fp))
    return rows


def write_months(rows, months, out=OUT):
    """只改寫有動到的月份檔。"""
    (out / "news").mkdir(parents=True, exist_ok=True)
    by = {}
    for r in rows:
        by.setdefault(r["date"][:7], []).append(r)
    for m in months:
        rs = sorted(by.get(m, []), key=lambda r: (r["date"], r["time"], r["code"], r["serial"]))
        with (out / "news" / f"{m}.csv").open("w", encoding="utf-8", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rs)


def merge_table(path, cols, new, keyf, keep_since):
    """小表（除權息、法說會）：同 key 以新抓的為準，舊資料只留 keep_since 之後的。"""
    old = []
    if path.exists():
        with path.open(encoding="utf-8") as fp:
            old = list(csv.DictReader(fp))
    out = {keyf(r): r for r in old if (r.get(cols[0]) or "") >= keep_since}
    out.update({keyf(r): r for r in new})
    rows = sorted(out.values(), key=lambda r: (r[cols[0]], r["code"]))
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows


def key(r):
    return r["code"], r["enter_date"], r["serial"]


def merge(old, new):
    """同一則重訊（代號＋enterDate＋序號）以新抓的為準，其餘保留。"""
    out = {key(r): r for r in old}
    out.update({key(r): r for r in new})
    return list(out.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="回補起日（預設 60 天前，夠涵蓋還沒開的股東臨時會、法說會公告）")
    ap.add_argument("--max-minutes", type=float, default=20, help="抓取時間上限（分鐘），超過就停，下次接著抓")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(C.TPE).date()

    done_p = OUT / "days.txt"
    done = set(done_p.read_text().split()) if done_p.exists() else set()
    recent = {(today - timedelta(days=i)).isoformat() for i in range(RECENT)}
    start = date.fromisoformat(a.since) if a.since else today - timedelta(days=60)
    todo = [today - timedelta(days=i) for i in range((today - start).days + 1)]  # 新到舊
    todo = [d for d in todo if d.isoformat() in recent or d.isoformat() not in done]

    old = read_all()
    new, fetched, errors = fetch_days(todo, a.max_minutes * 60, {key(r): r for r in old})
    rows = merge(old, new)
    for r in rows:  # 分類規則改了，舊資料也跟著重分（內容沒變的月份檔不會有 diff）
        r["cat"], r["sub"] = classify(r["subject"]), is_sub(r["subject"])
    write_months(rows, sorted({r["date"][:7] for r in rows if r["date"]}))
    done |= set(fetched)
    done_p.write_text("\n".join(sorted(done)) + "\n")

    keep = (today - timedelta(days=60)).isoformat()
    exr, e1 = fetch_exright()
    calls, e2 = fetch_calls(today)
    errors += e1 + e2
    exr = merge_table(OUT / "exright.csv", EXR_COLS, exr, lambda r: (r["code"], r["ex_date"]), keep)
    calls = merge_table(OUT / "calls.csv", CALL_COLS, calls, lambda r: (r["code"], r["date"], r["time"]), keep)
    print(f"除權息預告 {len(exr)} 筆、法說會一覽 {len(calls)} 筆")

    left = len([d for d in todo if d.isoformat() not in set(fetched)])
    cats = {}
    for r in new:
        cats[r["cat"]] = cats.get(r["cat"], 0) + 1
    ev = [r for r in new if r["ev_kind"]]
    miss = [f"{r['code']}{r['name']} {r['date']}" for r in ev if not r["ev_date"]]
    log = {"generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "fetched_days": len(fetched),
           "left_days": left, "news": len(new), "cats": cats, "exright": len(exr), "calls": len(calls), "events": len(ev), "unparsed": miss[:20],
           "errors": errors[:20]}
    (OUT / "sources.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"重訊：本次 {len(fetched)} 天 {len(new)} 則（股東會／法說會 {len(ev)} 則，日期沒解析到 {len(miss)} 則）；"
          f"還剩 {left} 天未回補")
    for e in errors:
        print("錯誤：" + e, file=sys.stderr)
    return 1 if errors and not fetched else 0


if __name__ == "__main__":
    sys.exit(main())
