"""PII-safe logging and local redaction utilities."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re

from .ingestion import ExtractedDocument, chunk_text


_PATTERN_DEFS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("ssn", re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b"), "[REDACTED_SSN]"),
    ("ein", re.compile(r"\b\d{2}-\d{7}\b"), "[REDACTED_EIN]"),
    (
        "email",
        re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "phone",
        re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
        "[REDACTED_PHONE]",
    ),
    (
        "account_number",
        re.compile(r"\b\d{8,17}\b"),
        "[REDACTED_ACCOUNT]",
    ),
)


@dataclass(frozen=True)
class RedactionResult:
    """Text redaction result."""

    text: str
    replacements: int


def redact_text(text: str) -> RedactionResult:
    """Redact common PII patterns from text."""
    total_replacements = 0
    redacted = text
    for _, pattern, replacement in _PATTERN_DEFS:
        redacted, count = pattern.subn(replacement, redacted)
        total_replacements += count
    return RedactionResult(text=redacted, replacements=total_replacements)


def _source_key_from_document(doc: ExtractedDocument) -> str:
    return doc.source_ref


def redact_document(doc: ExtractedDocument) -> tuple[ExtractedDocument, int]:
    """Return redacted document clone and replacement count."""
    result = redact_text(doc.text)
    if result.replacements == 0:
        return doc, 0

    source_key = _source_key_from_document(doc)
    redacted_chunks = chunk_text(result.text, source_key=source_key)
    redacted_notes = list(doc.extraction_notes)
    redacted_notes.append(f"Local redaction applied ({result.replacements} replacement(s)).")
    redacted_doc = ExtractedDocument(
        source_path=doc.source_path,
        source_kind=doc.source_kind,
        text=result.text,
        chunks=redacted_chunks,
        extraction_notes=redacted_notes,
        artifact_path=None,
    )
    return redacted_doc, result.replacements


class PIIRedactingLogFilter(logging.Filter):
    """Redact common PII patterns from log messages before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True

        result = redact_text(message)
        if result.replacements > 0:
            record.msg = result.text
            record.args = ()
        return True


def install_safe_logging_filter() -> None:
    """Install a PII redaction filter on root logger handlers."""
    root_logger = logging.getLogger()
    pii_filter = PIIRedactingLogFilter()
    for handler in root_logger.handlers:
        handler.addFilter(pii_filter)
