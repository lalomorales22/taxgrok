from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

from taxgrok.config import RuntimeConfig
from taxgrok.pipeline import run_phase3_pipeline
from taxgrok.report import write_phase3_report
from taxgrok.xai_client import GenerationResult, UploadedRemoteFile


@dataclass
class FakeXAIClient:
    uploaded_ids: list[str]
    deleted_ids: list[str]

    def analyze_png(self, *, png_path: Path, model: str) -> str:
        return f"extracted image text from {png_path.name} using {model}"

    def upload_file(self, file_path: Path, *, purpose: str = "assistants") -> UploadedRemoteFile:
        uploads = getattr(self, "uploaded_filenames", [])
        uploads.append(file_path.name)
        setattr(self, "uploaded_filenames", uploads)
        file_id = f"file-{len(self.uploaded_ids) + 1}"
        self.uploaded_ids.append(file_id)
        return UploadedRemoteFile(
            file_id=file_id,
            filename=file_path.name,
            bytes_uploaded=file_path.stat().st_size,
        )

    def extract_pdf_text(self, *, pdf_path: Path, model: str) -> str:
        return ""

    def chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        return GenerationResult(
            text="phase2 summary",
            citations=[{"source": "artifact-1"}],
            sources_used=len(attached_file_ids or []),
            raw_response={"choices": []},
            api_path="/v1/chat/completions",
        )

    def responses_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        return GenerationResult(
            text=(
                '{"how_to_file":["Use Form 1040"],'
                '"what_to_file":["W-2"],'
                '"what_to_remember":["Double-check SSN"],'
                '"what_not_to_forget":["Bank routing/account for direct deposit"],'
                '"common_mistakes":["Typos in SSN"],'
                '"rough_expectation_summary":"Possible small refund based on withholding.",'
                '"rough_expectation_drivers":["Withholding vs tax liability"],'
                '"confidence_level":"low",'
                '"missing_information":["1099 details"],'
                '"follow_up_questions":["Any additional income?"],'
                '"assumptions":["Single filer"],'
                '"citation_notes":["001-info.md: income notes"],'
                '"disclaimer":"Rough educational guidance only."}'
            ),
            citations=[{"source": "artifact-1"}],
            sources_used=len(attached_file_ids or []),
            raw_response={"id": "resp_1"},
            api_path="/v1/responses",
        )

    def delete_file(self, file_id: str) -> None:
        self.deleted_ids.append(file_id)


class FallbackFakeXAIClient(FakeXAIClient):
    def responses_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        raise RuntimeError("responses unavailable in test")


@dataclass
class UploadBlockedFakeXAIClient(FakeXAIClient):
    last_attached_file_ids: list[str] | None = None
    last_user_prompt: str = ""

    def upload_file(self, file_path: Path, *, purpose: str = "assistants") -> UploadedRemoteFile:
        raise RuntimeError("POST /v1/files failed (403): error code: 1010")

    def chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        self.last_attached_file_ids = attached_file_ids
        self.last_user_prompt = user_prompt
        return GenerationResult(
            text=(
                '{"how_to_file":["Use Form 1040"],'
                '"what_to_file":["W-2"],'
                '"what_to_remember":["Review all withholding entries"],'
                '"what_not_to_forget":["Direct deposit routing/account"],'
                '"common_mistakes":["Forgetting supplemental income forms"],'
                '"rough_expectation_summary":"Possible balance due or refund depending on final withholding.",'
                '"rough_expectation_drivers":["Withholding vs final liability"],'
                '"confidence_level":"low",'
                '"missing_information":["Exact wage and withholding values"],'
                '"follow_up_questions":["Did you receive additional 1099 income?"],'
                '"assumptions":["Federal filing only"],'
                '"citation_notes":["Local extracted context used"],'
                '"disclaimer":"Rough educational guidance only."}'
            ),
            citations=[],
            sources_used=0,
            raw_response={"id": "chat_local_mode"},
            api_path="/v1/chat/completions",
        )


@dataclass
class FullyDeniedFakeXAIClient(UploadBlockedFakeXAIClient):
    def chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        raise RuntimeError("POST /v1/chat/completions failed (403): error code: 1010")

    def responses_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        raise RuntimeError("POST /v1/responses failed (403): error code: 1010")


@dataclass
class EmptyGenerationFakeXAIClient(FakeXAIClient):
    def responses_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        return GenerationResult(
            text="",
            citations=[],
            sources_used=0,
            raw_response={"id": "resp_empty"},
            api_path="/v1/responses",
        )


@dataclass
class PdfOcrFallbackFakeXAIClient(FakeXAIClient):
    ocr_text: str = ""

    def extract_pdf_text(self, *, pdf_path: Path, model: str) -> str:
        return self.ocr_text


class Phase2PipelineTests(unittest.TestCase):
    def test_pipeline_cleans_up_remote_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            png = root / "w2.png"
            txt.write_text("income and withholding details", encoding="utf-8")
            png.write_bytes(b"\x89PNG\r\n\x1a\n")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=True,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = FakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt, png],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

            report_content = result.report_path.read_text(encoding="utf-8")

        self.assertEqual(len(result.uploaded_artifacts), 2)
        self.assertEqual(len(result.cleanup.deleted_file_ids), 2)
        self.assertEqual(client.deleted_ids, result.cleanup.deleted_file_ids)
        self.assertIn("## Source and chunk index", report_content)
        self.assertIn("## How to file (federal)", report_content)
        self.assertIn("Use Form 1040", report_content)

    def test_pipeline_can_skip_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            txt.write_text("income and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=False,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = FakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        self.assertEqual(len(result.uploaded_artifacts), 1)
        self.assertEqual(result.cleanup.deleted_file_ids, [])
        self.assertEqual(client.deleted_ids, [])

    def test_pipeline_falls_back_to_chat_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            txt.write_text("income and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=False,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = FallbackFakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        self.assertEqual(result.generation.api_path, "/v1/chat/completions")
        self.assertTrue(any("Responses API failed" in warning for warning in result.warnings))

    def test_pipeline_uses_local_context_when_uploads_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            txt.write_text("income and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=True,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = UploadBlockedFakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        self.assertEqual(result.generation.api_path, "/v1/chat/completions")
        self.assertEqual(len(result.uploaded_artifacts), 0)
        self.assertEqual(result.cleanup.deleted_file_ids, [])
        self.assertEqual(client.last_attached_file_ids, [])
        self.assertIn("No remote xAI files were attached for this run.", client.last_user_prompt)
        self.assertTrue(
            any("Files API permission/access issue detected" in warning for warning in result.warnings)
        )

    def test_pipeline_uses_local_heuristic_when_generation_endpoints_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            txt.write_text("income and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=True,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = FullyDeniedFakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        self.assertEqual(result.generation.api_path, "/local/fallback")
        self.assertIsNotNone(result.guidance)
        self.assertTrue(
            any(
                "xAI generation endpoint access appears denied" in warning
                for warning in result.warnings
            )
        )

    def test_pipeline_uses_local_heuristic_when_generation_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            txt = root / "info.txt"
            txt.write_text("income and withholding details", encoding="utf-8")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=False,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = EmptyGenerationFakeXAIClient(uploaded_ids=[], deleted_ids=[])
            result = run_phase3_pipeline(
                config=config,
                queued_files=[txt],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        self.assertEqual(result.generation.api_path, "/local/fallback")
        self.assertIsNotNone(result.guidance)
        self.assertTrue(
            any("Generation returned empty text" in warning for warning in result.warnings)
        )

    def test_pipeline_uses_pdf_ocr_fallback_text_in_artifact_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf = root / "scan.pdf"
            pdf.write_bytes(b"%PDF-1.3\nthis is not a valid text PDF payload\n%%EOF")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=False,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = PdfOcrFallbackFakeXAIClient(
                uploaded_ids=[],
                deleted_ids=[],
                ocr_text=(
                    "Form 1099-NEC\n"
                    "PAYER: Example LLC\n"
                    "RECIPIENT: Test User\n"
                    "NONEMPLOYEE COMPENSATION: 12500.00\n"
                    "FEDERAL INCOME TAX WITHHELD: 0.00\n"
                    "STATE TAX WITHHELD: 0.00\n"
                    "PAYER FEDERAL ID NUMBER: 12-3456789\n"
                ),
            )
            result = run_phase3_pipeline(
                config=config,
                queued_files=[pdf],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        uploaded_names = getattr(client, "uploaded_filenames", [])
        self.assertEqual(len(result.uploaded_artifacts), 1)
        self.assertEqual(uploaded_names, ["001-scan.md"])
        self.assertTrue(any("PDF OCR fallback applied." in warning for warning in result.warnings))

    def test_pipeline_uploads_original_pdf_when_ocr_fallback_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pdf = root / "scan.pdf"
            pdf.write_bytes(b"%PDF-1.3\nthis is not a valid text PDF payload\n%%EOF")

            config = RuntimeConfig(
                xai_api_key="test-key",
                username="tester",
                output_dir=root,
                model="grok-test",
                timeout_seconds=10,
                cleanup_remote_files=False,
                refresh_irs_sources=False,
                local_redaction=False,
                verbose=False,
            )
            client = PdfOcrFallbackFakeXAIClient(uploaded_ids=[], deleted_ids=[], ocr_text="")
            result = run_phase3_pipeline(
                config=config,
                queued_files=[pdf],
                report_writer=write_phase3_report,
                client=client,  # type: ignore[arg-type]
            )

        uploaded_names = getattr(client, "uploaded_filenames", [])
        self.assertEqual(len(result.uploaded_artifacts), 1)
        self.assertEqual(uploaded_names, ["scan.pdf"])
        self.assertEqual(result.uploaded_artifacts[0].upload_kind, "source-pdf")
        self.assertTrue(
            any("uploading original PDF for retrieval" in warning for warning in result.warnings)
        )


if __name__ == "__main__":
    unittest.main()
