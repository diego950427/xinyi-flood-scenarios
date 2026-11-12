"""One-time explicit import of existing local validation, never run by app or CI.

Usage: python qa/capture_v2_native_baseline.py PATH_TO_VALIDATED_V2
Only numerical synthetic-case evidence and source hashes are published.
"""
from pathlib import Path
import hashlib
import json
import sys

source = Path(sys.argv[1]).resolve(strict=True)
qa = source / "qa" / "engine_tests.json"
previous = json.loads(qa.read_text(encoding="utf-8-sig"))
if not previous["passed"] or len(previous["cases"]) != 9:
    raise ValueError("Expected nine verified V2 cases")
metrics = ["rain_m3", "to_network_m3", "to_surface_m3", "drain_m3", "surface_stored_m3",
           "native_stored_m3", "time_s"]
cases = {r["name"]: {**{k: r["balance"][k] for k in metrics}, "max_depth_m": r["max_depth_m"]}
         for r in previous["cases"]}
text = (source / "engine" / "NativeCoupling.cs").read_text(encoding="utf-8-sig")
equations = text[text.index("    class Unit {"):].replace("\r\n", "\n")
surface = (source / "engine" / "SurfaceEngine.cs").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
record = {"scope": "Existing V2 verified synthetic regressions; not field calibration",
          "original_qa_sha256": hashlib.sha256(qa.read_bytes()).hexdigest(),
          "coupling_equations_sha256": hashlib.sha256(equations.encode()).hexdigest(),
          "surface_equations_sha256": hashlib.sha256(surface.encode()).hexdigest(),
          "reference_native_sha256": previous["native_dll_sha256"], "cases": cases}
(Path(__file__).parent / "v2_native_baseline.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
