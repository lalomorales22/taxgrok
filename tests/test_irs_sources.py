from __future__ import annotations

import unittest

from taxgrok.irs_sources import CURATED_IRS_SOURCES, load_irs_sources


class IRSSourceTests(unittest.TestCase):
    def test_load_irs_sources_without_refresh(self) -> None:
        sources = load_irs_sources(refresh=False)
        self.assertEqual(len(sources), len(CURATED_IRS_SOURCES))
        self.assertTrue(all(source.reviewed_at_utc for source in sources))
        self.assertTrue(all(source.status_code is None for source in sources))


if __name__ == "__main__":
    unittest.main()
