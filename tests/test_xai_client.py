from __future__ import annotations

import unittest
from unittest import mock

from taxgrok.xai_client import XAIClient


class XAIClientTests(unittest.TestCase):
    def test_responses_payload_does_not_include_file_search_tool_without_vector_store(self) -> None:
        client = XAIClient(api_key="test-key", timeout_seconds=1)

        def fake_request_json(
            xai_client: XAIClient,
            *,
            method: str,
            path: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/v1/responses")
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertNotIn("tools", payload)
            self.assertNotIn("tool_choice", payload)
            return {
                "output_text": '{"how_to_file":["Use Form 1040"],"what_to_file":["W-2"],'
                '"what_to_remember":["Check entries"],"what_not_to_forget":["Direct deposit details"],'
                '"common_mistakes":["Typos"],"rough_expectation_summary":"Rough expectation only.",'
                '"rough_expectation_drivers":["Withholding"],"confidence_level":"low",'
                '"missing_information":["Additional forms"],"follow_up_questions":["Any side income?"],'
                '"assumptions":["Federal only"],"citation_notes":["local"],'
                '"disclaimer":"Rough educational guidance only."}'
            }

        with mock.patch.object(XAIClient, "_request_json", new=fake_request_json):
            result = client.responses_completion(
                model="grok-test",
                system_prompt="system",
                user_prompt="user",
                attached_file_ids=["file_123"],
            )
        self.assertEqual(result.api_path, "/v1/responses")
        self.assertTrue(result.text)


if __name__ == "__main__":
    unittest.main()
