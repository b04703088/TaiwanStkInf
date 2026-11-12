# 記錄櫃買盤中「熱門股證券商進出排行」的更新時刻（每 2 分鐘問一次到 13:45）
import requests, time, datetime as dt
U = "https://www.tpex.org.tw/www/zh-tw/mostActive/brokerVol?response=json"
last = None
while True:
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    try:
        t = requests.get(U, timeout=30).json()["tables"][0]
        sub = t["subtitle"]
        if sub != last:
            print(now.strftime("%H:%M:%S"), "CHANGED", sub, t["data"][:1], flush=True); last = sub
        else:
            print(now.strftime("%H:%M:%S"), "same", flush=True)
    except Exception as e:
        print(now.strftime("%H:%M:%S"), "ERR", e, flush=True)
    if now.hour * 60 + now.minute > 13 * 60 + 45:
        break
    time.sleep(120)
