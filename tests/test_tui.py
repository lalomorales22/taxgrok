from __future__ import annotations

from pathlib import Path
import unittest

from taxgrok.config import RuntimeConfig
from taxgrok.tui import build_dashboard, build_intro


class TUITests(unittest.TestCase):
    def _config(self) -> RuntimeConfig:
        return RuntimeConfig(
            xai_api_key="test-key",
            username="tester",
            output_dir=Path.cwd(),
            model="grok-test",
            timeout_seconds=10,
            cleanup_remote_files=True,
            refresh_irs_sources=False,
            local_redaction=True,
            verbose=False,
        )

    def test_build_intro_plain_contains_branding(self) -> None:
        text = build_intro(styled=False, width=80)
        self.assertIn("taxgrok | federal tax briefing dashboard", text)
        self.assertIn("private-by-default, practical output", text)

    def test_build_intro_keeps_exact_logo_when_width_allows(self) -> None:
        text = build_intro(styled=False, width=140)
        self.assertIn(
            "██████████░░░░░░░░░████░░░░   ██████████████████░██████░█████░░████████████░░████░░░░░██████████░░█████░██████░░░░",
            text,
        )

    def test_build_intro_fits_small_width(self) -> None:
        width = 72
        text = build_intro(styled=False, width=width)
        max_line = max(len(line) for line in text.splitlines())
        self.assertLessEqual(max_line, width)

    def test_build_dashboard_plain_contains_core_status(self) -> None:
        config = self._config()
        text = build_dashboard(
            config=config,
            queued_paths=(Path("/tmp/w2.pdf"), Path("/tmp/notes.md")),
            styled=False,
            width=76,
        )
        self.assertIn("Output file: TAXGROK-tester.md", text)
        self.assertIn("Queue items: 2", text)
        self.assertIn("local redaction=ON", text)
        self.assertIn("remote cleanup=ON", text)
        self.assertIn("- w2.pdf", text)
        self.assertIn("- notes.md", text)
        self.assertIn("1) Add file", text)

    def test_build_dashboard_shows_overflow_count(self) -> None:
        config = self._config()
        queued = tuple(Path(f"/tmp/doc-{i}.pdf") for i in range(1, 8))
        text = build_dashboard(config=config, queued_paths=queued, styled=False, width=76)
        self.assertIn("Queue items: 7", text)
        self.assertIn("... and 2 more file(s).", text)


if __name__ == "__main__":
    unittest.main()
