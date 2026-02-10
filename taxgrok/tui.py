"""Minimal terminal dashboard helpers for taxgrok."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable, TextIO

from .config import RuntimeConfig

_RESET = "\033[0m"
_BLACK = (0, 0, 0)
_FG_PRIMARY = (225, 228, 232)
_FG_MUTED = (134, 143, 153)
_FG_ACCENT = (120, 214, 255)

_LOGO_LINES: tuple[str, ...] = (
    "     █████████████ ██",
    "   ███████████████████        ███                                █████████                        █████",
    " ██████░░░░░░░░░██████░       ████                             ████████████                       █████░",
    "█████░░░░░░░░██████████░    █████████ █████████  █████  █████ ██████░░░░██░░ ████████  █████████  █████░██████",
    "███░░░░░░░░██████░░░████░   █████████░██████████  ██████████░█████░░░██████░░████████████████████ ███████████░░",
    "███░░░░░░█████░░░░░░████░░   ░████░░░░██████████░  ░██████░░░█████░░░██████░░████░░░░████░░░░████░████████░░░░░░",
    "███░░░░█████░░░░░░░░████░░   ███████░███████████░░ ████████░░░███████░░████░░████░░░░██████░█████░██████████░░░░░",
    "██████████░░░░░░░░░████░░░░   ██████████████████░██████░█████░░████████████░░████░░░░░██████████░░█████░██████░░░░",
    " ███████░░░░░░░░░░████░░░░░░   ░████░░░████░░███░████░░░░████░░░░░███████░░░░████░░░░░░░██████░░░░░███░░░░████░░░",
    "██████████████░░░░ ░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░░   ░░░░░░░░░░░░░░░░░░░░░░░░",
    "████░█████████░░    ░░░░░░░░     ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  ░░░░░░░░░░░░░░░░░░░    ░░░░░░░░░░░░░░░░░░░░░░░░",
    " ░░░░░░░░░░░░░░░     ░░░░░░       ░░░░░░░░░░░░░░░░░░░░░░░░░ ░░░░░  ░░░░░░░░░░░░ ░░░░░     ░░░░░░░░░░  ░░░░░ ░░░░░░",
    "  ░░░░░░░░░░░░░░░     ░░░░          ░░░░   ░░░░  ░░░ ░░░░    ░░░░     ░░░░░░░    ░░░░       ░░░░░░     ░░░    ░░░░",
    "   ░░░░░░░░░░░░░░░",
    "    ░░░░ ░░░░░░░░░",
)

_MENU_LINES: tuple[str, ...] = (
    "1) Add file",
    "2) Add folder",
    "3) View queue",
    "4) Run analysis",
    "5) Exit",
)

_COMPACT_LOGO_LINES: tuple[str, ...] = (
    "████████╗ █████╗ ██╗  ██╗ ██████╗ ██████╗  ██████╗ ██╗  ██╗",
    "╚══██╔══╝██╔══██╗╚██╗██╔╝██╔════╝ ██╔══██╗██╔═══██╗██║ ██╔╝",
    "   ██║   ███████║ ╚███╔╝ ██║  ███╗██████╔╝██║   ██║█████╔╝ ",
    "   ██║   ██╔══██║ ██╔██╗ ██║   ██║██╔══██╗██║   ██║██╔═██╗ ",
    "   ██║   ██║  ██║██╔╝ ██╗╚██████╔╝██║  ██║╚██████╔╝██║  ██╗",
    "   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝",
)


def _bool_env(name: str) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def supports_dashboard(stream: TextIO | None = None) -> bool:
    """Return True when terminal dashboard rendering should be used."""
    output = stream or sys.stdout
    if _bool_env("TAXGROK_NO_STYLE"):
        return False
    if not output.isatty():
        return False
    term = os.getenv("TERM", "").strip().lower()
    return term not in {"", "dumb"}


def supports_color(stream: TextIO | None = None) -> bool:
    """Return True when ANSI color styling is safe to emit."""
    if os.getenv("NO_COLOR") is not None:
        return False
    return supports_dashboard(stream=stream)


def _style(
    text: str,
    *,
    fg: tuple[int, int, int] | None = None,
    bg: tuple[int, int, int] | None = None,
    bold: bool = False,
    dim: bool = False,
    enabled: bool,
) -> str:
    if not enabled:
        return text

    codes: list[str] = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if fg is not None:
        codes.append(f"38;2;{fg[0]};{fg[1]};{fg[2]}")
    if bg is not None:
        codes.append(f"48;2;{bg[0]};{bg[1]};{bg[2]}")
    if not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}{_RESET}"


def clear_screen(*, enabled: bool) -> str:
    """Return ANSI clear-screen sequence when enabled."""
    if not enabled:
        return ""
    return "\033[2J\033[H"


def _terminal_width(width: int | None = None) -> int:
    if width is not None:
        return max(30, width)
    return max(30, shutil.get_terminal_size(fallback=(100, 30)).columns)


def _center(text: str, width: int) -> str:
    if len(text) >= width:
        return text
    pad = (width - len(text)) // 2
    return (" " * pad) + text


def _wrap_line(text: str, width: int) -> list[str]:
    if width <= 1:
        return [text]
    if len(text) <= width:
        return [text]

    wrapped: list[str] = []
    value = text
    while len(value) > width:
        chunk = value[:width]
        split = chunk.rfind(" ")
        if split < width // 2:
            split = width
        wrapped.append(value[:split].rstrip())
        value = value[split:].lstrip()
    wrapped.append(value)
    return wrapped


def _squeeze_space_runs(line: str, *, max_run: int) -> str:
    trimmed = line.rstrip()
    if max_run < 1:
        return re.sub(r" +", " ", trimmed)

    def repl(match: re.Match[str]) -> str:
        run_len = len(match.group(0))
        return " " * min(run_len, max_run)

    return re.sub(r" {2,}", repl, trimmed)


def _fit_logo_lines(width: int) -> tuple[str, ...]:
    """Return width-fitted logo lines, preserving the exact logo when possible."""
    base = tuple(line.rstrip() for line in _LOGO_LINES)
    if max(len(line) for line in base) <= width:
        return base

    for max_run in (10, 8, 6, 4, 3, 2, 1):
        candidate = tuple(_squeeze_space_runs(line, max_run=max_run) for line in base)
        if max(len(line) for line in candidate) <= width:
            return candidate

    compact = tuple(line.rstrip() for line in _COMPACT_LOGO_LINES)
    if max(len(line) for line in compact) <= width:
        return compact

    fallback = "taxgrok"
    return (fallback[: max(1, width)],)


def _panel(
    title: str,
    lines: Iterable[str],
    *,
    width: int,
    styled: bool,
) -> str:
    inner = max(10, width - 4)
    border = "+" + ("-" * (inner + 2)) + "+"
    header = f"| {title:<{inner}} |"

    rows: list[str] = [border, header, border]
    for line in lines:
        wrapped = _wrap_line(line, inner)
        for item in wrapped:
            rows.append(f"| {item:<{inner}} |")
    rows.append(border)

    if not styled:
        return "\n".join(rows)

    colored: list[str] = []
    for idx, row in enumerate(rows):
        if idx in {0, 2, len(rows) - 1}:
            colored.append(_style(row, fg=_FG_MUTED, bg=_BLACK, enabled=True))
        elif idx == 1:
            colored.append(_style(row, fg=_FG_ACCENT, bg=_BLACK, bold=True, enabled=True))
        else:
            colored.append(_style(row, fg=_FG_PRIMARY, bg=_BLACK, enabled=True))
    return "\n".join(colored)


def build_intro(*, styled: bool, width: int | None = None) -> str:
    """Build startup intro text with ASCII logo."""
    resolved_width = _terminal_width(width)
    logo_lines = _fit_logo_lines(max(12, resolved_width - 2))
    lines: list[str] = []
    for raw in logo_lines:
        centered = _center(raw, resolved_width)
        lines.append(_style(centered, fg=_FG_ACCENT, bg=_BLACK, bold=True, enabled=styled))
    subtitle = _center("taxgrok | federal tax briefing dashboard", resolved_width)
    lines.append(_style(subtitle, fg=_FG_PRIMARY, bg=_BLACK, enabled=styled))
    lines.append(_style(_center("private-by-default, practical output", resolved_width), fg=_FG_MUTED, bg=_BLACK, dim=True, enabled=styled))
    return "\n".join(lines)


def build_dashboard(
    *,
    config: RuntimeConfig,
    queued_paths: tuple[Path, ...],
    styled: bool,
    width: int | None = None,
) -> str:
    """Build dashboard screen with session info, queue preview, and actions."""
    resolved_width = _terminal_width(width)
    panel_width = min(96, resolved_width - 2)
    queue_count = len(queued_paths)
    queue_preview = [f"- {path.name}" for path in queued_paths[:5]]
    if not queue_preview:
        queue_preview = ["- Queue is empty."]
    if queue_count > 5:
        queue_preview.append(f"- ... and {queue_count - 5} more file(s).")

    status_lines = [
        f"User: {config.username}",
        f"Model: {config.model}",
        f"Output file: TAXGROK-{config.username}.md",
        f"Queue items: {queue_count}",
        (
            "Security: local redaction="
            + ("ON" if config.local_redaction else "OFF")
            + ", remote cleanup="
            + ("ON" if config.cleanup_remote_files else "OFF")
        ),
        f"IRS refresh on run: {'ON' if config.refresh_irs_sources else 'OFF'}",
    ]

    menu_lines = list(_MENU_LINES)

    sections = [
        _panel(" Session ", status_lines, width=panel_width, styled=styled),
        _panel(" Queue Preview ", queue_preview, width=panel_width, styled=styled),
        _panel(" Actions ", menu_lines, width=panel_width, styled=styled),
    ]
    return "\n\n".join(sections)
