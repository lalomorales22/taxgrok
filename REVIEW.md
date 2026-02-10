# taxgrok Security Review

Date: 2026-02-10

## Scope reviewed
- `/Users/megabrain2/Desktop/tax-man/README.md`
- `/Users/megabrain2/Desktop/tax-man/tasks.md`
- `/Users/megabrain2/Desktop/tax-man/CHANGELOG.md`
- `/Users/megabrain2/Desktop/tax-man/SECURITY.md`
- Core code paths in `/Users/megabrain2/Desktop/tax-man/taxgrok/`
- Tests in `/Users/megabrain2/Desktop/tax-man/tests/`
- Last generated run report: `/Users/megabrain2/Desktop/tax-man/TAXGROK-megabrain2.md`

## Executive summary
- No SQL usage exists in the current codebase, so SQL injection is not an active attack surface right now.
- No dynamic shell execution (`subprocess`, `os.system`) or dynamic code execution (`eval`, `exec`) paths were found.
- Default remote cleanup and logging redaction controls are present and working.
- A high-impact reliability/data-quality issue exists for image-only PDFs, and it likely explains the two failed PDFs in the last run.

## Checks performed
- Static scan for SQL/database usage:
  - `rg -n "sql|sqlite|execute\(|SELECT|INSERT|UPDATE|DELETE FROM|psycopg|mysql|sqlalchemy" ...`
  - Result: no matches.
- Static scan for command/code execution sinks:
  - `rg -n "subprocess|os\.system|eval\(|exec\(" taxgrok tests`
  - Result: no risky execution paths in app code.
- Test run:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 31 tests ... OK`.
- PDF failure triage (quick diagnostics):
  - `pdftotext` output for two failed PDFs was empty.
  - `pdfimages -list` shows both failed PDFs are image-only scans.

## Positive security controls already in place
- Input extension allowlist (`.txt`, `.md`, `.pdf`, `.png`): `/Users/megabrain2/Desktop/tax-man/taxgrok/files.py`
- API key required at startup: `/Users/megabrain2/Desktop/tax-man/taxgrok/config.py`
- Runtime log redaction filter for common PII patterns: `/Users/megabrain2/Desktop/tax-man/taxgrok/security.py`
- Optional local PII redaction before upload: `/Users/megabrain2/Desktop/tax-man/taxgrok/pipeline.py`
- Remote file cleanup enabled by default after generation: `/Users/megabrain2/Desktop/tax-man/taxgrok/pipeline.py`
- `.env` and local tax docs ignored by git: `/Users/megabrain2/Desktop/tax-man/.gitignore`

## Findings (ordered by severity)

### 1) High: image-only PDFs are not effectively recoverable in current pipeline
- Evidence:
  - PDF extraction fallback note is added when no text is available: `/Users/megabrain2/Desktop/tax-man/taxgrok/ingestion.py`
  - Pipeline uploads `doc.artifact_path` (generated markdown artifact), not the original source PDF: `/Users/megabrain2/Desktop/tax-man/taxgrok/pipeline.py`
  - Artifact content includes only normalized extracted text and notes: `/Users/megabrain2/Desktop/tax-man/taxgrok/ingestion.py`
- Impact:
  - For scanned/image-only PDFs, local extraction returns little/no text.
  - The uploaded artifact then also contains little/no source content, so xAI cannot recover fields from the original PDF.
  - This creates false confidence that PDF was "processed" while key tax fields are actually missing.
- Recommendation:
  - Upload original PDFs as attachments (or instead of artifacts for PDFs) when extraction quality is low.
  - Add OCR fallback for PDFs with no extractable text.
  - Add explicit "low extraction quality" warnings and a per-document status in output.

### 2) Medium: absolute local source paths are embedded in uploaded artifacts and reports
- Evidence:
  - Artifact writes `- Source path: <absolute path>`: `/Users/megabrain2/Desktop/tax-man/taxgrok/ingestion.py`
  - Report writes `- Source path: <absolute path>`: `/Users/megabrain2/Desktop/tax-man/taxgrok/report.py`
- Impact:
  - Leaks local machine path details (username, directory structure) to remote service and shared reports.
- Recommendation:
  - Replace absolute paths with file basename or stable document IDs in artifacts/reports.
  - Keep full path local only in debug logs (redacted/sanitized).

### 3) Medium: PII redaction is opt-in and heuristic
- Evidence:
  - Redaction runs only if `local_redaction` is enabled: `/Users/megabrain2/Desktop/tax-man/taxgrok/pipeline.py`
  - Pattern set is limited to common SSN/EIN/email/phone/account formats: `/Users/megabrain2/Desktop/tax-man/taxgrok/security.py`
- Impact:
  - Sensitive values may be uploaded by default in normal runs.
- Recommendation:
  - Consider enabling local redaction by default for `taxgrok` release.
  - Add `--no-local-redaction` for explicit opt-out.
  - Expand/test patterns and clearly label redaction limits.

### 4) Medium: remote cleanup is best-effort only
- Evidence:
  - Cleanup failures are recorded but do not halt/force retry: `/Users/megabrain2/Desktop/tax-man/taxgrok/pipeline.py`
- Impact:
  - Sensitive remote files can remain if delete fails.
- Recommendation:
  - Add retry with backoff for delete.
  - Surface cleanup failure as a stronger terminal status and final report banner.
  - Optionally provide a `cleanup --file-id ...` command for manual recovery.

### 5) Low: xAI base URL override is not domain-restricted
- Evidence:
  - Only checks `http://`/`https://`, not hostname allowlist: `/Users/megabrain2/Desktop/tax-man/taxgrok/config.py`
- Impact:
  - Misconfiguration or malicious local `.env` could send API key and document data to non-xAI endpoints.
- Recommendation:
  - Default allowlist to `api.x.ai` and expected regional hosts.
  - Add explicit override flag/env for advanced self-hosted testing.

### 6) Low: uploads are read fully into memory, no file-size safety limits
- Evidence:
  - `file_path.read_bytes()` in multipart upload: `/Users/megabrain2/Desktop/tax-man/taxgrok/xai_client.py`
- Impact:
  - Large files can spike memory or degrade app stability.
- Recommendation:
  - Enforce max input/upload size.
  - Stream multipart payloads where possible.

## SQL injection conclusion
Confirmed: there are no SQL/database query paths in this codebase today, so SQL injection is not currently possible through this application.

## Two failed PDFs: quick root-cause notes
- Failed docs from last run:
  - `/Users/megabrain2/Desktop/tax-man/morales-taxes-2025/Morales2026-Jessica-W2-SDUSD.pdf`
  - `/Users/megabrain2/Desktop/tax-man/morales-taxes-2025/Morales2026-Lalo-1099.pdf`
- Observed in report:
  - Both were marked with extraction note: `No extractable text found in PDF pages.`
- File diagnostics:
  - Both appear to be image-based iOS Quartz PDFs.
  - `pdftotext` produced no text for both.
  - `pdfimages -list` shows single full-page image objects (scan-like PDFs).
- Why they failed in this implementation:
  - No OCR fallback is currently applied to PDF pages.
  - Artifact upload path sends normalized markdown text, not original PDF bytes, so server-side recovery from the original scan does not happen.

## Recommended next steps before `taxgrok` release
1. Fix PDF path: upload original PDFs when extraction quality is low, and add OCR fallback.
2. Remove absolute local paths from remote artifacts and final reports.
3. Default local redaction to ON for production-safe behavior.
4. Harden remote cleanup behavior with retry/escalation.
5. Restrict base URL to known xAI hosts by default.
6. For branding/rename (`taxgrok` -> `taxgrok`): preserve all security defaults during package/CLI rename and add regression tests for these controls.
