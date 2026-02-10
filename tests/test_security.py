from __future__ import annotations

from pathlib import Path
import logging
import unittest

from taxgrok.ingestion import DocumentChunk, ExtractedDocument
from taxgrok.security import PIIRedactingLogFilter, redact_document, redact_text


class SecurityTests(unittest.TestCase):
    def test_redact_text_masks_common_pii(self) -> None:
        raw = (
            "SSN 123-45-6789 email john@example.com "
            "phone 415-555-1212 ein 12-3456789 acct 123456789012"
        )
        result = redact_text(raw)
        self.assertGreaterEqual(result.replacements, 5)
        self.assertNotIn("123-45-6789", result.text)
        self.assertIn("[REDACTED_SSN]", result.text)
        self.assertIn("[REDACTED_EMAIL]", result.text)

    def test_redact_document_rechunks_and_notes(self) -> None:
        doc = ExtractedDocument(
            source_path=Path("sample.txt"),
            source_kind="txt",
            text="taxpayer ssn 123-45-6789",
            chunks=[
                DocumentChunk(
                    chunk_id="sample-abc-chunk-001",
                    start_char=0,
                    end_char=24,
                    preview="taxpayer ssn 123-45-6789",
                )
            ],
        )
        redacted_doc, replacements = redact_document(doc)
        self.assertGreater(replacements, 0)
        self.assertIn("[REDACTED_SSN]", redacted_doc.text)
        self.assertTrue(any("Local redaction applied" in note for note in redacted_doc.extraction_notes))
        self.assertGreaterEqual(len(redacted_doc.chunks), 1)

    def test_logging_filter_redacts_message(self) -> None:
        filt = PIIRedactingLogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ssn 123-45-6789",
            args=(),
            exc_info=None,
        )
        keep = filt.filter(record)
        self.assertTrue(keep)
        self.assertIn("[REDACTED_SSN]", str(record.msg))


if __name__ == "__main__":
    unittest.main()
