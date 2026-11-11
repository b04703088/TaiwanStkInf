import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import conc_site  # noqa: E402


def wcsv(p, head, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        w.writerow(head)
        w.writerows(rows)


class ConcTest(unittest.TestCase):
    def test_conc_top15(self):
        nets = {f"b{i}": 10 for i in range(20)} | {f"s{i}": -1 for i in range(200)}
        self.assertEqual(conc_site.conc(nets, 1000), (13.5, 135))
        self.assertEqual(conc_site.counts(nets), (20, 200, -180))

    def test_build_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            PH = ["date", "market", "code", "name", "close", "change", "volume", "value"]
            BH = ["date", "code", "side", "rank", "bid", "broker", "buy", "sell", "net", "pct"]
            wcsv(d / "2026" / "20261106.csv", PH, [["2026-11-06", "TWSE", "2330", "台積電", 90, 0, 100000, 1]])
            for day, close, nets in (("20261107", 100, {"A": 50, "B": -20}), ("20261110", 110, {"A": 30, "C": -40})):
                wcsv(d / "2026" / f"{day}.csv", PH, [[day, "TWSE", "2330", "台積電", close, 10, 1000000, 1]])
                wcsv(d / "broker" / "2026" / f"{day}.csv", BH,
                     [[day, "2330", "B" if v > 0 else "S", 1, k, k, max(v, 0), max(-v, 0), v, 1] for k, v in nets.items()])
            out = conc_site.build(d)
            r = dict(zip(out["cols"], out["rows"][0]))
            self.assertEqual((r["t1"], r["c1"]), (-10, -1.0))
            # 2 日：A +80、B −20、C −40 → 20 張 ÷ 2000 張
            self.assertEqual((r["t5"], r["c5"]), (20, 1.0))
            self.assertEqual(r["r5"], 22.22)
            self.assertIsNone(r["d5"])
            self.assertFalse(out["has_count"])
            self.assertEqual(out["hist"]["2330"][0], [3.0, -1.0])


if __name__ == "__main__":
    unittest.main()
