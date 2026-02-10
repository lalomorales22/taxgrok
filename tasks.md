# taxgrok Build Plan (4 Phases)

## Phase 1 - Foundation and CLI Skeleton

Goal: Create a working local CLI scaffold with clean project structure and config handling.

Tasks:
- [x] Initialize Python package structure (`taxgrok/`, tests, `pyproject.toml`).
- [x] Add CLI entrypoint `taxgrok` with interactive menu loop.
- [x] Implement config + env loading (`XAI_API_KEY`, local username).
- [x] Add file/folder picker logic and extension filtering (`txt`, `md`, `pdf`, `png`).
- [x] Add logging, error handling, and non-zero exit codes for failures.
- [x] Add baseline README usage section and setup instructions.

Exit criteria:
- Running `taxgrok` opens menu and can queue valid files from folder traversal.
- Invalid file types are skipped with clear warnings.
- Config validation errors are actionable and explicit.

## Phase 2 - Ingestion and RAG Pipeline

Goal: Convert inputs into retrievable knowledge and wire xAI retrieval end-to-end.

Tasks:
- [x] Build text extraction adapters for `.txt`, `.md`, `.pdf`.
- [x] Build `.png` analysis adapter using xAI image understanding -> normalized text artifact.
- [x] Upload run-scoped artifacts via Files API.
- [x] Implement retrieval via file attachments and document search tools in generation requests.
- [x] Implement remote file cleanup after report generation (default behavior).
- [x] Add citation metadata tracking per chunk/source.

Exit criteria:
- Mixed folder ingest completes and uploaded files are attached for retrieval.
- Retrieval returns relevant passages with source references.
- Pipeline gracefully handles partial upload/extraction failures.

## Phase 3 - Tax Guidance Report Generation

Goal: Produce high-signal `TAXGROK-<username>.md` report grounded in user docs + IRS baseline context.

Tasks:
- [x] Create strict system prompt with scope guardrails and disclaimer.
- [x] Add IRS source loader/refresh module (curated official URLs + reviewed dates).
- [x] Build response orchestration via `POST /v1/responses`.
- [x] Define output template sections:
  - filing checklist
  - documents to prepare
  - likely payment/refund drivers
  - deductions/credits to verify
  - common mistakes and "do not forget" items
- [x] Add confidence/unknowns block and citation footer.
- [x] Add rough estimate language rules and confidence caveats.
- [x] Write final markdown output to `TAXGROK-<username>.md`.

Exit criteria:
- Report is generated from real sample inputs and passes format checks.
- Report includes disclaimer, timestamp, and source metadata.
- Missing information is explicitly listed as follow-up questions.
- Uploaded remote files are removed on successful completion.

## Phase 4 - Quality, Security, and PyPI Release

Goal: Productionize for public install and safe default behavior.

Tasks:
- [x] Unit tests for ingestion, filtering, prompt building, and output rendering.
- [x] Integration test for end-to-end run with mocked xAI APIs.
- [x] Add PII-safe logging policy and optional local redaction pass.
- [x] Add optional debug mode to keep remote files temporarily (off by default).
- [x] Add CI workflow (lint, tests, packaging checks).
- [x] Build release artifacts workflow and publish-ready docs (`CHANGELOG.md`, `RELEASE.md`).

Exit criteria:
- Test suite is stable in CI.
- Package installs via `pip install taxgrok` and CLI works.
- Release checklist and rollback procedure are documented.

## Cross-Phase Risks to Track

- xAI endpoint/tooling changes affecting file attachment search behavior.
- IRS source drift or stale yearly documents.
- OCR quality variance on low-quality PNG uploads.
- Token/cost growth with large folders.

## Immediate next actions

1. Run first real-key end-to-end generation against xAI (`.env` with `XAI_API_KEY`).
2. Publish first PyPI release using `RELEASE.md`.
3. Collect user feedback and prioritize post-v1 improvements.
