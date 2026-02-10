from __future__ import annotations

import unittest

from taxgrok.taxpayer import filing_status_label, parse_filing_status


class TaxpayerTests(unittest.TestCase):
    def test_parse_filing_status_aliases(self) -> None:
        self.assertEqual(parse_filing_status("single"), "single")
        self.assertEqual(parse_filing_status("mfj"), "married_filing_jointly")
        self.assertEqual(parse_filing_status("head of household"), "head_of_household")
        self.assertEqual(parse_filing_status("widow"), "qualifying_surviving_spouse")
        self.assertEqual(parse_filing_status("not sure"), "unknown")
        self.assertIsNone(parse_filing_status("totally invalid option"))

    def test_filing_status_label(self) -> None:
        self.assertEqual(filing_status_label("single"), "Single")
        self.assertEqual(filing_status_label("married_filing_jointly"), "Married filing jointly")
        self.assertEqual(filing_status_label("unknown-code"), "Not sure yet")


if __name__ == "__main__":
    unittest.main()
