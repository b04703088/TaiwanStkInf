import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import insider_site as S  # noqa: E402


def _w(p, cols, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


class InsiderSiteTest(unittest.TestCase):
    def test_build(self):
        with tempfile.TemporaryDirectory() as d:
            ins = Path(d) / "insider"
            tcols = ["month", "market", "code", "company", "role", "name", "held_prev", "buy_mkt", "buy_other",
                     "sell_mkt", "sell_other", "held_now", "pledged", "note", "dup"]
            # 舊檔沒有 pledge_add / pledge_sub 欄 → 補 0
            _w(ins / "trades" / "202608.csv", tcols, [dict(zip(tcols, ["2026-08", "sii", "1101", "台泥", "董事", "甲",
                                                                         "10", "5", "0", "0", "0", "15", "0", "", ""]))])
            _w(ins / "trades" / "202609.csv", tcols + ["pledge_add", "pledge_sub"],
               [dict(zip(tcols + ["pledge_add", "pledge_sub"], ["2026-09", "otc", "1259", "安心", "董事", "乙", "10", "0",
                                                               "0", "3", "0", "7", "4", "", "", "4", "0"]))])
            _w(ins / "transfer" / "2026.csv", S.TRANSFER, [
                {"date": "2026-10-20", "code": "2313", "name": "吳", "method": "一般交易", "shares": "600000",
                 "period": "1151015~1151114"},
                {"date": "2026-01-01", "code": "1", "name": "old", "shares": "1"}])
            pcols = ["code", "company", "ds_held", "ds_padd", "ds_psub", "ds_pledged", "ds_ppct", "mgr_held",
                     "major_held", "mm_pledged", "mm_ppct"]
            _w(ins / "irb130" / "202609_sii.csv", pcols, [
                dict(zip(pcols, ["1110", "東南水泥", "1", "0", "0", "40", "21.47", "0", "0", "0", "0"])),   # 比例高
                dict(zip(pcols, ["1101", "臺灣水泥", "1", "0", "0", "4", "0.64", "0", "0", "0", "0"])),      # 沒變動、比例低 → 不留
                dict(zip(pcols, ["1295", "生合", "1", "300", "0", "300", "5.25", "0", "0", "0", "0"]))])
            out = S.build(d, today=date(2026, 10, 27))
        self.assertEqual(out["months"], ["2026-09", "2026-08"])
        tr = [dict(zip(out["trades"]["cols"], r)) for r in out["trades"]["rows"]]
        self.assertEqual([r["month"] for r in tr], ["2026-09", "2026-08"])
        self.assertEqual((tr[0]["pledge_add"], tr[1]["pledge_add"], tr[1]["buy_mkt"]), (4, 0, 5))
        pre = [dict(zip(out["transfer"]["cols"], r)) for r in out["transfer"]["rows"]]
        self.assertEqual(len(pre), 1)
        self.assertEqual(pre[0]["period"], "2026-10-15~2026-11-14")
        self.assertEqual(pre[0]["shares"], 600000)
        pl = [dict(zip(out["pledge"]["cols"], r)) for r in out["pledge"]["rows"]]
        self.assertEqual(sorted(r["code"] for r in pl), ["1110", "1295"])
        self.assertEqual(out["pmonths"], ["2026-09"])
        self.assertEqual({r["market"] for r in pl}, {"sii"})


if __name__ == "__main__":
    unittest.main()
