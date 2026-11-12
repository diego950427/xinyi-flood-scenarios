"""Mark this CI attempt NOT_RUN before any dependency/build step can fail.

The repository may carry a prior local verification report. Never upload that
prior PASS as if it were a result produced by this Linux workflow attempt.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Only initialize ephemeral GitHub Actions checkout reports.")

report_names = (
    "portable_engine_tests.json", "full_domain_custom.json", "cloud_app_tests.json",
    "charts_tests.json", "data_release_audit.json",
)
base = Path(__file__).resolve().parent
for name in report_names:
    record = {
        "passed": False, "status": "NOT_RUN", "executed": False,
        "platform": platform.system(),
        "commit": os.environ.get("GITHUB_SHA"), "run_id": os.environ.get("GITHUB_RUN_ID"),
        "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "initialized_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "This attempt has not produced evidence for this check yet.",
    }
    (base / name).write_text(json.dumps(record, indent=2), encoding="utf-8")
print("Initialized five reports as NOT_RUN; no prior PASS can be reused.")
