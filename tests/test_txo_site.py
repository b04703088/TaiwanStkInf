import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import txo_site as T  # noqa: E402
import fetch_futures as F  # noqa: E402

H = "exp,exp_date,strike,cp,close,settle,volume,oi\n"


def row(d, exp, k, cp, oi, vol=0, ed="20261118"):
    return [d, "TXO", exp, f"{k}.0000", "買權" if cp == "C" else "賣權", "-", "-", "-", "1", str(vol), "1", str(oi),
            "-", "-", "-", "-", "", "一般", "-", "-", ed]


class TxoTest(unittest.TestCase):
    def test_parse(self):
        rows = [row("2026/11/13", "202611", 44000, "C", 5), row("2026/11/13", "202611", 44100, "P", 0),
                row("2026/11/13", "202611W4", 43000, "P", 7, ed="20261125")]
        rows.append(rows[0][:17] + ["盤後"] + rows[0][18:])
        by = F.parse_txo(rows)
        self.assertEqual(len(by["2026-11-13"]), 2)              # oi＝0 且沒成交、盤後都略過
        r = by["2026-11-13"][1]
        self.assertEqual((r["exp"], r["exp_date"], r["strike"], r["cp"], r["oi"]), ("202611W4", "2026-11-25", "43000", "P", "7"))

    def test_max_pain(self):
        s = {100: [10, 0, 0, 0, None, None], 110: [0, 0, 0, 0, None, None], 120: [0, 10, 0, 0, None, None]}
        self.assertIn(T.max_pain(s), (100, 110, 120))
        s = {100: [0, 50, 0, 0, None, None], 110: [5, 5, 0, 0, None, None], 120: [50, 0, 0, 0, None, None]}
        self.assertEqual(T.max_pain(s), 110)

    def test_build(self):
        with tempfile.TemporaryDirectory() as t:
            fut = Path(t) / "futures"
            (fut / "txo" / "2026").mkdir(parents=True)
            (fut / "txo" / "2026" / "20261112.csv").write_text(H + "202611,2026-11-18,44000,C,1,1,0,10\n202611,2026-11-18,43000,P,1,1,0,20\n")
            (fut / "txo" / "2026" / "20261113.csv").write_text(H + "202611,2026-11-18,44000,C,1,1,3,15\n202611,2026-11-18,43000,P,1,1,0,12\n"
                                                              "202611W4,2026-11-25,44000,C,1,1,0,4\n")
            (fut / "tx.csv").write_text("date,contract,close,change,volume,settle,oi,oi_all\n2026-11-13,202611,43834,706,1,1,1,1\n")
            p = T.build(t)
        self.assertEqual(p["date"], "2026-11-13")
        m = p["exps"][0]
        self.assertEqual((m["exp"], m["top_c"][0], m["top_p"][0], m["oi_c_d"], m["oi_p_d"]), ("202611", [44000, 15], [43000, 12], 5, -8))
        self.assertEqual([x["exp"] for x in p["exps"]], ["202611", "202611W4", "ALL"])
        w = p["exps"][1]
        self.assertIsNone(w["strikes"][0][3])                    # 前一天沒有這個契約 → 增減不算
        self.assertEqual(p["exps"][2]["oi_c"], 19)
        self.assertEqual(p["hist"]["rows"][-1][2:5], ["202611", 44000, 43000])


if __name__ == "__main__":
    unittest.main()
