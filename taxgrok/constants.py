"""Shared constants for taxgrok."""

from __future__ import annotations

EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_INTERRUPTED = 130

SUPPORTED_EXTENSIONS = frozenset({".txt", ".md", ".pdf", ".png"})

DEFAULT_MODEL = "grok-4-fast"
DEFAULT_TIMEOUT_SECONDS = 90

XAI_BASE_URL = "https://api.x.ai"
