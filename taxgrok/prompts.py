"""Prompt builders for phase-3 tax guidance generation."""

from __future__ import annotations

from .irs_sources import IRSSource, format_irs_sources_for_prompt
from .taxpayer import TaxpayerContext, filing_status_label


def build_tax_system_prompt(
    *,
    irs_sources: list[IRSSource],
    username: str,
    taxpayer_context: TaxpayerContext | None = None,
) -> str:
    """Return strict system prompt with schema and scope constraints."""
    profile_lines = ""
    if taxpayer_context is not None:
        profile_lines = (
            f"\nDeclared taxpayer name: {taxpayer_context.display_name}\n"
            f"Declared filing status: {filing_status_label(taxpayer_context.filing_status)}\n"
            "Use declared filing status to shape checklist guidance and assumptions.\n"
        )
    return (
        "You are TAXGROK, a U.S. federal tax-prep assistant.\n"
        "Audience: a single user running a local CLI tool.\n"
        "Scope: federal taxes only. No state tax guidance.\n"
        "Style: practical, concise, actionable checklists.\n"
        "Safety: this is rough educational guidance, not legal/tax/financial advice.\n"
        "Never claim certainty when source info is missing.\n"
        "Explicitly list unknowns and follow-up questions.\n"
        "Do not fabricate IRS rules, thresholds, or forms.\n"
        "Only produce the JSON object schema requested by the user prompt.\n"
        "Use rough expectation language (likely, possible, estimated) for refund/payment outcomes.\n"
        f"Target user id: {username}\n"
        f"{profile_lines}"
        "IRS baseline references:\n"
        f"{format_irs_sources_for_prompt(irs_sources)}"
    )


def build_tax_user_prompt() -> str:
    """Return required JSON schema prompt for final report rendering."""
    return (
        "Review attached tax-relevant artifacts and return ONLY valid JSON with this exact shape:\n"
        "{\n"
        '  "how_to_file": ["..."],\n'
        '  "what_to_file": ["..."],\n'
        '  "what_to_remember": ["..."],\n'
        '  "what_not_to_forget": ["..."],\n'
        '  "common_mistakes": ["..."],\n'
        '  "rough_expectation_summary": "...",\n'
        '  "rough_expectation_drivers": ["..."],\n'
        '  "confidence_level": "low|medium|high",\n'
        '  "missing_information": ["..."],\n'
        '  "follow_up_questions": ["..."],\n'
        '  "assumptions": ["..."],\n'
        '  "citation_notes": ["filename: short note"],\n'
        '  "disclaimer": "..."'
        "}\n"
        "Requirements:\n"
        "- Keep all lists non-empty when possible; use explicit 'unknown' items when data is missing.\n"
        "- Federal only. No state tax guidance.\n"
        "- Keep rough estimate language and include caveats.\n"
        "- Prefer short, practical bullet-sized strings.\n"
        "- Do not output markdown, explanations, or code fences."
    )
