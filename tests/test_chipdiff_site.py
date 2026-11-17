import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import chipdiff_site as cd  # noqa: E402


class TestChipdiff(unittest.TestCase):
    def test_pct(self):
        hist = list(range(1, 101))
        self.assertEqual(cd._pct(hist, 100), 100)
        self.assertEqual(cd._pct(hist, 1), 1)
        self.assertEqual(cd._pct(hist, 50), 50)
        self.assertIsNone(cd._pct(list(range(10)), 5))  # 不到 MIN_N 天不算
        self.assertIsNone(cd._pct(hist, None))

    def test_chg(self):
        self.assertEqual(cd._chg(110, 100), 10.0)
        self.assertIsNone(cd._chg(1, 0))
        self.assertIsNone(cd._chg(None, 5))


if __name__ == "__main__":
    unittest.main()
