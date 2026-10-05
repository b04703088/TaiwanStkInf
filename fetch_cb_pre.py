#!/usr/bin/env python3
"""可轉債（CB）詢圈之前的階段：董事會決議 → 送件申報 → 申報生效。

資料來源（公開、免登入）
  1. 金管會證期局「受理申報(請)案件情形」→ 申報案件彙總表（每個工作天更新；今年＋去年）
     https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52
     欄位：證券代號、承銷商、案件類別（轉換公司債(無擔保) 等）、金額、收文日期（＝送件日）、
           生效日期（審查中案件是預計生效日）、停止生效／自行撤回／退件／廢止撤銷日期
  2. 公開資訊觀測站 重大訊息（新版 API，依日期查詢）
     https://mops.twse.com.tw/mops/api/t05st02          當天所有重訊主旨
     https://mops.twse.com.tw/mops/api/t05st02_detail   單則重訊內容
     抓主旨含「轉換／交換公司債」的公告，分類成 董事會決議、撤回、代收價款行庫；
     董事會決議再讀內容：決議日、第幾次、有無擔保、發行總額、承銷方式（詢圈／競拍）、主辦承銷商。

輸出 data/cb/
  sfb.csv          證期局申報案件（只留國內轉換／交換公司債）
  mops_events.csv  觀測站 CB 相關重訊（含董事會決議解析結果）
  mops_days.txt    已抓過的日期（回補用；最近 7 天每次都重抓）

用法：python fetch_cb_pre.py [--since 2025-01-01] [--max-minutes 25]
  第一次執行會從 --since 一路回補，超過 --max-minutes 就先停，下次接著抓。
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import etf_common as C

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "cb"
SFB_PAGE = "https://www.sfb.gov.tw/ch/home.jsp?id=1016&parentpath=0,6,52"
MOPS_API = "https://mops.twse.com.tw/mops/api/"
DELAY = 0.5

SFB_COLS = ["code", "market", "status", "name", "lead", "kind", "amount", "filed", "fix", "stop", "unstop",
            "effective", "revoked", "withdrawn", "returned", "nature"]
EV_COLS = ["date", "time", "code", "name", "kind", "subject", "market", "enter_date", "serial",
           "board_date", "series", "secured", "amount", "method", "lead", "issue_price", "parsed"]


# ---------------- 小工具 ----------------
def roc_date(s):
    """1150917、115/09/17、115-9-17 → 2026-09-17"""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d{2,3})(\d{2})(\d{2})", s) or re.search(r"(\d{2,3})[/.\-年](\d{1,2})[/.\-月](\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y + 1911, mo, d).isoformat()
    except ValueError:
        return ""


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _read(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


_CN_D = {"零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "貳": 2, "兩": 2, "三": 3, "參": 3, "叁": 3, "四": 4, "肆": 4,
         "五": 5, "伍": 5, "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9}
_CN_U = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_B = {"萬": 10 ** 4, "億": 10 ** 8}


def _small(s):
    """萬以下的數字：參仟伍佰、3,500、1.5、二十 → 數值"""
    s = s.replace(",", "")
    if not s:
        return 0
    if re.fullmatch(r"[\d.]+", s):
        return float(s)
    n, cur = 0, None
    for ch in s:
        if ch.isdigit():
            cur = (cur or 0) * 10 + int(ch)
        elif ch in _CN_D:
            cur = _CN_D[ch]
        elif ch in _CN_U:
            n += (cur if cur is not None else 1) * _CN_U[ch]
            cur = None
    return n + (cur or 0)


def parse_money(text):
    """「新台幣參億伍仟萬元」「新臺幣25億元整」「500,000仟元」「NT$300,000,000」→ 元（int）；找不到回 None"""
    t = unicodedata.normalize("NFKC", text or "").replace("臺", "台")
    m = re.search(r"([\d,.零〇一壹二貳兩三參叁四肆五伍六陸七柒八捌九玖十拾百佰千仟萬億]+)\s*(仟元|千元|萬元|億元|元)", t)
    if not m:
        return None
    expr, unit = m.group(1), m.group(2)
    total, rest = 0.0, expr
    for big in ("億", "萬"):
        if big in rest:
            head, rest = rest.split(big, 1)
            total += _small(head) * _CN_B[big]
    total += _small(rest)
    total *= {"仟元": 1000, "千元": 1000, "萬元": 10 ** 4, "億元": 10 ** 8, "元": 1}[unit]
    return int(round(total)) if total else None


# ---------------- 證期局 申報案件彙總表 ----------------
_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_P = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"


def read_ods(content):
    """ODS（zip + content.xml）→ 第一張工作表的列（字串串列）。"""
    root = ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read("content.xml"))
    table = next(root.iter(_T + "table"))
    rows = []
    for tr in table.iter(_T + "table-row"):
        cells = []
        for tc in tr:
            if tc.tag not in (_T + "table-cell", _T + "covered-table-cell"):
                continue
            n = min(int(tc.get(_T + "number-columns-repeated", "1")), 40)
            cells += ["\n".join("".join(p.itertext()) for p in tc.findall(_P))] * n
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            rows.append(cells)
    return rows


def read_xlsx(content):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    return [["" if v is None else str(v) for v in r] for r in wb.worksheets[0].iter_rows(values_only=True)]


def parse_sfb(rows):
    """彙總表的列 → 國內轉換／交換公司債申報案件（SFB_COLS）。"""
    head_i = next((i for i, r in enumerate(rows) if r and r[0].strip() == "證券代號"), None)
    if head_i is None:
        return []
    head = [re.sub(r"\s+", "", h) for h in rows[head_i]]

    def col(*keys, exact=False):
        return next((i for i, h in enumerate(head) if (h == keys[0] if exact else all(k in h for k in keys))), None)
    ix = {"code": col("證券代號"), "market": col("公司型態"), "status": col("結案類型"), "name": col("公司名稱"),
          "lead": col("承銷商"), "kind": col("案件類別"), "amount": col("金額"), "cur": col("幣別"),
          "filed": col("收文日期"), "fix": col("自動補正"), "stop": col("停止生效"), "unstop": col("解除生效"),
          "effective": col("生效日期", exact=True), "revoked": col("廢止"), "withdrawn": col("自行撤回"),
          "returned": col("退件"), "nature": col("案件性質")}
    out = []
    for r in rows[head_i + 1:]:
        def g(k):
            i = ix[k]
            return r[i].strip() if i is not None and i < len(r) else ""
        kind = g("kind")
        if not re.search(r"[轉交]換公司債", kind) or "海外" in kind or (g("cur") and g("cur") != "台幣"):
            continue
        out.append({"code": g("code"), "market": g("market"), "status": g("status") or "審查中", "name": g("name"),
                    "lead": g("lead"), "kind": kind, "amount": re.sub(r"[^\d]", "", g("amount")),
                    "filed": roc_date(g("filed")),
                    "fix": ",".join(filter(None, (roc_date(x) for x in re.split(r"[,、\s]+", g("fix"))))),
                    "stop": roc_date(g("stop").split(",")[-1]), "unstop": roc_date(g("unstop").split(",")[-1]),
                    "effective": roc_date(g("effective")), "revoked": roc_date(g("revoked")),
                    "withdrawn": roc_date(g("withdrawn")), "returned": roc_date(g("returned")), "nature": g("nature")})
    return out


def fetch_sfb(years):
    """抓指定民國年度的申報案件彙總表（ODS 優先，xlsx 備援）。"""
    page = C.http(SFB_PAGE, as_json=False)
    links = re.findall(r'href="(https://www\.fsc\.gov\.tw/userfiles/file/[^"]+?\.(?:ods|xlsx))"', page)
    out, got = [], []
    for y in years:
        cands = [u for u in links if urllib.parse.unquote(u.rsplit("/", 1)[-1]).startswith(str(y))
                 and "申報案件彙總表" in urllib.parse.unquote(u) and "無償" not in urllib.parse.unquote(u)]
        cands.sort(key=lambda u: not u.endswith(".ods"))
        for u in cands:
            try:
                b = C.http(u, raw=True)
                rows = read_ods(b) if b[:2] == b"PK" and u.endswith(".ods") else read_xlsx(b) if b[:2] == b"PK" else None
                if not rows:
                    continue
                cb = parse_sfb(rows)
                out += cb
                got.append(f"{y}:{urllib.parse.unquote(u.rsplit('/', 1)[-1])}:{len(cb)}")
                break
            except Exception as e:  # noqa: BLE001
                print(f"  證期局 {u[-40:]} 解析失敗：{e}", file=sys.stderr)
    return out, got


# ---------------- 公開資訊觀測站 重大訊息 ----------------
def mops(api, body):
    d = C.http(MOPS_API + api, body=body, headers={"Referer": "https://mops.twse.com.tw/mops/"}, retries=3)
    if not isinstance(d, dict) or d.get("code") != 200:
        raise C.AdapterError(f"{api} {body}: {str(d)[:120]}")
    return d.get("result") or {}


def classify(subject):
    """重訊主旨 → board / withdraw / bank / None（只看國內轉換／交換公司債）。"""
    s = re.sub(r"\s+", "", subject or "")
    if not re.search(r"[轉交]換公司債", s) or re.search(r"海外|私募|ECB|境外|轉讓|處分|取得|買回", s):
        return None
    if re.search(r"撤回|撤銷|不發行|停止發行|暫緩|取消發行", s) and not re.search(r"轉換價格|贖回|變更登記|轉換普通股", s):
        return "withdraw"
    if re.search(r"董事會", s) and re.search(r"決議|通過", s) and re.search(r"發行|募集|辦理", s) \
            and not re.search(r"除權|除息|停止轉換|贖回|轉換價格|收回|買回", s):
        return "board"
    if re.search(r"代收(價|債)款|存儲專戶", s):
        return "bank"
    return None


def parse_list(result):
    """t05st02 回傳 → [{date,time,code,name,subject,market,enter_date,serial,kind}]（只留分類得到的）"""
    out = []
    for x in result.get("data") or []:
        kind = classify(x[4])
        if not kind:
            continue
        p = (x[5] or {}).get("parameters", {}) if isinstance(x[5], dict) else {}
        out.append({"date": roc_date(x[0]), "time": x[1], "code": x[2].strip(), "name": x[3].strip(),
                    "subject": re.sub(r"\s+", "", x[4]), "kind": kind, "market": p.get("marketKind", ""),
                    "enter_date": p.get("enterDate", ""), "serial": str(p.get("serialNumber", ""))})
    return out


def _field(text, n, label):
    """「4.發行總額:xxx」這種編號欄位 → xxx（到下一個編號為止）"""
    m = re.search(rf"(?:^|\n)\s*{n}\s*[.、．]\s*{label}[^:：\n]*[:：]?(.*?)(?=\n\s*\d{{1,2}}\s*[.、．]\s*\S|\Z)", text, re.S)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def parse_board(detail_text, fact_date=""):
    """董事會決議發行公司債的重訊內容 → 決議日、第幾次、有無擔保、發行總額、承銷方式、主辦承銷商。"""
    t = unicodedata.normalize("NFKC", detail_text or "").replace("臺", "台")
    r = {}
    m = re.search(r"董事會決議日期\s*[:：]?\s*(\d{2,3}\s*/\s*\d{1,2}\s*/\s*\d{1,2})", t)
    r["board_date"] = roc_date(re.sub(r"\s", "", m.group(1))) if m else roc_date(fact_date)
    name = _field(t, 2, "名稱") or t[:400]
    sers = re.findall(r"第([一二三四五六七八九十\d]+)次", name)
    from fetch_cb import cn_num  # 共用中文數字轉換
    r["series"] = ",".join(str(cn_num(s)) for s in sers)
    r["secured"] = "有擔保" if "有擔保" in name else "無擔保" if "無擔保" in name else ""
    amt = _field(t, 4, "發行總額") or ""
    r["amount"] = parse_money(amt) or ""
    method = _field(t, 11, "承銷方式") + _field(t, 6, "發行價格")
    r["method"] = "競價拍賣" if "競價拍賣" in method else "詢價圈購" if "詢價圈購" in method else ""
    lead = _field(t, 13, "承銷或代銷機構") or _field(t, 12, "承銷或代銷機構")
    r["lead"] = re.sub(r"[。，,].*$", "", lead)[:30]
    r["issue_price"] = _field(t, 6, "發行價格")[:60]
    r["parsed"] = "1" if r["board_date"] and (r["amount"] or r["series"]) else "0"
    return r


def fetch_events(days, budget_s):
    """逐日抓重訊主旨，董事會決議再抓內容；超過時間預算就停。回傳 (events, 完成的日期)"""
    t0, events, done = time.time(), [], []
    for d in days:
        if time.time() - t0 > budget_s:
            break
        try:
            res = mops("t05st02", {"year": str(d.year - 1911), "month": f"{d.month:02d}", "day": f"{d.day:02d}"})
        except C.AdapterError as e:
            print(f"  {d} 重訊清單失敗：{e}", file=sys.stderr)
            continue
        evs = parse_list(res)
        for ev in evs:
            if ev["kind"] != "board":
                continue
            try:
                det = mops("t05st02_detail", {"companyId": ev["code"], "marketKind": ev["market"],
                                              "enterDate": ev["enter_date"], "serialNumber": int(ev["serial"] or 1)})
                row = (det.get("data") or [[]])[0]
                ev.update(parse_board(row[9] if len(row) > 9 else "", row[8] if len(row) > 8 else ""))
            except Exception as e:  # noqa: BLE001
                print(f"  {ev['code']} {ev['date']} 重訊內容失敗：{e}", file=sys.stderr)
                ev["parsed"] = "0"
            time.sleep(DELAY)
        events += evs
        done.append(d.isoformat())
        time.sleep(DELAY)
    return events, done


# ---------------- 主程式 ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2025-01-01", help="重訊回補起日（預設 2025-01-01）")
    ap.add_argument("--max-minutes", type=float, default=25, help="重訊抓取時間上限（分鐘）")
    ap.add_argument("--skip-mops", action="store_true")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(C.TPE).date()
    errors, log = [], {}

    # 1. 證期局：今年＋去年（去年 12 月送件、今年生效的案子在今年度檔案）
    try:
        rows, got = fetch_sfb([today.year - 1911 - 1, today.year - 1911])
        if rows:
            _write(OUT / "sfb.csv", SFB_COLS, sorted(rows, key=lambda r: (r["filed"], r["code"], r["amount"])))
        else:
            errors.append("證期局申報案件：沒有抓到資料")
        log["sfb"] = got
        print(f"證期局申報案件 {len(rows)} 筆（{'、'.join(got)}）")
    except C.AdapterError as e:
        errors.append(f"證期局申報案件：{e}")

    # 2. 觀測站重訊：最近 7 天每次重抓；其餘從 --since 回補到抓完為止
    if not a.skip_mops:
        done_p = OUT / "mops_days.txt"
        done = set(done_p.read_text().split()) if done_p.exists() else set()
        recent = {(today - timedelta(days=i)).isoformat() for i in range(7)}
        start = date.fromisoformat(a.since)
        todo = [today - timedelta(days=i) for i in range((today - start).days + 1)]  # 新到舊
        todo = [d for d in todo if d.isoformat() in recent or d.isoformat() not in done]
        new, fetched = fetch_events(todo, a.max_minutes * 60)
        old = [e for e in _read(OUT / "mops_events.csv") if e["date"] and e["date"] not in set(fetched)]
        # 同一則重訊（日期＋代號＋序號）只留一筆
        seen, merged = set(), []
        for e in new + old:
            k = (e["enter_date"], e["code"], e["serial"], e["subject"])
            if k not in seen:
                seen.add(k)
                merged.append(e)
        merged.sort(key=lambda e: (e["date"], e["time"], e["code"]))
        _write(OUT / "mops_events.csv", EV_COLS, merged)
        done |= set(fetched)
        done_p.write_text("\n".join(sorted(done)) + "\n")
        left = len([d for d in todo if d.isoformat() not in set(fetched)])
        log["mops"] = {"fetched_days": len(fetched), "left_days": left, "events": len(merged)}
        print(f"重訊：本次 {len(fetched)} 天、還剩 {left} 天未回補；CB 相關重訊共 {len(merged)} 則"
              f"（董事會 {sum(e['kind'] == 'board' for e in merged)}）")

    src = OUT / "pre_sources.json"
    log.update({"generated": datetime.now(C.TPE).strftime("%Y-%m-%d %H:%M"), "errors": errors})
    src.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    for e in errors:
        print("錯誤：" + e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
