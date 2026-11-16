import json, sys, traceback
from datetime import date, timedelta
sys.path.insert(0, ".")
import etf_adapters as A, etf_common as C
for code in ["00984A", "00402A"]:
    try:
        print(code, "adapter ->", A.allianz(code)[0])
    except Exception as e:
        traceback.print_exc()
print("map", A._allianz.get("map"))
fno = A._allianz["map"].get("00984A")
for i in range(9):
    d = date(2026, 11, 9) + timedelta(days=i)
    try:
        r = A._allianz_post("Fund/GetFundTradeInfo", {"Type": 1, "Keyword": "", "FundNo": fno, "Date": d.isoformat()})
        e = C.find_key(r, "Entries") or {}
        tables = C.find_key(r, "DynamicTableData") or []
        print(d, "CNavDt", isinstance(e, dict) and (e.get("CNavDtStr"), e.get("CNavDt"), e.get("CAnceDt") if isinstance(e, dict) else None),
              [ (t.get("TableTitle"), len(t.get("Rows") or [])) for t in tables])
        if i == 8:
            print(json.dumps(r, ensure_ascii=False)[:3000])
    except Exception as ex:
        print(d, "ERR", ex)
