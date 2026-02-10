from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from taxgrok.ingestion import DocumentChunk, ExtractedDocument
from taxgrok.irs_sources import IRSSource
from taxgrok.pipeline import CleanupResult, UploadedArtifact
from taxgrok.report import write_phase3_report
from taxgrok.schema import TaxGuidance
from taxgrok.taxpayer import TaxpayerContext
from taxgrok.xai_client import GenerationResult


class ReportTests(unittest.TestCase):
    def test_write_phase3_report_structured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "doc.txt"
            source.write_text("hello", encoding="utf-8")
            doc = ExtractedDocument(
                source_path=source,
                source_kind="txt",
                text="hello world",
                chunks=[
                    DocumentChunk(
                        chunk_id="doc-abc-chunk-001",
                        start_char=0,
                        end_char=11,
                        preview="hello world",
                    )
                ],
            )
            report_path = write_phase3_report(
                username="tester",
                output_dir=root,
                extracted_documents=[doc],
                uploaded_artifacts=[
                    UploadedArtifact(
                        source_path=source,
                        artifact_path=root / "001-doc.md",
                        remote_file_id="file_1",
                    )
                ],
                generation=GenerationResult(
                    text='{"how_to_file":["Use Form 1040"]}',
                    citations=[{"source": "file_1"}],
                    sources_used=1,
                    raw_response={"id": "resp_1"},
                    api_path="/v1/responses",
                ),
                cleanup=CleanupResult(deleted_file_ids=["file_1"], delete_failures=[]),
                irs_sources=[
                    IRSSource(
                        name="Forms",
                        url="https://www.irs.gov/forms-instructions",
                        reviewed_at_utc="2026-02-10 00:00:00 UTC",
                    )
                ],
                guidance=TaxGuidance(
                    how_to_file=["Use Form 1040"],
                    what_to_file=["W-2"],
                    what_to_remember=["Check SSN"],
                    what_not_to_forget=["Direct deposit info"],
                    common_mistakes=["Typos"],
                    rough_expectation_summary="Rough small refund",
                    rough_expectation_drivers=["Withholding"],
                    confidence_level="low",
                    missing_information=["1099"],
                    follow_up_questions=["Any side income?"],
                    assumptions=["Single filer"],
                    citation_notes=["doc.txt: values"],
                    disclaimer="Rough guidance only.",
                ),
                warnings=[],
                model="grok-test",
                cleanup_enabled=True,
                taxpayer_context=TaxpayerContext(
                    display_name="Alex Rivera",
                    filing_status="head_of_household",
                ),
            )
            content = report_path.read_text(encoding="utf-8")

        self.assertIn("## How to file (federal)", content)
        self.assertIn("Use Form 1040", content)
        self.assertIn("## IRS source set", content)
        self.assertIn("Generation API: `/v1/responses`", content)
        self.assertIn("## Cleanup", content)
        self.assertNotIn(str(source), content)
        self.assertIn("- Source ref:", content)
        self.assertIn("## Taxpayer profile", content)
        self.assertIn("- Name: `Alex Rivera`", content)
        self.assertIn("- Filing status: `Head of household`", content)

    def test_write_phase3_report_unstructured_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source = root / "doc.txt"
            source.write_text("hello", encoding="utf-8")
            doc = ExtractedDocument(
                source_path=source,
                source_kind="txt",
                text="hello world",
                chunks=[],
            )
            report_path = write_phase3_report(
                username="tester",
                output_dir=root,
                extracted_documents=[doc],
                uploaded_artifacts=[],
                generation=GenerationResult(
                    text="raw output",
                    citations=[],
                    sources_used=None,
                    raw_response={},
                    api_path="/v1/chat/completions",
                ),
                cleanup=CleanupResult(deleted_file_ids=[], delete_failures=[]),
                irs_sources=[],
                guidance=None,
                warnings=["parse failed"],
                model="grok-test",
                cleanup_enabled=False,
            )
            content = report_path.read_text(encoding="utf-8")

        self.assertIn("## Model output (unstructured fallback)", content)
        self.assertIn("raw output", content)
        self.assertIn("parse failed", content)


if __name__ == "__main__":
    unittest.main()
