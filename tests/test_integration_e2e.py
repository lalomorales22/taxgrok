from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from taxgrok.config import RuntimeConfig
from taxgrok.pipeline import run_phase3_pipeline
from taxgrok.report import write_phase3_report
from taxgrok.xai_client import XAIClient


class EndToEndIntegrationTests(unittest.TestCase):
    def test_pipeline_with_mocked_xai_http(self) -> None:
        upload_counter = {"value": 0}
        deleted_ids: list[str] = []

        def fake_upload(
            self: XAIClient,
            *,
            path: str,
            file_path: Path,
            purpose: str | None,
        ) -> dict[str, object]:
            upload_counter["value"] += 1
            return {"id": f"file_mock_{upload_counter['value']}"}

        def fake_request_json(
            self: XAIClient,
            *,
            method: str,
            path: str,
            payload: dict[str, object] | None = None,
        ) -> dict[str, object]:
            if method.upper() == "POST" and path == "/v1/responses":
                return {
                    "output_text": (
                        '{"how_to_file":["Use Form 1040"],'
                        '"what_to_file":["W-2"],'
                        '"what_to_remember":["Check SSN"],'
                        '"what_not_to_forget":["Direct deposit info"],'
                        '"common_mistakes":["Typos"],'
                        '"rough_expectation_summary":"Potential small refund.",'
                        '"rough_expectation_drivers":["Withholding"],'
                        '"confidence_level":"low",'
                        '"missing_information":["1099 details"],'
                        '"follow_up_questions":["Any side income?"],'
                        '"assumptions":["Single filer"],'
                        '"citation_notes":["001-info.md: source"],'
                        '"disclaimer":"Rough educational guidance only."}'
                    ),
                    "usage": {"sources_used": 1},
                    "citations": [{"source": "file_mock_1"}],
                }
            if method.upper() == "DELETE" and path.startswith("/v1/files/"):
                file_id = path.rsplit("/", 1)[-1]
                deleted_ids.append(file_id)
                return {"id": file_id, "deleted": True}
            raise AssertionError(f"Unexpected request {method} {path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            info_file = root / "info.txt"
            info_file.write_text("Wages and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=True,
                refresh_irs_sources=False,
                local_redaction=True,
                verbose=False,
            )

            client = XAIClient(api_key="test-key", timeout_seconds=1)
            with mock.patch.object(XAIClient, "_upload_multipart", new=fake_upload), mock.patch.object(
                XAIClient, "_request_json", new=fake_request_json
            ):
                result = run_phase3_pipeline(
                    config=config,
                    queued_files=[info_file],
                    report_writer=write_phase3_report,
                    client=client,
                )

            content = result.report_path.read_text(encoding="utf-8")

        self.assertEqual(upload_counter["value"], 1)
        self.assertEqual(deleted_ids, ["file_mock_1"])
        self.assertEqual(result.generation.api_path, "/v1/responses")
        self.assertIsNotNone(result.guidance)
        self.assertIn("## How to file (federal)", content)
        self.assertIn("Use Form 1040", content)


if __name__ == "__main__":
    unittest.main()
