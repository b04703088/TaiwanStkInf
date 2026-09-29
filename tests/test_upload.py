import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upload_firestore as uf  # noqa: E402

CSV = """date,market,code,name,open,high,low,close,change,volume,value,transactions
2026-09-24,TWSE,2330,台積電,1000.0,1010.0,995.0,1005.0,-5.0,25123456,25000000000,45678
2026-09-24,TWSE,00625K,富邦上証+R,,,,,0.00,0,0,0
2026-09-24,TPEx,6488,環球晶,403.0,405.0,399.0,400.5,-2.5,1234000,495000000,2345
"""


class FakeRef:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def collection(self, name):
        return FakeCol(self.store, f"{self.path}/{name}")

    def set(self, data):
        self.store[self.path] = data


class FakeCol:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def document(self, name):
        return FakeRef(self.store, f"{self.path}/{name}")


class FakeBatch:
    def __init__(self, store):
        self.store, self.pending = store, []

    def set(self, ref, data):
        self.pending.append((ref, data))

    def commit(self):
        for ref, data in self.pending:
            ref.set(data)
        self.pending = []


class FakeDB:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return FakeCol(self.store, name)

    def batch(self):
        return FakeBatch(self.store)


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self.tmp.name) / "20260924.csv"
        self.csv.write_text(CSV, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_rows_skips_no_close(self):
        rows = uf.read_rows(self.csv)
        self.assertEqual([r["code"] for r in rows], ["2330", "6488"])
        self.assertEqual(rows[0]["close"], 1005.0)
        self.assertEqual(rows[1]["market"], "TPEx")

    def test_upload_day_layout(self):
        db = FakeDB()
        n = uf.upload_day(db, uf.read_rows(self.csv))
        self.assertEqual(n, 3)
        self.assertEqual(db.store["stock_prices/2330/daily/2026-09-24"]["close"], 1005.0)
        snap = db.store["daily_snapshots/2026-09-24"]
        self.assertEqual(snap["count"], 2)
        self.assertIsInstance(snap["data"], str)  # 單一字串欄位，避免索引項爆量
        data = json.loads(snap["data"])
        by_code = {r[0]: dict(zip(data["columns"], r)) for r in data["rows"]}
        self.assertEqual(by_code["6488"]["close"], 400.5)
        self.assertEqual(by_code["2330"]["name"], "台積電")

    def test_max_files_keeps_latest(self):
        paths = []
        for d in ("20260922", "20260923", "20260924"):
            p = Path(self.tmp.name) / f"{d}.csv"
            p.write_text(CSV, encoding="utf-8")
            paths.append(str(p))
        lst = Path(self.tmp.name) / "list.txt"
        lst.write_text("\n".join(paths), encoding="utf-8")
        args = type("A", (), {"list": str(lst), "latest": None, "files": [], "max_files": 2})
        self.assertEqual([p.name for p in uf.pick_files(args)], ["20260923.csv", "20260924.csv"])

    def test_no_credentials_skips(self):
        import os
        env = {k: os.environ.pop(k) for k in ("FIREBASE_SERVICE_ACCOUNT",
                                              "GOOGLE_APPLICATION_CREDENTIALS") if k in os.environ}
        try:
            self.assertEqual(uf.main([str(self.csv)]), 0)
        finally:
            os.environ.update(env)


if __name__ == "__main__":
    unittest.main()
