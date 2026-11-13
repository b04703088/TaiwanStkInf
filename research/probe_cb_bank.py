"""暫時用：看代收行庫重訊內容格式、時碩訂價資料在哪（PR 合併前刪除）"""
import csv, json, sys, time
sys.path.insert(0, ".")
import fetch_cb as F
import fetch_cb_pre as P

ed = F.Edoc(2026, "UnderwritingNotice")
print("NOTICE head", ed.head, "rows", len(ed.rows))
for tds, btn in ed.rows[:25]:
    print("NT", tds[:10], bool(btn))
for tds, btn in ed.rows:
    if "時碩" in "|".join(tds):
        print("TS", tds, btn)
ed = F.Edoc(2026, "BookBuilding")
for tds, btn in ed.rows[:6]:
    print("BB", tds)

for d in ("10", "11", "12", "13"):
    try:
        res = P.mops("t05st02", {"year": "115", "month": "11", "day": d})
    except Exception as e:
        print("ERR", d, e); continue
    for x in res.get("data") or []:
        if x[2].strip() == "4566" or ("公司債" in x[4] and ("訂價" in x[4] or "發行條件" in x[4] or "定價" in x[4])):
            print("MOPS", d, x[:5], json.dumps(x[5], ensure_ascii=False)[:200])
    time.sleep(0.5)

evs = [r for r in csv.DictReader(open("data/cb/mops_events.csv", encoding="utf-8")) if r["kind"] == "bank"]
for ev in evs[-12:] + evs[:3]:
    try:
        det = P.mops("t05st02_detail", {"companyId": ev["code"], "marketKind": ev["market"],
                                        "enterDate": ev["enter_date"], "serialNumber": int(ev["serial"] or 1)})
        row = (det.get("data") or [[]])[0]
        print("BANK", ev["code"], ev["name"], ev["date"], json.dumps(row, ensure_ascii=False)[:1800])
    except Exception as e:
        print("BANKERR", ev["code"], e)
    time.sleep(0.5)
# 完成訂價重訊範例
for code, mk, ed_, sn in (("6658", "sii", "1151102", 1),):
    det = P.mops("t05st02_detail", {"companyId": code, "marketKind": mk, "enterDate": ed_, "serialNumber": sn})
    print("PRICE", json.dumps((det.get("data") or [[]])[0], ensure_ascii=False)[:2500])
