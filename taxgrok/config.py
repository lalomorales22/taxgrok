"""Runtime configuration loading for taxgrok."""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import re

from .constants import DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, XAI_BASE_URL


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid or missing."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Values needed to run the CLI session."""

    xai_api_key: str
    username: str
    output_dir: Path
    model: str
    timeout_seconds: int
    cleanup_remote_files: bool
    refresh_irs_sources: bool
    local_redaction: bool
    xai_base_url: str = XAI_BASE_URL
    verbose: bool = False


def _parse_bool_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value == "":
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(
        f"Invalid {name} value '{raw}'. Expected one of: 1,true,yes,on,0,false,no,off."
    )


def sanitize_username(raw_value: str) -> str:
    """Map user-provided names to a stable filesystem-safe identifier."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_value).strip("-_.")
    return cleaned or "user"


def resolve_username(override: str | None = None) -> str:
    """Resolve username from explicit arg, env, or OS user."""
    candidates = [
        override,
        os.getenv("TAXGROK_USERNAME"),
        os.getenv("USER"),
        os.getenv("USERNAME"),
    ]
    for candidate in candidates:
        if candidate and candidate.strip():
            return sanitize_username(candidate.strip())

    try:
        return sanitize_username(getpass.getuser())
    except Exception:
        return "user"


def load_runtime_config(
    *,
    username_override: str | None = None,
    output_dir: str | Path | None = None,
    verbose: bool = False,
    require_api_key: bool = True,
) -> RuntimeConfig:
    """Build and validate runtime config from environment + CLI args."""
    _load_dotenv(Path.cwd() / ".env")
    xai_api_key = os.getenv("XAI_API_KEY", "").strip()
    if require_api_key and not xai_api_key:
        raise ConfigError(
            "Missing XAI_API_KEY. Set it before running taxgrok.\n"
            "Example:\n"
            "  export XAI_API_KEY='your-key-here'"
        )

    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else Path.cwd()
    try:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"Unable to create output directory '{resolved_output_dir}': {exc}") from exc

    if not resolved_output_dir.is_dir():
        raise ConfigError(f"Output path is not a directory: {resolved_output_dir}")

    model = os.getenv("TAXGROK_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    xai_base_url = os.getenv("TAXGROK_XAI_BASE_URL", XAI_BASE_URL).strip() or XAI_BASE_URL
    if not re.match(r"^https?://", xai_base_url):
        raise ConfigError("TAXGROK_XAI_BASE_URL must start with http:// or https://.")
    timeout_raw = os.getenv("TAXGROK_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)).strip()
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise ConfigError(
            f"Invalid TAXGROK_TIMEOUT_SECONDS value '{timeout_raw}'. Expected integer seconds."
        ) from exc
    if timeout_seconds <= 0:
        raise ConfigError("TAXGROK_TIMEOUT_SECONDS must be greater than zero.")

    keep_remote_files = _parse_bool_env("TAXGROK_KEEP_REMOTE_FILES", default=False)
    refresh_irs_sources = _parse_bool_env("TAXGROK_REFRESH_IRS_SOURCES", default=False)
    local_redaction = _parse_bool_env("TAXGROK_LOCAL_REDACTION", default=True)

    return RuntimeConfig(
        xai_api_key=xai_api_key,
        username=resolve_username(username_override),
        output_dir=resolved_output_dir,
        model=model,
        timeout_seconds=timeout_seconds,
        xai_base_url=xai_base_url.rstrip("/"),
        cleanup_remote_files=not keep_remote_files,
        refresh_irs_sources=refresh_irs_sources,
        local_redaction=local_redaction,
        verbose=verbose,
    )


def _load_dotenv(path: Path) -> None:
    """Best-effort local .env loader that does not override existing env vars."""
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
            parsed = parsed[1:-1]
        os.environ.setdefault(key, parsed)
