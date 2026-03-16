"""Structured output schema parsing for phase-3 guidance."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any


@dataclass(frozen=True)
class TaxGuidance:
    """Normalized phase-3 tax guidance payload."""

    how_to_file: list[str]
    what_to_file: list[str]
    what_to_remember: list[str]
    what_not_to_forget: list[str]
    common_mistakes: list[str]
    rough_expectation_summary: str
    rough_expectation_drivers: list[str]
    confidence_level: str
    missing_information: list[str]
    estimated_2025_refund_or_owed: str
    assumptions: list[str]
    citation_notes: list[str]
    disclaimer: str


class GuidanceParseError(ValueError):
    """Raised when model output cannot be normalized into TaxGuidance."""


def _clean_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _extract_json_text(raw_text: str) -> str:
    stripped = raw_text.strip()
    if not stripped:
        raise GuidanceParseError("Model response is empty.")

    if stripped.startswith("```"):
        fenced = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", stripped)
        fenced = re.sub(r"\n```$", "", fenced).strip()
        if fenced:
            stripped = fenced

    # Try direct JSON first.
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    # Fallback: extract first JSON object in text.
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        return stripped[first : last + 1]
    raise GuidanceParseError("No JSON object found in model response.")


def parse_tax_guidance(raw_text: str) -> TaxGuidance:
    """Parse strict JSON payload into TaxGuidance."""
    json_text = _extract_json_text(raw_text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise GuidanceParseError(f"JSON decode failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise GuidanceParseError("Expected top-level JSON object.")

    rough_expectation_summary = str(payload.get("rough_expectation_summary", "")).strip()
    confidence_level = str(payload.get("confidence_level", "")).strip().lower()
    disclaimer = str(payload.get("disclaimer", "")).strip()

    guidance = TaxGuidance(
        how_to_file=_clean_str_list(payload.get("how_to_file")),
        what_to_file=_clean_str_list(payload.get("what_to_file")),
        what_to_remember=_clean_str_list(payload.get("what_to_remember")),
        what_not_to_forget=_clean_str_list(payload.get("what_not_to_forget")),
        common_mistakes=_clean_str_list(payload.get("common_mistakes")),
        rough_expectation_summary=rough_expectation_summary or "Rough expectation unavailable from source data.",
        rough_expectation_drivers=_clean_str_list(payload.get("rough_expectation_drivers")),
        confidence_level=confidence_level or "low",
        missing_information=_clean_str_list(payload.get("missing_information")),
        estimated_2025_refund_or_owed=str(payload.get("estimated_2025_refund_or_owed", "")).strip() or "Rough estimate unavailable from source data.",
        assumptions=_clean_str_list(payload.get("assumptions")),
        citation_notes=_clean_str_list(payload.get("citation_notes")),
        disclaimer=disclaimer or "This is rough educational guidance, not tax/legal/financial advice.",
    )
    return guidance
