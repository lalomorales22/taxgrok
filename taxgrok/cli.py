"""CLI entrypoint for taxgrok."""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import threading
import time
import sys

from .config import ConfigError, RuntimeConfig, load_runtime_config, sanitize_username
from .constants import EXIT_CONFIG_ERROR, EXIT_INTERRUPTED, EXIT_OK, EXIT_RUNTIME_ERROR
from .files import AddFolderResult, DocumentQueue
from .pipeline import PipelineError, run_phase3_pipeline
from .report import write_phase3_report
from .security import install_safe_logging_filter
from .taxpayer import (
    TaxpayerContext,
    filing_status_label,
    filing_status_options,
    parse_filing_status,
)
from .tui import build_dashboard, build_intro, clear_screen, supports_color, supports_dashboard

LOGGER = logging.getLogger("taxgrok")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taxgrok",
        description="Create a rough federal tax-prep briefing from user documents.",
    )
    parser.add_argument(
        "--username",
        help="Override local username used for TAXGROK-<username>.md output file.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for generated report (defaults to current directory).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--debug-keep-remote-files",
        action="store_true",
        help="Do not auto-delete uploaded remote files after generation (debug use only).",
    )
    parser.add_argument(
        "--refresh-irs-sources",
        action="store_true",
        help="Run live IRS source HEAD checks before generation.",
    )
    parser.add_argument(
        "--no-style",
        action="store_true",
        help="Disable ASCII intro and styled dashboard UI.",
    )
    redaction_group = parser.add_mutually_exclusive_group()
    redaction_group.add_argument(
        "--local-redaction",
        action="store_true",
        help="Enable local PII redaction pass before uploading artifacts.",
    )
    redaction_group.add_argument(
        "--no-local-redaction",
        action="store_true",
        help="Disable local PII redaction pass before uploading artifacts.",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    install_safe_logging_filter()


def prompt_input(label: str) -> str:
    try:
        return input(label).strip()
    except EOFError:
        return ""


def print_menu() -> None:
    print("")
    print("taxgrok menu")
    print("1) Add file")
    print("2) Add folder")
    print("3) View queue")
    print("4) Run analysis")
    print("5) Exit")


def pause_for_continue(*, dashboard_mode: bool) -> None:
    if dashboard_mode:
        prompt_input("Press Enter to continue...")


class LoadingIndicator:
    """Simple spinner shown while pipeline processing is in progress."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.enabled = sys.stdout.isatty()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            print(f"{self.message}...")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        frames = "|/-\\"
        index = 0
        while not self._stop_event.is_set():
            frame = frames[index % len(frames)]
            print(f"\r{self.message} {frame}", end="", flush=True)
            time.sleep(0.12)
            index += 1
        clear = " " * (len(self.message) + 4)
        print(f"\r{clear}\r", end="", flush=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


def _prompt_filing_status(default_code: str) -> str:
    options = filing_status_options()
    code_by_index = {str(idx): code for idx, (code, _) in enumerate(options, start=1)}
    while True:
        print("How are you filing?")
        for idx, (code, label) in enumerate(options, start=1):
            suffix = " (default)" if code == default_code else ""
            print(f"{idx}) {label}{suffix}")
        raw = prompt_input("Filing status [1-6]: ")
        if not raw:
            return default_code
        if raw in code_by_index:
            return code_by_index[raw]
        parsed = parse_filing_status(raw)
        if parsed is not None:
            return parsed
        print("Invalid filing status. Enter option number or text (e.g., single, mfj, hoh).")


def collect_taxpayer_context(
    *,
    config: RuntimeConfig,
    previous: TaxpayerContext | None,
) -> tuple[str, TaxpayerContext]:
    """Collect report name and filing-status context before analysis."""
    default_name = previous.display_name if previous is not None else config.username
    default_status = previous.filing_status if previous is not None else "unknown"

    entered_name = prompt_input(f"Taxpayer name for this report [{default_name}]: ")
    display_name = entered_name.strip() or default_name
    filing_status = _prompt_filing_status(default_status)

    report_id = sanitize_username(display_name)
    context = TaxpayerContext(display_name=display_name, filing_status=filing_status)
    print(
        f"Using profile: {context.display_name} ({filing_status_label(context.filing_status)}). "
        f"Report file: TAXGROK-{report_id}.md"
    )
    return report_id, context


def print_queue(queue: DocumentQueue) -> None:
    if not queue.items:
        print("Queue is empty.")
        return

    print("Queued files:")
    for index, path in enumerate(queue.items, start=1):
        print(f"{index}. {path}")


def handle_add_file(queue: DocumentQueue) -> None:
    path_input = prompt_input("Enter file path: ")
    if not path_input:
        print("No path provided.")
        return

    result = queue.add_file(path_input)
    if result.added:
        print(f"Added: {result.path}")
    else:
        print(f"Skipped: {result.path} ({result.reason})")


def handle_add_folder(queue: DocumentQueue) -> None:
    path_input = prompt_input("Enter folder path: ")
    if not path_input:
        print("No path provided.")
        return

    result: AddFolderResult = queue.add_folder(path_input)
    print(f"Added {len(result.added)} supported files.")

    if result.skipped:
        print(f"Skipped {len(result.skipped)} items.")
        for skipped in result.skipped[:10]:
            print(f"- {skipped.path}: {skipped.reason}")
        remaining = len(result.skipped) - 10
        if remaining > 0:
            print(f"- ... and {remaining} more skipped items")


def handle_run_analysis(
    queue: DocumentQueue,
    config: RuntimeConfig,
    *,
    taxpayer_context: TaxpayerContext | None,
) -> TaxpayerContext | None:
    if not queue.items:
        print("Queue is empty. Add files before running analysis.")
        return taxpayer_context

    report_id, collected_context = collect_taxpayer_context(
        config=config,
        previous=taxpayer_context,
    )
    run_config = replace(config, username=report_id)
    indicator = LoadingIndicator("Analyzing documents with taxgrok")
    indicator.start()

    try:
        result = run_phase3_pipeline(
            config=run_config,
            queued_files=list(queue.items),
            report_writer=write_phase3_report,
            taxpayer_context=collected_context,
        )
    except PipelineError as exc:
        indicator.stop()
        print(f"Analysis failed: {exc}")
        return collected_context
    except Exception as exc:
        indicator.stop()
        LOGGER.exception("Unexpected pipeline error.")
        print(f"Analysis failed with unexpected error: {exc}")
        return collected_context
    else:
        indicator.stop()

    print(f"Report written: {result.report_path}")
    if result.warnings:
        print(f"Warnings: {len(result.warnings)}")
        for warning in result.warnings[:10]:
            print(f"- {warning}")
        remaining = len(result.warnings) - 10
        if remaining > 0:
            print(f"- ... and {remaining} more warnings")
    print(f"Uploaded artifacts: {len(result.uploaded_artifacts)}")
    print(f"Remote files deleted: {len(result.cleanup.deleted_file_ids)}")
    if result.cleanup.delete_failures:
        print(f"Cleanup issues: {len(result.cleanup.delete_failures)} (see report)")

    queue.clear()
    print("Queue cleared for one-time-use workflow.")
    return collected_context


def run_menu(config: RuntimeConfig, *, use_style: bool = True) -> int:
    queue = DocumentQueue()
    taxpayer_context: TaxpayerContext | None = None
    dashboard_mode = use_style and supports_dashboard()
    styled = dashboard_mode and supports_color()

    if dashboard_mode:
        print(clear_screen(enabled=True), end="")
        print(build_intro(styled=styled))
        pause_for_continue(dashboard_mode=True)

    while True:
        if dashboard_mode:
            print(clear_screen(enabled=True), end="")
            print(
                build_dashboard(
                    config=config,
                    queued_paths=queue.items,
                    styled=styled,
                )
            )
        else:
            print_menu()
        choice = prompt_input("Select option [1-5]: ").lower()

        if choice in {"1", "add file", "file"}:
            handle_add_file(queue)
            pause_for_continue(dashboard_mode=dashboard_mode)
            continue
        if choice in {"2", "add folder", "folder"}:
            handle_add_folder(queue)
            pause_for_continue(dashboard_mode=dashboard_mode)
            continue
        if choice in {"3", "view", "list", "queue"}:
            print_queue(queue)
            pause_for_continue(dashboard_mode=dashboard_mode)
            continue
        if choice in {"4", "run", "analyze", "analysis"}:
            taxpayer_context = handle_run_analysis(
                queue,
                config,
                taxpayer_context=taxpayer_context,
            )
            pause_for_continue(dashboard_mode=dashboard_mode)
            continue
        if choice in {"5", "exit", "quit", "q"}:
            print("Exiting taxgrok.")
            return EXIT_OK

        print("Invalid option. Enter 1-5.")
        pause_for_continue(dashboard_mode=dashboard_mode)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    try:
        config = load_runtime_config(
            username_override=args.username,
            output_dir=args.output_dir,
            verbose=args.verbose,
            require_api_key=True,
        )
        if args.debug_keep_remote_files:
            config = replace(config, cleanup_remote_files=False)
        if args.refresh_irs_sources:
            config = replace(config, refresh_irs_sources=True)
        if args.local_redaction:
            config = replace(config, local_redaction=True)
        if args.no_local_redaction:
            config = replace(config, local_redaction=False)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except Exception as exc:
        print(f"Unexpected startup error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR

    LOGGER.debug("Runtime config resolved: output_dir=%s username=%s", config.output_dir, config.username)

    try:
        return run_menu(config, use_style=not args.no_style)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return EXIT_INTERRUPTED
    except Exception:
        LOGGER.exception("Unhandled error during session.")
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
