"""Phase 3 pipeline: ingestion, retrieval generation, schema parsing, cleanup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import Callable, Sequence

from .config import RuntimeConfig
from .ingestion import (
    ExtractedDocument,
    build_image_document,
    extract_local_document,
    replace_document_text,
    write_artifact,
)
from .irs_sources import IRSSource, load_irs_sources
from .prompts import build_tax_system_prompt, build_tax_user_prompt
from .schema import GuidanceParseError, TaxGuidance, parse_tax_guidance
from .security import redact_document
from .taxpayer import TaxpayerContext
from .xai_client import GenerationResult, XAIClient


@dataclass(frozen=True)
class UploadedArtifact:
    """One uploaded artifact tied back to its source file."""

    source_path: Path
    artifact_path: Path
    remote_file_id: str
    upload_kind: str = "artifact"


@dataclass(frozen=True)
class CleanupResult:
    """Remote cleanup details for report/logging."""

    deleted_file_ids: list[str]
    delete_failures: list[str]


@dataclass
class PipelineResult:
    """Pipeline output values returned to CLI."""

    report_path: Path
    generation: GenerationResult
    extracted_documents: list[ExtractedDocument]
    uploaded_artifacts: list[UploadedArtifact]
    cleanup: CleanupResult
    irs_sources: list[IRSSource]
    guidance: TaxGuidance | None
    warnings: list[str] = field(default_factory=list)


# Backward-compatible alias for existing tests/imports.
Phase2Result = PipelineResult


class PipelineError(RuntimeError):
    """Raised when pipeline cannot complete generation."""


# Backward-compatible alias for existing imports.
Phase2PipelineError = PipelineError

_PDF_INCOMPLETE_TEXT_MARKER = "Local PDF extraction was incomplete."
_PDF_MIN_ARTIFACT_CHARS = 120


def _pdf_needs_ocr_fallback(doc: ExtractedDocument) -> bool:
    if doc.source_kind != "pdf":
        return False
    for note in doc.extraction_notes:
        lowered = note.lower()
        if "pypdf is not installed" in lowered:
            return True
        if "no extractable text found" in lowered:
            return True
        if "unable to parse pdf locally" in lowered:
            return True
        if "extraction failed" in lowered and "page " in lowered:
            return True
    return False


def _pdf_has_usable_artifact_text(doc: ExtractedDocument) -> bool:
    if doc.source_kind != "pdf":
        return True
    cleaned = doc.text.strip()
    if not cleaned:
        return False
    if _PDF_INCOMPLETE_TEXT_MARKER in cleaned:
        return False
    return len(cleaned) >= _PDF_MIN_ARTIFACT_CHARS


def _generate_with_fallback(
    *,
    xai_client: XAIClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
    attached_ids: list[str],
    warnings: list[str],
    prefer_chat_first: bool = False,
) -> GenerationResult:
    attempts: list[tuple[str, Callable[[], GenerationResult]]]
    if prefer_chat_first:
        attempts = [
            (
                "Chat Completions",
                lambda: xai_client.chat_completion(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    attached_file_ids=attached_ids,
                    temperature=0.1,
                ),
            ),
            (
                "Responses API",
                lambda: xai_client.responses_completion(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    attached_file_ids=attached_ids,
                    temperature=0.1,
                ),
            ),
        ]
    else:
        attempts = [
            (
                "Responses API",
                lambda: xai_client.responses_completion(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    attached_file_ids=attached_ids,
                    temperature=0.1,
                ),
            ),
            (
                "Chat Completions",
                lambda: xai_client.chat_completion(
                    model=model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    attached_file_ids=attached_ids,
                    temperature=0.1,
                ),
            ),
        ]

    errors: list[str] = []
    for index, (label, call) in enumerate(attempts, start=1):
        try:
            return call()
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            if index < len(attempts):
                warnings.append(f"{label} failed; trying fallback endpoint ({exc}).")

    raise RuntimeError("All generation endpoints failed. " + " | ".join(errors))


def _looks_like_files_api_acl_failure(message: str) -> bool:
    lowered = message.lower()
    if "error code: 1010" in lowered:
        return True
    if "/v1/files" not in lowered:
        return False
    return any(
        marker in lowered
        for marker in (
            "(403",
            " 403",
            "forbidden",
            "permission",
            "not allowed",
            "unauthorized",
            "access denied",
        )
    )


def _looks_like_permission_failure(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "error code: 1010",
            "(403",
            " 403",
            "forbidden",
            "permission",
            "not allowed",
            "unauthorized",
            "access denied",
            "doesn't have permission",
        )
    )


def _truncate_for_prompt(value: str, *, max_chars: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars <= 20:
        return cleaned[:max_chars]
    return cleaned[: max_chars - 16].rstrip() + "\n...[truncated]"


def _build_local_context_appendix(extracted_documents: list[ExtractedDocument]) -> str:
    max_chars_total = 22000
    max_chars_per_doc = 5000

    lines = [
        "No remote xAI files were attached for this run.",
        "Use ONLY the local extracted text below as evidence for the JSON response.",
        "If extraction appears incomplete, mark uncertainty in missing_information and follow_up_questions.",
        "",
        "Local extracted context:",
    ]

    total_used = 0
    docs_included = 0
    truncated_docs = 0

    for index, doc in enumerate(extracted_documents, start=1):
        remaining = max_chars_total - total_used
        if remaining <= 0:
            break

        allowance = min(max_chars_per_doc, remaining)
        snippet = _truncate_for_prompt(doc.text, max_chars=allowance)
        if snippet.endswith("...[truncated]"):
            truncated_docs += 1
        total_used += len(snippet)
        docs_included += 1

        lines.extend(
            [
                f"### Source {index}: {doc.source_name}",
                f"- Source type: {doc.source_kind}",
                f"- Extraction notes: {', '.join(doc.extraction_notes) if doc.extraction_notes else 'none'}",
                "```text",
                snippet or "(empty extracted text)",
                "```",
                "",
            ]
        )

    omitted_docs = len(extracted_documents) - docs_included
    if omitted_docs > 0:
        lines.append(f"- {omitted_docs} source(s) omitted from prompt due context size limits.")
    if truncated_docs > 0:
        lines.append(f"- {truncated_docs} source(s) truncated for prompt size limits.")

    return "\n".join(lines)


def _looks_like_form(doc: ExtractedDocument, form_code: str) -> bool:
    lowered_name = doc.source_name.lower()
    lowered_text = doc.text.lower()
    token = form_code.lower()
    return token in lowered_name or token in lowered_text


def _build_local_heuristic_guidance(extracted_documents: list[ExtractedDocument]) -> TaxGuidance:
    forms_detected: list[str] = []
    known_forms = [
        ("W-2", "Form W-2 (wage income and withholding)"),
        ("1099", "Form 1099 series income statement(s)"),
        ("1098", "Form 1098 (mortgage interest)"),
    ]
    for code, label in known_forms:
        if any(_looks_like_form(doc, code) for doc in extracted_documents):
            forms_detected.append(label)

    if not forms_detected:
        forms_detected.append("Income and deduction documents found in uploaded files (exact form mapping uncertain).")

    citation_notes = [f"{doc.source_name}: locally extracted evidence." for doc in extracted_documents[:10]]
    if len(extracted_documents) > 10:
        citation_notes.append(f"{len(extracted_documents) - 10} additional source(s) omitted from citation notes.")

    return TaxGuidance(
        how_to_file=[
            "Prepare a federal Form 1040 return using your extracted wage/income documents.",
            "Cross-check names, SSN, filing status, and dependent details before submitting.",
            "E-file when possible and keep a saved copy of the final return and acknowledgements.",
        ],
        what_to_file=forms_detected
        + [
            "Form 1040 and any schedules required by your income and deduction items.",
            "Any additional federal statements not present in the uploaded set.",
        ],
        what_to_remember=[
            "Use exact withholding values from each income statement.",
            "Confirm account/routing details if choosing direct deposit or direct debit.",
            "Keep source documents and final return records for audit/tie-out support.",
        ],
        what_not_to_forget=[
            "Report all taxable income sources (W-2/1099 and similar).",
            "Include deductible items only when documentation supports them.",
            "Verify key identifiers and totals to avoid IRS mismatch notices.",
        ],
        common_mistakes=[
            "Typos in SSN, names, or bank details.",
            "Missing one or more income forms.",
            "Copying rounded/estimated values instead of exact statement amounts.",
        ],
        rough_expectation_summary=(
            "xAI generation endpoints were unavailable for this run, so this is a local heuristic summary only. "
            "Final refund/payment depends on complete income, credits, deductions, and withholding."
        ),
        rough_expectation_drivers=[
            "Total withholding vs final federal tax liability.",
            "Additional income not fully captured in provided files.",
            "Eligibility for credits/deductions not inferable from current document set.",
        ],
        confidence_level="low",
        missing_information=[
            "Potential missing federal forms not included in the queue.",
            "Full filing-status, dependents, and credit-eligibility inputs.",
            "Exact year-specific values needed for a reliable estimate.",
        ],
        follow_up_questions=[
            "Do you have any additional 1099, K-1, or other income forms?",
            "Are there credits/deductions (education, childcare, retirement, etc.) not represented here?",
            "Was any estimated federal tax paid outside withholding?",
        ],
        assumptions=[
            "Federal filing scope only.",
            "Uploaded files are representative but may be incomplete.",
            "No legal/tax advice is being provided.",
        ],
        citation_notes=citation_notes,
        disclaimer=(
            "This report is rough educational guidance generated without successful xAI endpoint access for this run. "
            "It is not tax, legal, or financial advice."
        ),
    )


def run_phase3_pipeline(
    *,
    config: RuntimeConfig,
    queued_files: Sequence[Path],
    report_writer: Callable[..., Path],
    client: XAIClient | None = None,
    taxpayer_context: TaxpayerContext | None = None,
) -> PipelineResult:
    """Run phase 3 pipeline end-to-end."""
    if not queued_files:
        raise PipelineError("No queued files were provided.")

    xai_client = client or XAIClient(
        api_key=config.xai_api_key,
        base_url=config.xai_base_url,
        timeout_seconds=config.timeout_seconds,
    )

    warnings: list[str] = []
    extracted_documents: list[ExtractedDocument] = []
    uploaded_artifacts: list[UploadedArtifact] = []
    guidance: TaxGuidance | None = None
    generation: GenerationResult | None = None
    deleted_file_ids: list[str] = []
    delete_failures: list[str] = []
    upload_failures: list[str] = []

    irs_sources = load_irs_sources(
        refresh=config.refresh_irs_sources,
        timeout_seconds=min(config.timeout_seconds, 12),
    )

    with tempfile.TemporaryDirectory(prefix="taxgrok-phase3-") as tmp_dir:
        artifact_dir = Path(tmp_dir)

        for path in sorted(queued_files, key=lambda value: str(value)):
            extension = path.suffix.lower()
            if extension == ".png":
                try:
                    extracted_image_text = xai_client.analyze_png(png_path=path, model=config.model)
                except Exception as exc:
                    warnings.append(f"{path.name}: PNG analysis failed ({exc}).")
                    extracted_image_text = (
                        "Image analysis failed for this source. Content may be missing from generated report."
                    )
                doc = build_image_document(path, extracted_image_text)
            else:
                try:
                    doc = extract_local_document(path)
                except Exception as exc:
                    warnings.append(f"{path.name}: local extraction failed ({exc}).")
                    continue
                if extension == ".pdf" and _pdf_needs_ocr_fallback(doc):
                    warnings.append(
                        f"{path.name}: local PDF extraction was low quality; attempting xAI OCR fallback."
                    )
                    try:
                        ocr_text = xai_client.extract_pdf_text(pdf_path=path, model=config.model)
                    except Exception as exc:
                        warnings.append(f"{path.name}: PDF OCR fallback failed ({exc}).")
                    else:
                        if ocr_text.strip():
                            doc = replace_document_text(
                                doc,
                                ocr_text,
                                note="xAI OCR fallback applied after low local PDF extraction quality.",
                            )
                            warnings.append(f"{path.name}: PDF OCR fallback applied.")
                        else:
                            warnings.append(f"{path.name}: PDF OCR fallback returned empty text.")

            if config.local_redaction:
                doc, redaction_count = redact_document(doc)
                if redaction_count > 0:
                    warnings.append(f"{path.name}: local redaction applied ({redaction_count} replacement(s)).")

            write_artifact(doc, artifact_dir, len(extracted_documents) + 1)
            extracted_documents.append(doc)

        if not extracted_documents:
            raise PipelineError("No documents were extracted successfully from queued files.")

        for doc in extracted_documents:
            if doc.artifact_path is None:
                warnings.append(f"{doc.source_name}: missing artifact path after extraction.")
                continue
            upload_path = doc.artifact_path
            upload_kind = "artifact"
            if doc.source_kind == "pdf" and not _pdf_has_usable_artifact_text(doc):
                upload_path = doc.source_path
                upload_kind = "source-pdf"
                warnings.append(
                    f"{doc.source_name}: artifact text still low quality; uploading original PDF for retrieval."
                )
            try:
                uploaded = xai_client.upload_file(upload_path)
            except Exception as exc:
                failure = f"{doc.source_name}: upload failed ({exc})."
                warnings.append(failure)
                upload_failures.append(failure)
                continue
            uploaded_artifacts.append(
                UploadedArtifact(
                    source_path=doc.source_path,
                    artifact_path=doc.artifact_path,
                    remote_file_id=uploaded.file_id,
                    upload_kind=upload_kind,
                )
            )

        attached_ids = [item.remote_file_id for item in uploaded_artifacts]
        system_prompt = build_tax_system_prompt(
            irs_sources=irs_sources,
            username=config.username,
            taxpayer_context=taxpayer_context,
        )
        user_prompt = build_tax_user_prompt()

        local_context_mode = not attached_ids
        if local_context_mode:
            first_failure = upload_failures[0] if upload_failures else "unknown upload issue"
            if _looks_like_files_api_acl_failure(first_failure):
                warnings.append(
                    "Files API permission/access issue detected; using local-context text prompts (no remote file attachments)."
                )
            else:
                warnings.append(
                    "No artifacts uploaded successfully; using local-context text prompts (no remote file attachments)."
                )
            if any(
                "pypdf is not installed" in note
                for doc in extracted_documents
                for note in doc.extraction_notes
            ):
                warnings.append(
                    "Install `pypdf` to improve local PDF extraction when remote uploads are unavailable."
                )
            user_prompt = f"{user_prompt}\n\n{_build_local_context_appendix(extracted_documents)}"

        try:
            generation = _generate_with_fallback(
                xai_client=xai_client,
                model=config.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                attached_ids=attached_ids,
                warnings=warnings,
                prefer_chat_first=local_context_mode,
            )
            if not generation.text.strip():
                warnings.append(
                    "Generation returned empty text; falling back to local heuristic report."
                )
                guidance = _build_local_heuristic_guidance(extracted_documents)
                generation = GenerationResult(
                    text=guidance.disclaimer,
                    citations=[],
                    sources_used=0,
                    raw_response={
                        "fallback": "local-heuristic-empty-generation",
                        "upstream_api_path": generation.api_path,
                    },
                    api_path="/local/fallback",
                )
            else:
                try:
                    guidance = parse_tax_guidance(generation.text)
                except GuidanceParseError as exc:
                    warnings.append(f"Structured output parsing failed; using raw model text ({exc}).")
                    guidance = None
        except Exception as exc:
            if _looks_like_permission_failure(str(exc)):
                warnings.append(
                    "xAI generation endpoint access appears denied (403/ACL). Falling back to local heuristic report."
                )
                guidance = _build_local_heuristic_guidance(extracted_documents)
                generation = GenerationResult(
                    text=guidance.disclaimer,
                    citations=[],
                    sources_used=0,
                    raw_response={"fallback": "local-heuristic", "error": str(exc)},
                    api_path="/local/fallback",
                )
            else:
                raise PipelineError(f"Generation failed: {exc}") from exc
        finally:
            if config.cleanup_remote_files:
                for file_id in attached_ids:
                    try:
                        xai_client.delete_file(file_id)
                        deleted_file_ids.append(file_id)
                    except Exception as exc:
                        delete_failures.append(f"{file_id}: {exc}")

    if generation is None:
        raise PipelineError("Generation did not return a response.")

    cleanup = CleanupResult(deleted_file_ids=deleted_file_ids, delete_failures=delete_failures)
    report_path = report_writer(
        username=config.username,
        output_dir=config.output_dir,
        extracted_documents=extracted_documents,
        uploaded_artifacts=uploaded_artifacts,
        generation=generation,
        cleanup=cleanup,
        irs_sources=irs_sources,
        guidance=guidance,
        warnings=warnings,
        model=config.model,
        cleanup_enabled=config.cleanup_remote_files,
        taxpayer_context=taxpayer_context,
    )
    return PipelineResult(
        report_path=report_path,
        generation=generation,
        extracted_documents=extracted_documents,
        uploaded_artifacts=uploaded_artifacts,
        cleanup=cleanup,
        irs_sources=irs_sources,
        guidance=guidance,
        warnings=warnings,
    )


def run_phase2_pipeline(
    *,
    config: RuntimeConfig,
    queued_files: Sequence[Path],
    report_writer: Callable[..., Path],
    client: XAIClient | None = None,
    taxpayer_context: TaxpayerContext | None = None,
) -> PipelineResult:
    """Compatibility wrapper kept for older imports/tests."""
    return run_phase3_pipeline(
        config=config,
        queued_files=queued_files,
        report_writer=report_writer,
        client=client,
        taxpayer_context=taxpayer_context,
    )
