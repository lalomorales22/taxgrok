"""Taxpayer profile helpers for analysis context and report naming."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class TaxpayerContext:
    """User-provided taxpayer context used for prompting/report metadata."""

    display_name: str
    filing_status: str


_FILING_STATUS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("single", "Single"),
    ("married_filing_jointly", "Married filing jointly"),
    ("married_filing_separately", "Married filing separately"),
    ("head_of_household", "Head of household"),
    ("qualifying_surviving_spouse", "Qualifying surviving spouse"),
    ("unknown", "Not sure yet"),
)

_FILING_STATUS_LABELS: dict[str, str] = dict(_FILING_STATUS_OPTIONS)

_FILING_STATUS_ALIASES: dict[str, str] = {
    "single": "single",
    "s": "single",
    "married_filing_jointly": "married_filing_jointly",
    "married_joint": "married_filing_jointly",
    "married_jointly": "married_filing_jointly",
    "joint": "married_filing_jointly",
    "jointly": "married_filing_jointly",
    "mfj": "married_filing_jointly",
    "married_filing_separately": "married_filing_separately",
    "married_separate": "married_filing_separately",
    "separate": "married_filing_separately",
    "separately": "married_filing_separately",
    "mfs": "married_filing_separately",
    "head_of_household": "head_of_household",
    "hoh": "head_of_household",
    "household": "head_of_household",
    "qualifying_surviving_spouse": "qualifying_surviving_spouse",
    "surviving_spouse": "qualifying_surviving_spouse",
    "qss": "qualifying_surviving_spouse",
    "widow": "qualifying_surviving_spouse",
    "widower": "qualifying_surviving_spouse",
    "unknown": "unknown",
    "not_sure": "unknown",
    "unsure": "unknown",
    "dont_know": "unknown",
}


def filing_status_options() -> tuple[tuple[str, str], ...]:
    """Return filing-status option tuples for CLI prompts."""
    return _FILING_STATUS_OPTIONS


def filing_status_label(code: str) -> str:
    """Return human label for filing status code."""
    return _FILING_STATUS_LABELS.get(code, _FILING_STATUS_LABELS["unknown"])


def parse_filing_status(raw_value: str) -> str | None:
    """Parse free-text filing-status input into normalized status code."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", raw_value.strip().lower()).strip("_")
    if not cleaned:
        return None
    return _FILING_STATUS_ALIASES.get(cleaned)
