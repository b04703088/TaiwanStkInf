"""證交所市場休市日（含未來日期）→ data/calendar/holidays.csv

來源：https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule（當年度開休市日期，民國年 yyyMMdd）
「…開始交易日」「…最後交易日」是有交易的日子，不算休市；「市場無交易，僅辦理結算交割作業」算休市。
跟舊檔合併，所以往年的休市日會留著；隔年的日程證交所通常 12 月才公布。
"""
import csv
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "calendar" / "holidays.csv"
URL = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"


def roc_to_iso(s):
    s = str(s).strip()
    if len(s) != 7 or not s.isdigit():
        return None
    return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:]}"


def parse(items):
    out = {}
    for x in items:
        d = roc_to_iso(x.get("Date"))
        name = (x.get("Name") or "").strip()
        if not d or name.endswith("交易日"):
            continue
        out[d] = name
    return out


def load(path=OUT):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fp:
        return {r["date"]: r["name"] for r in csv.DictReader(fp)}


def save(days, path=OUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["date", "name"])
        for d in sorted(days):
            w.writerow([d, days[d]])


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    items = json.loads(urllib.request.urlopen(req, timeout=30).read().decode("utf-8-sig"))
    new = parse(items)
    if not new:
        print("沒有取得休市日", file=sys.stderr)
        return 1
    days = load()
    days.update(new)
    save(days)
    print(f"休市日 {len(new)} 筆（合計 {len(days)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
