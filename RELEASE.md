# Release and Rollback

## Prerequisites

- Clean working tree.
- Passing local tests.
- GitHub repo admin access.
- PyPI project owner/maintainer access.

## Release steps

1. Update version in:
- `setup.py`
- `taxgrok/__init__.py`

2. Update `CHANGELOG.md` with release date and notes.

3. Run local quality gates:

```bash
python3 -m pip install ruff build twine
ruff check .
python3 -m unittest discover -s tests -v
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
VERSION=0.1.2
git add .
git commit -m "release: ${VERSION}"
git tag -a "v${VERSION}" -m "taxgrok v${VERSION}"
git push origin main --tags
```

6. Publish to PyPI:

```bash
gh release create "v${VERSION}" --title "taxgrok v${VERSION}" --notes-file CHANGELOG.md
```

Publishing happens automatically when the GitHub release is published via
`.github/workflows/pypi-publish.yml` using PyPI Trusted Publishing (OIDC).

7. Verify install:

```bash
python3 -m venv /tmp/taxgrok-release-check
source /tmp/taxgrok-release-check/bin/activate
pip install taxgrok
taxgrok --help
```

## One-time GitHub hardening setup

1. Branch protection (`main`)
- Require pull request before merging.
- Require status checks to pass before merging.
- Select required checks from CI + security workflows:
  - `CI / test (3.9)`
  - `CI / test (3.10)`
  - `CI / test (3.11)`
  - `CI / test (3.12)`
  - `Secret Scan / Gitleaks`
- Require conversation resolution before merging.
- Restrict force pushes and branch deletion.

2. Security settings
- Enable Dependabot alerts.
- Enable Dependabot security updates.
- Enable secret scanning and push protection (when available for the repo plan).

3. PyPI Trusted Publisher
- In PyPI project settings, add a trusted publisher with:
  - Owner: `lalomorales22`
  - Repository: `taxgrok`
  - Workflow: `.github/workflows/pypi-publish.yml`
  - Environment: `pypi`

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
