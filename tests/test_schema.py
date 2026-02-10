from __future__ import annotations

import unittest

from taxgrok.schema import GuidanceParseError, parse_tax_guidance


class SchemaTests(unittest.TestCase):
    def test_parse_valid_json(self) -> None:
        raw = (
            '{"how_to_file":["Use Form 1040"],'
            '"what_to_file":["W-2"],'
            '"what_to_remember":["Check SSN"],'
            '"what_not_to_forget":["Direct deposit info"],'
            '"common_mistakes":["Math errors"],'
            '"rough_expectation_summary":"Likely small refund",'
            '"rough_expectation_drivers":["Withholding"],'
            '"confidence_level":"low",'
            '"missing_information":["1099"],'
            '"follow_up_questions":["Any side income?"],'
            '"assumptions":["Single filer"],'
            '"citation_notes":["file.md: line item"],'
            '"disclaimer":"Rough educational guidance only."}'
        )
        guidance = parse_tax_guidance(raw)
        self.assertEqual(guidance.how_to_file[0], "Use Form 1040")
        self.assertEqual(guidance.confidence_level, "low")

    def test_parse_raises_when_no_json(self) -> None:
        with self.assertRaises(GuidanceParseError):
            parse_tax_guidance("not json")


if __name__ == "__main__":
    unittest.main()
