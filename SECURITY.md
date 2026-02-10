# Security notes

## PII handling defaults

- Taxgrok is designed for one-time report generation workflows.
- Remote uploaded artifacts are deleted by default after generation.
- Runtime logs use a redaction filter to mask common PII patterns.
- Local PII redaction is enabled by default before artifact upload.

## Local redaction controls

Disable with:

```bash
export TAXGROK_LOCAL_REDACTION=0
```

or:

```bash
taxgrok --no-local-redaction
```

When local redaction is enabled, common patterns are redacted before artifact upload:
- SSN-like numbers
- EIN-like numbers
- Email addresses
- US phone numbers
- Long account-number-like digit sequences

## Debug mode warning

`--debug-keep-remote-files` (or `TAXGROK_KEEP_REMOTE_FILES=1`) keeps uploaded files on xAI for debugging.
Use only when needed and avoid with sensitive data.

## Limitations

- Pattern redaction is heuristic and not a guarantee of full PII removal.
- For image-only PDFs with poor local extraction, the pipeline may upload the original PDF as a retrieval fallback.
- If file uploads fail but generation endpoints are still available, local-context mode sends extracted text as prompt content.
- Always review generated output and source handling practices for your compliance requirements.

## GitHub safety checklist

Before pushing this repository to GitHub:

1. Ensure `.env` and any real keys are not committed (`.env` is ignored; keep only `.env.example`).
2. Do not commit personal tax source files or generated reports (for example `TAXGROK-*.md`).
3. Rotate keys immediately if a key was ever pasted into code, logs, commits, or issue threads.
4. Keep local redaction enabled (default) when processing sensitive records.
5. Review changed files for accidental identifiers (SSN/EIN/account numbers) before every push/PR.
