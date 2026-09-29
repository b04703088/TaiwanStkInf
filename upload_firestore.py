"""把 data/ 的每日 CSV 寫進 Firestore。

Firestore 結構：
  stock_prices/{code}/daily/{YYYY-MM-DD}   每檔每日一筆
  daily_snapshots/{YYYY-MM-DD}             當日全市場一份（列表頁一次讀完）
  jobs/firestore_upload                    最後一次上傳狀態

用日期當 doc id，重複上傳只會覆蓋同一筆。

憑證：環境變數 FIREBASE_SERVICE_ACCOUNT（整份 service account JSON）
      或 GOOGLE_APPLICATION_CREDENTIALS（json 檔路徑）。都沒有就略過不報錯。

用法：
  python upload_firestore.py data/2026/20260929.csv       # 指定檔案
  python upload_firestore.py --list new_files.txt         # 檔案清單（workflow 用）
  python upload_firestore.py --latest 5                   # data/ 裡最新 5 天

一天約 2,000 筆寫入；Firestore 免費額度每天 20,000 次寫入，
所以預設一次最多上傳 --max-files 5 天（取最新的），回補大量歷史時請分批。
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
NUM_FIELDS = ("open", "high", "low", "close", "change", "volume", "value", "transactions")
SNAPSHOT_FIELDS = ("name", "market", "open", "high", "low", "close", "change", "volume", "value")
BATCH_SIZE = 400  # Firestore 單一 batch 上限 500


def _num(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def read_rows(path):
    """讀一天的 CSV；沒有收盤價（當日無成交）的列略過。"""
    rows = []
    with open(path, newline="", encoding="utf-8") as fp:
        for r in csv.DictReader(fp):
            row = {"date": r["date"], "market": r["market"],
                   "code": r["code"].strip(), "name": r["name"].strip()}
            for k in NUM_FIELDS:
                row[k] = _num(r.get(k))
            if row["close"] is not None:
                rows.append(row)
    return rows


def build_snapshot(rows):
    return {r["code"]: {k: r[k] for k in SNAPSHOT_FIELDS} for r in rows}


def upload_day(db, rows, server_ts=None):
    """寫入一天的資料，回傳寫入次數。"""
    if not rows:
        return 0
    d = rows[0]["date"]
    ops = 0
    batch = db.batch()
    for r in rows:
        ref = (db.collection("stock_prices").document(r["code"])
                 .collection("daily").document(r["date"]))
        batch.set(ref, r)
        ops += 1
        if ops % BATCH_SIZE == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    snap = build_snapshot(rows)
    db.collection("daily_snapshots").document(d).set(
        {"date": d, "count": len(snap), "prices": snap, "updated_at": server_ts})
    return ops + 1


def pick_files(args):
    if args.list:
        text = Path(args.list).read_text(encoding="utf-8") if Path(args.list).exists() else ""
        files = [Path(p.strip()) for p in text.splitlines() if p.strip().endswith(".csv")]
    elif args.latest:
        files = sorted(DATA_DIR.glob("*/*.csv"))[-args.latest:]
    else:
        files = [Path(p) for p in args.files]
    files = sorted({f for f in files if f.exists()}, key=lambda p: p.name)
    if len(files) > args.max_files:
        print(f"共 {len(files)} 個檔案，超過 --max-files {args.max_files}，只上傳最新的 {args.max_files} 個")
        files = files[-args.max_files:]
    return files


def init_firestore():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT", "").strip()
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not raw and not path:
        return None, None
    import firebase_admin
    from firebase_admin import credentials, firestore
    cred = credentials.Certificate(json.loads(raw) if raw else path)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    return firestore.client(), firestore.SERVER_TIMESTAMP


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="CSV 檔案路徑")
    ap.add_argument("--list", help="內含 CSV 路徑的清單檔（一行一個）")
    ap.add_argument("--latest", type=int, help="上傳 data/ 裡最新 N 天")
    ap.add_argument("--max-files", type=int, default=5, help="一次最多上傳幾天（預設 5）")
    args = ap.parse_args(argv)

    files = pick_files(args)
    if not files:
        print("沒有要上傳的檔案")
        return 0

    db, ts = init_firestore()
    if db is None:
        print("未設定 FIREBASE_SERVICE_ACCOUNT，略過 Firestore 上傳")
        return 0

    total, done = 0, []
    try:
        for f in files:
            rows = read_rows(f)
            n = upload_day(db, rows, ts)
            total += n
            done.append({"file": f.name, "rows": len(rows)})
            print(f"{f.name}: {len(rows)} 檔")
    except Exception as e:  # noqa: BLE001
        if "does not exist" in str(e) and "database" in str(e):
            print("錯誤：這個 Firebase 專案還沒建立 Firestore 資料庫。\n"
                  "請到 Firebase Console → Firestore Database → 建立資料庫，"
                  "資料庫 ID 保持 (default)，位置選 asia-east1（台灣）。", file=sys.stderr)
            return 1
        raise
    db.collection("jobs").document("firestore_upload").set(
        {"files": done, "writes": total, "updated_at": ts})
    print(f"完成，共 {total} 次寫入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
