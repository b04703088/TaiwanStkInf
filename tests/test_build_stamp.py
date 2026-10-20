import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_site as B  # noqa: E402


class StampTest(unittest.TestCase):
    def test_every_page_has_taipei_time(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for f in (ROOT / "site").glob("*.html"):
                (out / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
            n = B.stamp_built(out, datetime(2026, 10, 20, 12, 3, tzinfo=timezone.utc))
            self.assertEqual(n, len(list(out.glob("*.html"))))
            s = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("更新 10/20 20:03", s)
            self.assertEqual(s.count('class="built-at"'), 1)


if __name__ == "__main__":
    unittest.main()
