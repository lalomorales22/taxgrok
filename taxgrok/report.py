"""Phase-3 report writer helpers for taxgrok."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .ingestion import ExtractedDocument, summarize_extraction
from .irs_sources import IRSSource
from .pipeline import CleanupResult, UploadedArtifact
from .schema import TaxGuidance
from .taxpayer import TaxpayerContext, filing_status_label
from .xai_client import GenerationResult


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _append_list(lines: list[str], heading: str, items: list[str]) -> None:
    lines.append(heading)
    if items:
        lines.extend([f"- {item}" for item in items])
    else:
        lines.append("- Unknown from provided documents.")
    lines.append("")


def write_phase3_report(
    *,
    username: str,
    output_dir: Path,
    extracted_documents: list[ExtractedDocument],
    uploaded_artifacts: list[UploadedArtifact],
    generation: GenerationResult,
    cleanup: CleanupResult,
    irs_sources: list[IRSSource],
    guidance: TaxGuidance | None,
    warnings: list[str],
    model: str,
    cleanup_enabled: bool,
    taxpayer_context: TaxpayerContext | None = None,
) -> Path:
    """Write final phase-3 markdown output."""
    report_path = output_dir / f"TAXGROK-{username}.md"
    totals = summarize_extraction(extracted_documents)
    report_name = taxpayer_context.display_name if taxpayer_context is not None else username

    source_to_remote: dict[str, list[str]] = {}
    source_to_upload_kinds: dict[str, list[str]] = {}
    for uploaded in uploaded_artifacts:
        key = str(uploaded.source_path)
        source_to_remote.setdefault(key, []).append(uploaded.remote_file_id)
        source_to_upload_kinds.setdefault(key, []).append(uploaded.upload_kind)

    lines = [
        f"# TAXGROK report for {report_name}",
        "",
        f"Generated: {_timestamp_utc()}",
        f"Model: `{model}`",
        f"Generation API: `{generation.api_path}`",
        "",
    ]

    if taxpayer_context is not None:
        lines.extend(
            [
                "## Taxpayer profile",
                f"- Name: `{taxpayer_context.display_name}`",
                f"- Filing status: `{filing_status_label(taxpayer_context.filing_status)}`",
                "",
            ]
        )

    if guidance is not None:
        _append_list(lines, "## How to file (federal)", guidance.how_to_file)
        _append_list(lines, "## What to file", guidance.what_to_file)
        _append_list(lines, "## What to remember", guidance.what_to_remember)
        _append_list(lines, "## What not to forget", guidance.what_not_to_forget)
        _append_list(lines, "## Common mistakes", guidance.common_mistakes)

        lines.append("## Rough payment/refund expectation")
        lines.append(f"- Summary: {guidance.rough_expectation_summary}")
        lines.append(f"- Confidence: `{guidance.confidence_level}`")
        if guidance.rough_expectation_drivers:
            lines.append("- Drivers:")
            lines.extend([f"  - {driver}" for driver in guidance.rough_expectation_drivers])
        else:
            lines.append("- Drivers: unknown from provided documents.")
        lines.append("")

        _append_list(lines, "## Missing information before filing", guidance.missing_information)
        
        lines.append("## Estimated 2025 Refund / Owed")
        lines.append(f"{guidance.estimated_2025_refund_or_owed}")
        lines.append("")
        
        _append_list(lines, "## Assumptions used", guidance.assumptions)
        _append_list(lines, "## Citation notes", guidance.citation_notes)
        disclaimer = guidance.disclaimer
    else:
        lines.extend(
            [
                "## Model output (unstructured fallback)",
                generation.text.strip() or "(No text returned by model.)",
                "",
            ]
        )
        disclaimer = "This tool provides rough educational guidance and is not tax, legal, or financial advice."

    lines.extend(
        [
            "## IRS source set",
        ]
    )
    for source in irs_sources:
        parts = [
            f"- {source.name}",
            f"  - URL: {source.url}",
            f"  - Reviewed: {source.reviewed_at_utc}",
        ]
        if source.status_code is not None:
            parts.append(f"  - HTTP status: {source.status_code}")
        if source.last_modified:
            parts.append(f"  - Last-Modified: {source.last_modified}")
        if source.error:
            parts.append(f"  - Refresh note: {source.error}")
        lines.extend(parts)
    lines.append("")

    lines.extend(
        [
            "## Ingestion summary",
            f"- Documents extracted: `{totals['documents']}`",
            f"- Characters extracted: `{totals['characters']}`",
            f"- Chunks indexed: `{totals['chunks']}`",
            f"- Uploaded artifacts: `{len(uploaded_artifacts)}`",
            f"- Model-reported sources used: `{generation.sources_used if generation.sources_used is not None else 'unknown'}`",
            "",
            "## Source and chunk index",
        ]
    )

    for doc in extracted_documents:
        lines.append(f"### `{doc.source_name}`")
        lines.append(f"- Source file: `{doc.source_name}`")
        lines.append(f"- Source ref: `{doc.source_ref}`")
        lines.append(f"- Source kind: `{doc.source_kind}`")
        lines.append(f"- Chunks: `{len(doc.chunks)}`")
        remote_ids = source_to_remote.get(str(doc.source_path), [])
        lines.append(f"- Remote file ids: `{', '.join(remote_ids) if remote_ids else 'none'}`")
        upload_kinds = source_to_upload_kinds.get(str(doc.source_path), [])
        if upload_kinds:
            joined = ", ".join(sorted(set(upload_kinds)))
            lines.append(f"- Upload payload type: `{joined}`")
        if doc.extraction_notes:
            lines.append("- Extraction notes:")
            for note in doc.extraction_notes:
                lines.append(f"  - {note}")
        lines.append("")

    lines.append("## Model citation payload")
    if generation.citations:
        for index, citation in enumerate(generation.citations, start=1):
            lines.append(f"{index}. `{citation}`")
    else:
        lines.append("- No machine-readable citations returned.")
    lines.append("")

    lines.append("## Cleanup")
    lines.append(f"- Cleanup enabled: `{cleanup_enabled}`")
    lines.append(f"- Deleted remote files: `{len(cleanup.deleted_file_ids)}`")
    if cleanup.deleted_file_ids:
        for file_id in cleanup.deleted_file_ids:
            lines.append(f"  - `{file_id}`")
    if cleanup.delete_failures:
        lines.append("- Cleanup failures:")
        for failure in cleanup.delete_failures:
            lines.append(f"  - {failure}")
    lines.append("")

    lines.append("## Warnings")
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(
        [
            "## Disclaimer",
            disclaimer,
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def write_phase2_report(**kwargs) -> Path:
    """Backward-compatible alias now backed by phase-3 renderer."""
    return write_phase3_report(**kwargs)
