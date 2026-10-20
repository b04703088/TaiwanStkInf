import fetch_treasury_broker as F
for code, bid, bh in [("2474", "700I", "7000"), ("2474", "9800", "9800"), ("2371", "9A9Z", "9A00")]:
    d = F.fetch_daily(code, bid, bh, "2026-08-10", "2026-10-06") if code == "2474" else F.fetch_daily(code, bid, bh, "2025-01-08", "2025-03-05")
    print(code, bid, len(d), d[:3], F.summarize(d), flush=True)
