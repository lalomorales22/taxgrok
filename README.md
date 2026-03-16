# taxgrok
```text
     █████████████ ██
   ███████████████████        ███                                █████████                        █████
 ██████░░░░░░░░░██████░       ████                             ████████████                       █████░
█████░░░░░░░░██████████░    █████████ █████████  █████  █████ ██████░░░░██░░ ████████  █████████  █████░██████
███░░░░░░░░██████░░░████░   █████████░██████████  ██████████░█████░░░██████░░████████████████████ ███████████░░
███░░░░░░█████░░░░░░████░░   ░████░░░░██████████░  ░██████░░░█████░░░██████░░████░░░░████░░░░████░████████░░░░░░
███░░░░█████░░░░░░░░████░░   ███████░███████████░░ ████████░░░███████░░████░░████░░░░██████░█████░██████████░░░░░
██████████░░░░░░░░░████░░░░   ██████████████████░██████░█████░░████████████░░████░░░░░██████████░░█████░██████░░░░
 ███████░░░░░░░░░░████░░░░░░   ░████░░░████░░███░████░░░░████░░░░░███████░░░░████░░░░░░░██████░░░░░███░░░░████░░░
██████████████░░░░ ░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░░   ░░░░░░░░░░░░░░░░░░░░░░░░
████░█████████░░    ░░░░░░░░     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░
 ░░░░░░░░░░░░░░░     ░░░░░░       ░░░░░░░░░░░░░░░░░░░░░░░░░ ░░░░░  ░░░░░░░░░░░░ ░░░░░     ░░░░░░░░░░  ░░░░░ ░░░░░░
  ░░░░░░░░░░░░░░░     ░░░░          ░░░░   ░░░░  ░░░ ░░░░    ░░░░     ░░░░░░░    ░░░░       ░░░░░░     ░░░    ░░░░
   ░░░░░░░░░░░░░░░
    ░░░░ ░░░░░░░░░
```



---
`taxgrok` is a local Python CLI app for generating a tax-prep briefing from user documents using xAI + RAG.

Planned behavior:
- User runs `taxgrok` from terminal.
- Startup shows a black-themed Unicode logo + dashboard in TTY terminals (auto-fits terminal width).
- Menu lets user add one file or an entire folder.
- Accepted input types: `.txt`, `.md`, `.pdf`, `.png`.
- Before analysis, app asks taxpayer name + filing status (single/MFJ/MFS/HOH/QSS/not sure).
- App analyzes content and writes `TAXGROK-<username>.md`.
- Output provides practical filing guidance: what to file, checklist, common mistakes, and refund/payment expectation notes.
- One-run privacy default: uploaded remote files are deleted after report generation.

## Product scope

This tool is for educational planning and organization, not legal/tax advice.

Primary goals:
- Fast local ingestion workflow for mixed document types.
- RAG-grounded report with citations and explicit unknowns.
- Up-to-date IRS grounding data used as baseline context.
- Packaged for PyPI with `pip install taxgrok`.
- Single-user local experience per install.

## xAI API assumptions (verified Feb 10, 2026)

Current official xAI docs indicate:
- Base REST API: `https://api.x.ai`
- Preferred text generation API: `POST /v1/responses`
- Legacy chat API (still available): `POST /v1/chat/completions`
- Files API: `POST /v1/files` and related file routes (API key)
- Files attached to chats automatically trigger document retrieval (`attachment_search`) for RAG-style workflows.
- Collections search API: `POST /v1/documents/search` (API key for querying collection content).
- Collections management API base: `https://management-api.x.ai` (only needed if creating/managing collections programmatically).

Important auth detail:
- For this v1 design, only `XAI_API_KEY` is required (Files + chat/reasoning flow).
- A Management key is only needed if we later adopt Collections lifecycle operations.

## Proposed architecture

1. CLI Layer
- `taxgrok` command with interactive menu.
- Commands: add file, add folder, review queue, run analysis, exit.

2. Ingestion Layer
- File validation and MIME detection.
- `.txt`, `.md`, `.pdf` routed to text extraction.
- `.png` routed to image understanding pipeline, converted into structured text notes.

3. Retrieval Layer (RAG)
- Upload accepted files for the current run using Files API.
- Attach uploaded files to model requests so xAI performs server-side document retrieval (`attachment_search`).
- Keep retrieval ephemeral: delete uploaded files after report output.

4. Tax Reasoning Layer
- Prepend strict system prompt for tax assistant behavior.
- Use IRS baseline corpus plus user corpus.
- Force output schema (sections/checklists/warnings/citations).

5. Output Layer
- Render `TAXGROK-<username>.md`.
- Include generation timestamp, data sources, confidence notes, and disclaimer.

## IRS grounding plan

Use authoritative IRS pages/documents as curated source list with refresh metadata:
- Forms, Instructions and Publications (latest index)
- Publication 17 (current year)
- Form 1040 Instructions (current year)
- Inflation-adjusted tax items by tax year
- Relevant IRS news releases for threshold updates

The app will record the IRS source URL + reviewed date in report metadata.

## Packaging and distribution

Target packaging:
- `pyproject.toml` + `setup.py` setuptools package.
- Console script entrypoint:
  - `taxgrok = taxgrok.cli:main`
- Python 3.9+ baseline.
- Publishable to PyPI under package name `taxgrok` (if available; otherwise reserve fallback).
- Required env var: `XAI_API_KEY`

## Current status

Phases 1, 2, 3, and 4 are implemented:
- Installable local package with `taxgrok` CLI entrypoint.
- Interactive menu for add file, add folder, view queue, run analysis, and exit.
- Input filtering for `.txt`, `.md`, `.pdf`, `.png`.
- Config validation with clear errors for missing `XAI_API_KEY`.
- Local ingestion adapters for `.txt`, `.md`, `.pdf`, and `.png`.
- `.png` files are analyzed with xAI and normalized into markdown artifacts.
- Artifacts are uploaded run-scoped via xAI Files API and attached for retrieval generation.
- Generation uses `POST /v1/responses` first, with fallback to chat completions for compatibility.
- If all uploads fail, pipeline falls back to local-context mode (no remote file attachments).
- In local-context mode, extracted text (after local redaction when enabled) is sent as prompt content.
- If generation endpoints are denied (`403`/`1010`) or return empty text, pipeline falls back to local heuristic structured guidance.
- Strict JSON guidance schema is requested and rendered into final report sections.
- IRS source loader is integrated and writes reviewed-source metadata into report output.
- Remote uploaded files are deleted by default after generation.
- Report now includes federal filing checklist, what to file, reminders, mistakes, rough expectation, missing info, citations, and cleanup metadata.
- Optional local PII redaction pass before upload.
- PII-safe logging filter for runtime logs.
- Expanded unit/integration tests and CI workflow for lint/test/package checks.

## Quickstart (PHP Dashboard Integration)

The `solana-tax-tracker` directory houses the unified PHP dashboard for tracking Solana activity and analyzing tax documents with `taxgrok`.

**⚠️ Important:** The web dashboard *requires* the `taxgrok` python module to be installed on your machine so it can execute the xAI analysis pipeline in the background.

1. Create a `.env` file in the `solana-tax-tracker` directory and add your API keys:
   ```ini
   HELIUS_API_KEY="your_helius_key_here"  # Get a free key from helius.dev
   XAI_API_KEY="your_xai_key_here"        # Used as a fallback if not provided in the UI
   ```
2. Create and activate a virtual environment in the root directory and install `taxgrok`:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install .
   ```
3. Boot up the PHP development server inside the `solana-tax-tracker` directory:
   ```bash
   cd solana-tax-tracker
   php -S localhost:8000
   ```
4. Access the dashboard at `http://localhost:8000`. 
   The database (`soltracker.db`) will instantiate automatically on your first visit.

## Solana Tax Tracker UI Features
When running the integrated tracker UI you'll have access to:
- **Taxgrok AI Dashboard** — Simply upload your `.pdf` or `.png` tax forms right from the browser. Provide your `console.x.ai` API Key, filing status, and it dynamically generates a beautifully formatted markdown brief offering refund estimates and checklist points using xAI's visual and text reasoning models. Click **"Export PDF"** to produce a clean printable document.
- **Solana Multi-Wallet Tracking** — Add unlimited Solana wallet addresses. Click the sync button to pull parsed historical transaction data (Swaps, Transfers, NFT mints/sales) via the Helius RPC.
- **Local SQLite Persistence** — All your crypto transaction data and wallet labels are stored privately and safely on your local `soltracker.db` ledger.
- **CSV Export Engine** — Instantly filter your transaction ledgers and export them natively to CSV for handing off to TurboTax or your tax professional.

## Quickstart (Terminal CLI Only)

If you prefer operating without the Web UI:

1. Create and activate a virtual environment.
2. Install the project.
3. Export `XAI_API_KEY`.
4. Run `taxgrok`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
export XAI_API_KEY="your-xai-api-key"
taxgrok
```

## Global command setup (run from anywhere)

If `taxgrok` is not found outside this repo, create a global launcher symlink:

```bash
ln -sf "$PWD/.venv/bin/taxgrok" "$HOME/.local/bin/taxgrok"
```

Then verify:

```bash
command -v taxgrok
taxgrok --help
```

If `command -v taxgrok` is empty, ensure `~/.local/bin` is in your shell PATH.

For `zsh`, add this to `~/.zshrc` if needed:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

You can also put config in `.env` at repo/runtime directory:

```bash
cp .env.example .env
# then edit .env
```

Optional runtime env vars:
- `TAXGROK_MODEL` (default: `grok-4-fast`)
- `TAXGROK_TIMEOUT_SECONDS` (default: `90`)
- `TAXGROK_XAI_BASE_URL` (default: `https://api.x.ai`)
- `TAXGROK_KEEP_REMOTE_FILES=1` to disable auto-delete during debugging
- `TAXGROK_REFRESH_IRS_SOURCES=1` to run live IRS URL HEAD checks before generation
- `TAXGROK_LOCAL_REDACTION=0` to disable local PII redaction (enabled by default)
- `TAXGROK_NO_STYLE=1` to force plain menu mode (skip ASCII intro/dashboard)

Phase 3 notes:
- Startup includes a `taxgrok` Unicode intro and a dashboard-style menu in TTY terminals.
- Logo rendering is width-aware and auto-compacts for smaller terminal windows.
- `pypdf` is included as a package dependency for local PDF text extraction.
- If local PDF extraction quality is poor, the pipeline attempts an xAI OCR fallback before report generation.
- If OCR fallback still returns weak text, the original PDF is uploaded for retrieval as a final fallback.
- If structured JSON parsing fails, report generation falls back to raw model text and records a warning.
- If you see repeated `403` + `error code: 1010`, try `TAXGROK_XAI_BASE_URL=https://us-east-1.api.x.ai` and verify key permissions with xAI support.
- If all xAI generation endpoints fail, report generation continues with a local heuristic fallback and explicit low-confidence warnings.

CLI debug/security options:
- `taxgrok --debug-keep-remote-files`
- `taxgrok --refresh-irs-sources`
- `taxgrok --no-style`
- `taxgrok --local-redaction`
- `taxgrok --no-local-redaction`

Interactive run behavior:
- Analysis start prompts for taxpayer name and filing status before uploading/processing.
- Report filename uses the entered name (`TAXGROK-<sanitized-name>.md`) instead of OS username.
- While analysis runs, CLI shows a processing indicator until report generation completes.

## GitHub safety defaults

- `.env` and `.env.*` are ignored; keep secrets in `.env` only and never commit real keys.
- Generated reports (`TAXGROK-*.md`) are ignored by default.
- Local tax document folders are ignored by default (`morales-taxes-2025/`, `user-docs/`, `reports/`).
- Keep only sanitized examples in the repo (`.env.example` and synthetic test fixtures).

## Document quality tips

- Prefer text-based PDFs over scanned image PDFs when possible.
- For scans/screenshots, use high resolution and clear contrast (avoid blur/shadows).
- Crop large screenshots to just the relevant form area before upload.
- If extraction warnings mention missing/unclear fields, re-export/re-scan and rerun analysis.

## Quality and release

- CI workflow: `.github/workflows/ci.yml`
- Security notes: `SECURITY.md`
- Changelog: `CHANGELOG.md`
- Release and rollback checklist: `RELEASE.md`

## Locked v1 decisions

1. Single user profile per install

2. One-time use workflow
- Remote uploaded files are deleted after report generation.
- No persistent cloud index by default.

3. Federal scope only
- IRS/federal guidance only in v1 (no state-specific coverage).

4. PNG strategy
- PNG screenshots are analyzed and converted into text notes before reasoning.

5. Estimate strictness
- Report provides rough expectation ranges and qualitative drivers only, with explicit disclaimer.

## Tech Stack & Dependencies

- **Python 3.9+** — The powerful CLI analysis tool integrating `pypdf` for PII redaction and inference interactions.
- **PHP 8.0+** — Single file web-app architecture powering the Solana Tracker and executing the Python suite natively.
- **SQLite** — Embedded zero-config offline wallet ledgering.
- **Helius API** — Parsing Solana transactions.
- **xAI RAG API** — Analyzing visual tax data natively.

## References used for planning

xAI docs:
- https://docs.x.ai/docs/overview
- https://docs.x.ai/docs/api-reference
- https://docs.x.ai/docs/guides/rag
- https://docs.x.ai/docs/guides/collections
- https://docs.x.ai/docs/guides/chat-with-files
- https://docs.x.ai/docs/guides/images

IRS sources:
- https://www.irs.gov/forms-instructions
- https://www.irs.gov/publications/p17
- https://www.irs.gov/forms-pubs/about-form-1040
- https://www.irs.gov/newsroom/inflation-adjusted-tax-items-by-tax-year
- https://www.irs.gov/newsroom/tax-updates-and-news-from-the-irs
