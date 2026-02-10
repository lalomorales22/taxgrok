"""File and folder queue handling for supported taxgrok input types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import SUPPORTED_EXTENSIONS


@dataclass(frozen=True)
class SkippedFile:
    """A file skipped during queueing with reason."""

    path: Path
    reason: str


@dataclass(frozen=True)
class AddFileResult:
    """Result of attempting to add one file."""

    added: bool
    path: Path
    reason: str = ""


@dataclass(frozen=True)
class AddFolderResult:
    """Result of attempting to add one folder."""

    added: list[Path]
    skipped: list[SkippedFile]


class DocumentQueue:
    """In-memory queue for files selected in the current run."""

    def __init__(self) -> None:
        self._items: list[Path] = []
        self._seen: set[str] = set()

    @property
    def items(self) -> tuple[Path, ...]:
        return tuple(self._items)

    def clear(self) -> None:
        self._items.clear()
        self._seen.clear()

    def add_file(self, path_like: str | Path) -> AddFileResult:
        path = Path(path_like).expanduser()
        if not path.exists():
            return AddFileResult(False, path, "file does not exist")
        if not path.is_file():
            return AddFileResult(False, path, "path is not a file")

        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            shown_extension = extension if extension else "<none>"
            return AddFileResult(False, path, f"unsupported extension '{shown_extension}'")

        resolved = path.resolve()
        key = str(resolved)
        if key in self._seen:
            return AddFileResult(False, resolved, "already queued")

        self._items.append(resolved)
        self._seen.add(key)
        return AddFileResult(True, resolved)

    def add_folder(self, folder_like: str | Path) -> AddFolderResult:
        folder = Path(folder_like).expanduser()
        if not folder.exists():
            return AddFolderResult([], [SkippedFile(folder, "folder does not exist")])
        if not folder.is_dir():
            return AddFolderResult([], [SkippedFile(folder, "path is not a folder")])

        added: list[Path] = []
        skipped: list[SkippedFile] = []
        candidates = sorted(
            (path for path in folder.rglob("*") if path.is_file()),
            key=lambda path: str(path),
        )
        for candidate in candidates:
            result = self.add_file(candidate)
            if result.added:
                added.append(result.path)
            else:
                skipped.append(SkippedFile(result.path, result.reason))
        return AddFolderResult(added, skipped)
