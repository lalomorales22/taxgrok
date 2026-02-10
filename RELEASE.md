# Release and Rollback

## Prerequisites

- PyPI token with publish access for `taxgrok`.
- Clean working tree.
- Passing local tests.

## Release steps

1. Update version in:
- `setup.py`
- `taxgrok/__init__.py`

2. Update `CHANGELOG.md` with release date and notes.

3. Run local quality gates:

```bash
python3 -m unittest discover -s tests -v
python3 -m pip install build twine
python3 -m build
python3 -m twine check dist/*
```

4. Run GitHub safety preflight (no secrets/PII):

```bash
ls -la .env .env.example
git ls-files -z | xargs -0 rg -n "xai-[A-Za-z0-9]{24,}|sk-|BEGIN PRIVATE KEY|SSN|social security" || true
git ls-files --error-unmatch .env >/dev/null 2>&1 && { echo "ERROR: .env is tracked. Remove it before release."; exit 1; } || true
```

5. Commit + tag release:

```bash
git add .
git commit -m "release: 0.1.1"
git tag -a v0.1.1 -m "taxgrok v0.1.1"
git push origin main --tags
```

6. Publish to PyPI:

```bash
python3 -m twine upload dist/*
```

7. Verify install:

```bash
python3 -m venv /tmp/taxgrok-release-check
source /tmp/taxgrok-release-check/bin/activate
pip install taxgrok
taxgrok --help
```

## Rollback / mitigation

If a bad release is published:

1. Do not delete release files on PyPI.
2. Cut a new patch version (for example `0.1.2`) with the fix.
3. Rebuild and republish using the same release flow.
4. Document the corrective release in `CHANGELOG.md`.

## Versioning policy

- Use semantic versioning.
- `MAJOR`: breaking CLI or report schema changes.
- `MINOR`: new features that remain backward compatible.
- `PATCH`: bugfixes, security fixes, and non-breaking polish.
