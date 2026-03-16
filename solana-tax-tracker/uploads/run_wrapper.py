import os
import sys
import traceback
from pathlib import Path

from taxgrok.config import load_runtime_config
from taxgrok.pipeline import run_phase3_pipeline
from taxgrok.report import write_phase3_report
from taxgrok.taxpayer import TaxpayerContext

try:
    files_to_process = [Path(p) for p in sys.argv[1:]]
    name = os.environ.get('USER_NAME', 'User')
    status = os.environ.get('USER_STATUS', 'unknown')

    config = load_runtime_config(
        username_override=name,
        output_dir=os.getcwd(),  # Output in the working directory
        verbose=False,
        require_api_key=True
    )
    # Force the user requested model explicitly after loading config
    from dataclasses import replace
    config = replace(config, model="grok-4-fast-reasoning")
    
    context = TaxpayerContext(display_name=name, filing_status=status)

    # Run pipeline
    result = run_phase3_pipeline(
        config=config,
        queued_files=files_to_process,
        report_writer=write_phase3_report,
        taxpayer_context=context
    )
    print(f"Report written: {result.report_path}")
except Exception as exc:
    print(f"Error: Pipeline failed: {exc}")
    traceback.print_exc()
    sys.exit(1)