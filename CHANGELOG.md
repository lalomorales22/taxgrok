# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- PDF OCR fallback path: when local PDF extraction is weak, pipeline attempts xAI OCR text extraction.
- `--no-local-redaction` CLI flag for explicit redaction opt-out.
- Terminal dashboard UI with black-themed ASCII `taxgrok` intro for interactive TTY sessions.
- `--no-style` flag and `TAXGROK_NO_STYLE=1` env override for plain menu mode.
- Pre-analysis taxpayer prompt for name + filing status, with context passed into model prompting.
- Analysis loading indicator while pipeline processing is running.

### Changed
- Local redaction default is now ON (`TAXGROK_LOCAL_REDACTION` defaults to enabled).
- Report and artifact metadata no longer include absolute local source paths.
- Report filename now uses entered taxpayer name (sanitized) instead of default OS username when provided.

### Fixed
- Low-quality scanned PDFs now fall back to original-PDF upload for retrieval if OCR fallback text is still insufficient.

## [0.1.1] - 2026-02-10

### Added
- Configurable xAI base URL via `TAXGROK_XAI_BASE_URL` for regional endpoint routing/tests.
- Additional regression coverage for upload-denied, generation-denied, and empty-generation fallback paths.
- README troubleshooting notes for `403`/`1010` responses and document quality tips for blurry scans.

### Changed
- `pypdf` is now included as a package dependency for local PDF extraction.
- Chat payload handling now sends plain text content for text-only requests for better endpoint compatibility.

### Fixed
- Removed invalid `tools: [{"type":"file_search"}]` payload from `/v1/responses` requests that caused `422` (`missing field vector_store_ids`).
- Pipeline no longer hard-fails when all file uploads are denied; it now runs in local-context mode.
- Pipeline now falls back to local heuristic structured guidance when generation endpoints are denied (`403`/`1010`) or when model output is empty.
- Improved endpoint fallback behavior to report both generation endpoint failures before switching to local fallback.

## [0.1.0] - 2026-02-10

### Added
- Initial `taxgrok` CLI with interactive menu and file/folder queueing.
- Input support for `.txt`, `.md`, `.pdf`, `.png`.
- xAI integration for file upload, retrieval generation, and remote cleanup.
- IRS source loader with optional source refresh checks.
- Phase-3 structured guidance generation using Responses API with chat fallback.
- Final report rendering to `TAXGROK-<username>.md` with filing sections, citations, and warnings.
- Local `.env` loading support for runtime config.
- Optional local PII redaction pass before upload.
- PII-safe logging filter for runtime logs.
- Unit and integration tests with mocked xAI API behavior.
- GitHub Actions CI for lint, tests, and packaging checks.

### Notes
- v1 scope is U.S. federal tax guidance only.
- Output is rough educational guidance, not tax/legal/financial advice.

## Handoff to Next Codex Chat

- Current state: CLI flow works end-to-end; reports are generated successfully even when xAI endpoints partially or fully deny access.
- Known constraint: low-quality/blurry image-based PDFs can still lead to weak extraction and lower-confidence guidance.
- Suggested next step: improve OCR robustness for scanned PDFs/PNGs (preprocessing and extraction quality scoring) and expose a user-facing retry/quality hint before analysis.
