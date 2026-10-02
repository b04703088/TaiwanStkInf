import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fetch_msci as M  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


class MsciTest(unittest.TestCase):
    def test_parse_taiwan_section(self):
        ann, close, adds, dels = M.parse_list_pdf((FIX / "msci_aug26_st.pdf").read_bytes())
        self.assertEqual((ann, close), (date(2026, 8, 12), date(2026, 8, 31)))
        self.assertIn("NANYA TECHNOLOGY", adds)
        self.assertIn("TAIWAN CEMENT CORP", dels)
        self.assertEqual((len(adds), len(dels)), (6, 6))
        self.assertEqual(M.next_weekday(close), date(2026, 9, 1))

    def test_name_mapping(self):
        cos = [{"code": "1101", "name": "台泥", "abbr": "TCC", "web": "tccgroupholdings", "mail": "taiwancement"},
               {"code": "2408", "name": "南亞科", "abbr": "NTC", "web": "nanya", "mail": "ntc"},
               {"code": "8046", "name": "南電", "abbr": "N.P.C", "web": "nanyapcb", "mail": "nanyapcb"},
               {"code": "8299", "name": "群聯", "abbr": "Phison", "web": "phison", "mail": "phison"}]
        self.assertEqual(M.map_name("TAIWAN CEMENT CORP", cos, {}), "1101")
        self.assertEqual(M.map_name("PHISON ELECTRONICS CORP", cos, {}), "8299")
        self.assertEqual(M.map_name("NAN YA PRINTED CIRCUIT", cos, {"NAN YA PRINTED CIRCUIT": "8046"}), "8046")
        self.assertEqual(M.map_name("SOMETHING UNKNOWN", cos, {}), "")

    def test_ir_dates(self):
        t = 'Quarter|Event|Announcement Date|Effective Date,,,\n"Nov, 2026|""Index Review""|11-11-2026|12-01-2026",,,'
        self.assertEqual(M.parse_ir_dates(t), [{"review": "2026-11", "announce_date": "2026-11-11", "effective_date": "2026-12-01"}])


if __name__ == "__main__":
    unittest.main()
