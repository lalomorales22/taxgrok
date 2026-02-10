from __future__ import annotations

import unittest

from taxgrok.irs_sources import IRSSource
from taxgrok.prompts import build_tax_system_prompt, build_tax_user_prompt
from taxgrok.taxpayer import TaxpayerContext


class PromptTests(unittest.TestCase):
    def test_build_tax_system_prompt_includes_scope_and_sources(self) -> None:
        sources = [
            IRSSource(
                name="Forms",
                url="https://www.irs.gov/forms-instructions",
                reviewed_at_utc="2026-02-10 00:00:00 UTC",
            )
        ]
        prompt = build_tax_system_prompt(irs_sources=sources, username="alice")
        self.assertIn("federal taxes only", prompt)
        self.assertIn("Target user id: alice", prompt)
        self.assertIn("https://www.irs.gov/forms-instructions", prompt)

    def test_build_tax_system_prompt_includes_taxpayer_context(self) -> None:
        prompt = build_tax_system_prompt(
            irs_sources=[],
            username="alice",
            taxpayer_context=TaxpayerContext(
                display_name="Alice Example",
                filing_status="married_filing_jointly",
            ),
        )
        self.assertIn("Declared taxpayer name: Alice Example", prompt)
        self.assertIn("Declared filing status: Married filing jointly", prompt)

    def test_build_tax_user_prompt_includes_json_shape(self) -> None:
        prompt = build_tax_user_prompt()
        self.assertIn('"how_to_file"', prompt)
        self.assertIn('"what_to_file"', prompt)
        self.assertIn('"disclaimer"', prompt)
        self.assertIn("return ONLY valid JSON", prompt)


if __name__ == "__main__":
    unittest.main()
