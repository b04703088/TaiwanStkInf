"""盤中上櫃熱門股券商進出（櫃買中心「熱門股證券商進出排行」）。

櫃買盤中定時更新兩張表：依成交量（張）、依成交金額（仟元），各是熱門前 30 檔 × 前 10 大券商（總公司合計）。
  https://www.tpex.org.tw/www/zh-tw/mostActive/brokerVol?response=json
  https://www.tpex.org.tw/www/zh-tw/mostActive/brokerAmt?response=json

櫃買實測（2026-11-12）：整點後 1–2 分鐘更新一次（截至 10:00、11:00、12:00），13:00 沒有更新，
收盤後約 13:45 出全天的最後一版（「截至13:46止」）。

開盤期間在 GitHub Actions 上每分鐘問一次，櫃買的統計時間變了才發布：
寫成 rtbrk.json，以單一 commit 強推到 `live` 分支（不進 main、不觸發部署）。
網頁 site/rtbrk.html 直接從 GitHub 讀 live 分支的檔案。

收盤後（最後一筆）另存 data/rtbrk/YYYY-MM-DD.json，由 workflow commit 回 main，留作日後回測。

用法：
  python fetch_rtbrk.py --loop          # 盤中一直跑到收盤後全天資料出來（最晚 --until，預設 14:15）
  python fetch_rtbrk.py --once --out x.json
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

SRC = "https://www.tpex.org.tw/www/zh-tw/mostActive/{}?response=json"
TPE = dt.timezone(dt.timedelta(hours=8))
LIVE_DIR = "_live"


def now_tpe():
    return dt.datetime.now(TPE)


def get_json(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}", flush=True)
            time.sleep(5)


def pull(kind):
    j = get_json(SRC.format(kind))
    t = (j.get("tables") or [None])[0]
    if not t or "data" not in t:
        raise ValueError(f"{kind} 格式不符")
    return {"subtitle": t.get("subtitle", ""), "fields": t.get("fields", []), "data": t["data"]}


def asof(subtitle):
    """「115年11月12日 截至10:00止 …」→ ('2026-11-12', '10:00')"""
    m = re.search(r"(\d+)年(\d+)月(\d+)日\s*截至\s*(\d+:\d+)", subtitle or "")
    if not m:
        return None, None
    return f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}", m[4]


def snapshot():
    vol, amt = pull("brokerVol"), pull("brokerAmt")
    d, t = asof(vol["subtitle"])
    return {
        "fetched": now_tpe().strftime("%Y-%m-%d %H:%M:%S"),
        "date": d, "time": t,
        "vol": vol, "amt": amt,
    }


def sh(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def publish(snap):
    """把 rtbrk.json 以單一 commit 強推到 live 分支（舊版不留歷史）。"""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("  （沒有 GITHUB_REPOSITORY / GITHUB_TOKEN，略過發布）", flush=True)
        return
    os.makedirs(LIVE_DIR, exist_ok=True)
    first = not os.path.isdir(os.path.join(LIVE_DIR, ".git"))
    if first:
        sh("git", "init", "-q", "-b", "live", cwd=LIVE_DIR)
        sh("git", "config", "user.name", "github-actions[bot]", cwd=LIVE_DIR)
        sh("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=LIVE_DIR)
        sh("git", "remote", "add", "origin", f"https://x-access-token:{token}@github.com/{repo}.git", cwd=LIVE_DIR)
    with open(os.path.join(LIVE_DIR, "rtbrk.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    sh("git", "add", "rtbrk.json", cwd=LIVE_DIR)
    msg = f"盤中熱門股券商進出 {snap['date']} {snap['time']}"
    if first:
        sh("git", "commit", "-q", "-m", msg, cwd=LIVE_DIR)
    else:
        sh("git", "commit", "-q", "--amend", "-m", msg, cwd=LIVE_DIR)
    sh("git", "push", "-q", "-f", "origin", "live", cwd=LIVE_DIR)


def save_day(snap):
    os.makedirs("data/rtbrk", exist_ok=True)
    path = f"data/rtbrk/{snap['date']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  saved {path}", flush=True)


def loop(until, interval):
    today = now_tpe().strftime("%Y-%m-%d")
    hh, mm = map(int, until.split(":"))
    last_key, last = None, None
    while True:
        n = now_tpe()
        try:
            s = snapshot()
            key = (s["date"], s["time"])
            if s["date"] != today:
                print(f"{n:%H:%M:%S} 櫃買資料日期 {s['date']}，還不是今天", flush=True)
                # 開盤 40 分鐘後還沒有今天的資料 → 視為休市
                if n.hour * 60 + n.minute > 9 * 60 + 40:
                    print("今天沒有盤中資料（休市？），結束", flush=True)
                    return
            elif key != last_key:
                print(f"{n:%H:%M:%S} 更新：截至 {s['time']}，{len(s['vol']['data'])} 列", flush=True)
                publish(s)
                last_key, last = key, s
                if s["time"] >= "13:30":
                    print("已拿到收盤後的全天資料，結束", flush=True)
                    break
            else:
                print(f"{n:%H:%M:%S} 未變（截至 {s['time']}）", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{n:%H:%M:%S} 失敗：{e}", flush=True)
        if (n.hour, n.minute) >= (hh, mm):
            break
        time.sleep(interval)
    if last:
        save_day(last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--until", default="14:15", help="台北時間，最晚跑到這個時間（拿到收盤後全天資料就提早結束）")
    ap.add_argument("--interval", type=int, default=60)
    a = ap.parse_args()
    if a.loop:
        n = now_tpe()
        if n.weekday() >= 5:
            print("週末，不抓"); return
        hh, mm = map(int, a.until.split(":"))
        if (n.hour, n.minute) >= (hh, mm):
            print("已過收盤抓取時間，不抓"); return
        loop(a.until, a.interval)
    else:
        s = snapshot()
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False)
        print(s["date"], s["time"], len(s["vol"]["data"]))


if __name__ == "__main__":
    sys.exit(main())
