"""IRS source loading and optional refresh helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request


@dataclass(frozen=True)
class IRSSource:
    """One IRS source entry plus lightweight refresh metadata."""

    name: str
    url: str
    reviewed_at_utc: str
    status_code: int | None = None
    last_modified: str | None = None
    error: str | None = None


CURATED_IRS_SOURCES: tuple[tuple[str, str], ...] = (
    ("Forms, Instructions and Publications", "https://www.irs.gov/forms-instructions"),
    ("Publication 17", "https://www.irs.gov/publications/p17"),
    ("Form 1040 overview", "https://www.irs.gov/forms-pubs/about-form-1040"),
    (
        "Inflation-adjusted tax items by year",
        "https://www.irs.gov/newsroom/inflation-adjusted-tax-items-by-tax-year",
    ),
    ("IRS tax updates and news", "https://www.irs.gov/newsroom/tax-updates-and-news-from-the-irs"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _refresh_url(url: str, timeout_seconds: int) -> tuple[int | None, str | None, str | None]:
    req = urllib_request.Request(url=url, method="HEAD")
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            headers = response.headers
            status_code = getattr(response, "status", None)
            last_modified = headers.get("Last-Modified")
            return status_code, last_modified, None
    except urllib_error.HTTPError as exc:
        # Many sites reject HEAD. Keep status and continue.
        return exc.code, None, f"HTTPError: {exc.reason}"
    except urllib_error.URLError as exc:
        return None, None, f"URLError: {exc.reason}"
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def load_irs_sources(*, refresh: bool = False, timeout_seconds: int = 8) -> list[IRSSource]:
    """Return curated IRS sources with reviewed time and optional HEAD checks."""
    reviewed_at = _utc_now()
    output: list[IRSSource] = []
    for name, url in CURATED_IRS_SOURCES:
        status_code: int | None = None
        last_modified: str | None = None
        error: str | None = None
        if refresh:
            status_code, last_modified, error = _refresh_url(url, timeout_seconds)
        output.append(
            IRSSource(
                name=name,
                url=url,
                reviewed_at_utc=reviewed_at,
                status_code=status_code,
                last_modified=last_modified,
                error=error,
            )
        )
    return output


def format_irs_sources_for_prompt(sources: Iterable[IRSSource]) -> str:
    """Compact IRS source list to embed in system prompt."""
    rows: list[str] = []
    for source in sources:
        status = str(source.status_code) if source.status_code is not None else "unchecked"
        rows.append(
            f"- {source.name} | {source.url} | reviewed={source.reviewed_at_utc} | status={status}"
        )
    return "\n".join(rows)
