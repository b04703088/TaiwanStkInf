from datetime import date
import fetch_treasury as F
rows = F.fetch_programs("sii", date(2005, 1, 1), date(2023, 12, 31))
print("total", len(rows), flush=True)
for r in rows:
    if r["code"] == "1605":
        print(r, flush=True)
