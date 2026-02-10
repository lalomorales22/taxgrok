"""Local ingestion adapters and chunk metadata for phase 2."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Iterable


@dataclass(frozen=True)
class DocumentChunk:
    """Chunk metadata for source/citation tracking."""

    chunk_id: str
    start_char: int
    end_char: int
    preview: str


@dataclass
class ExtractedDocument:
    """Normalized text document produced from one source file."""

    source_path: Path
    source_kind: str
    text: str
    chunks: list[DocumentChunk]
    extraction_notes: list[str] = field(default_factory=list)
    artifact_path: Path | None = None

    @property
    def source_name(self) -> str:
        return self.source_path.name

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def source_ref(self) -> str:
        """Stable source identifier used in artifacts/reports without local path exposure."""
        if self.chunks:
            first_id = self.chunks[0].chunk_id
            match = re.match(r"(.+)-chunk-\d+$", first_id)
            if match:
                return match.group(1)
        return make_source_key(self.source_path)


def _preview(text: str, *, max_len: int = 120) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def chunk_text(
    text: str,
    *,
    source_key: str,
    chunk_size: int = 1400,
    overlap: int = 200,
) -> list[DocumentChunk]:
    """Split text into overlapping chunks and track boundaries."""
    cleaned = text.strip()
    if not cleaned:
        return []

    safe_overlap = max(0, min(overlap, chunk_size - 1))
    step = chunk_size - safe_overlap
    chunks: list[DocumentChunk] = []
    start = 0
    index = 1
    while start < len(cleaned):
        end = min(len(cleaned), start + chunk_size)
        piece = cleaned[start:end]
        chunk_id = f"{source_key}-chunk-{index:03d}"
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                start_char=start,
                end_char=end,
                preview=_preview(piece),
            )
        )
        if end == len(cleaned):
            break
        start += step
        index += 1
    return chunks


def make_source_key(path: Path) -> str:
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower() or "source"
    return f"{stem}-{digest}"


def _extract_pdf_text(path: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return "", ["pypdf is not installed; local PDF text extraction skipped."]

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return "", [f"Unable to parse PDF locally: {exc}"]

    parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            page_text = (page.extract_text() or "").strip()
        except Exception as exc:
            notes.append(f"Page {index} extraction failed: {exc}")
            continue
        if page_text:
            parts.append(page_text)

    if not parts:
        notes.append("No extractable text found in PDF pages.")
    return "\n\n".join(parts), notes


def extract_local_document(path: Path) -> ExtractedDocument:
    """Extract local text from txt/md/pdf sources."""
    extension = path.suffix.lower()
    notes: list[str] = []

    if extension in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        source_kind = extension.lstrip(".")
    elif extension == ".pdf":
        text, notes = _extract_pdf_text(path)
        source_kind = "pdf"
        if not text:
            text = (
                "Local PDF extraction was incomplete. This source will still be uploaded for server-side "
                "retrieval during analysis."
            )
    else:
        raise ValueError(f"Unsupported local extraction extension: {extension}")

    source_key = make_source_key(path)
    chunks = chunk_text(text, source_key=source_key)
    return ExtractedDocument(
        source_path=path,
        source_kind=source_kind,
        text=text,
        chunks=chunks,
        extraction_notes=notes,
    )


def build_image_document(path: Path, extracted_text: str) -> ExtractedDocument:
    """Create normalized text document from image analysis output."""
    normalized = extracted_text.strip()
    if not normalized:
        normalized = "No text content was extracted from this image."
    source_key = make_source_key(path)
    chunks = chunk_text(normalized, source_key=source_key)
    return ExtractedDocument(
        source_path=path,
        source_kind="png",
        text=normalized,
        chunks=chunks,
        extraction_notes=[],
    )


def replace_document_text(
    doc: ExtractedDocument,
    updated_text: str,
    *,
    note: str | None = None,
) -> ExtractedDocument:
    """Return a cloned document with re-chunked text and optional extraction note."""
    normalized = updated_text.strip()
    if not normalized:
        normalized = doc.text
    source_key = make_source_key(doc.source_path)
    chunks = chunk_text(normalized, source_key=source_key)
    notes = list(doc.extraction_notes)
    if note:
        notes.append(note)
    return ExtractedDocument(
        source_path=doc.source_path,
        source_kind=doc.source_kind,
        text=normalized,
        chunks=chunks,
        extraction_notes=notes,
        artifact_path=None,
    )


def write_artifact(doc: ExtractedDocument, artifact_dir: Path, index: int) -> Path:
    """Write normalized markdown artifact for remote retrieval."""
    artifact_name = (
        f"{index:03d}-{re.sub(r'[^A-Za-z0-9._-]+', '-', doc.source_path.stem).strip('-') or 'source'}.md"
    )
    artifact_path = artifact_dir / artifact_name

    lines = [
        f"# Source: {doc.source_name}",
        "",
        f"- Source file: `{doc.source_name}`",
        f"- Source ref: `{doc.source_ref}`",
        f"- Source type: `{doc.source_kind}`",
        f"- Character count: `{doc.char_count}`",
        f"- Chunk count: `{len(doc.chunks)}`",
    ]
    if doc.extraction_notes:
        lines.append("- Extraction notes:")
        lines.extend([f"  - {note}" for note in doc.extraction_notes])

    lines.extend(
        [
            "",
            "## Normalized text",
            doc.text.strip() or "(empty)",
            "",
            "## Chunk index",
        ]
    )
    if doc.chunks:
        for chunk in doc.chunks:
            lines.append(
                f"- `{chunk.chunk_id}` chars `{chunk.start_char}:{chunk.end_char}` preview: {chunk.preview}"
            )
    else:
        lines.append("- No chunks generated.")

    artifact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    doc.artifact_path = artifact_path
    return artifact_path


def summarize_extraction(docs: Iterable[ExtractedDocument]) -> dict[str, int]:
    """Compute simple extraction totals for report metadata."""
    total_docs = 0
    total_chars = 0
    total_chunks = 0
    for doc in docs:
        total_docs += 1
        total_chars += doc.char_count
        total_chunks += len(doc.chunks)
    return {
        "documents": total_docs,
        "characters": total_chars,
        "chunks": total_chunks,
    }
