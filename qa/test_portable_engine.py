"""Real native regression, not a mocked model or field-validation claim.

Runs on Linux CI and Windows. Evidence paths in the public summary are relative.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import subprocess
import sys
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend as b
from cloud_runtime import ensure_runtime


def main():
    runtime = ensure_runtime()
    workroot = ROOT / ".runtime" / "tests" / uuid.uuid4().hex[:12]
    workroot.mkdir(parents=True)
    results = []
    baseline = dict(mode="custom", total_mm=50, duration_min=10, recession_min=0,
                    drain_mm_h=30, storage_mm=20, inlet_area_m2=.2, infiltration_mm_h=0,
                    exchange_cap_s=1)
    cases = [
        ("dry", 0, 0, 0, 1, 30),
        ("rain", 100, 0, 0, 1, 30),
        ("ponded", 0, .2, 0, 1, 30),
        ("surcharge", 0, 0, 4, 1, 30),
        ("surcharge_fine", 0, 0, 4, .5, 30),
        ("surcharge_wet", 0, .2, 4, 1, 30),
        ("zero_outlet", 100, 0, 0, 1, 0),
        ("dry_fractional_long", 0, 0, 0, .687, 30),
        ("elevated_ponded", 0, .2, 0, 1, 30),
    ]
    for name, rain, surface_initial, tank_initial, cap, drain in cases:
        work = workroot / name
        work.mkdir()
        crest = 4.35 if name == "elevated_ponded" else 1.
        z = np.full((12, 12), crest)
        active = np.ones(z.shape, bool)
        state = np.zeros((3, *z.shape))
        state[0] = surface_initial
        duration = 25200 if name == "dry_fractional_long" else 600
        edges = np.array([0., float(duration)])
        rates = np.array([[rain / 1000 / 3600]])
        station = np.zeros(z.shape, np.int32)
        req = dict(baseline, exchange_cap_s=cap, drain_mm_h=drain)
        units = [dict(id="0", cell=78, crest=crest, support_area_m2=57600.)]
        b.write_binary(work / "input.bin", z, active, active, edges, rates, station,
                       closed=True, state=state)
        b.write_swmm(work, units, duration, req, initial_depth=tank_initial)
        with (work / "console.log").open("w", encoding="utf-8") as log:
            # Relative native filenames also work under Unicode Windows directories.
            process = subprocess.run(runtime["command"] + ["input.bin", ".", "model.inp", "units.csv"],
                                     cwd=work, stdout=log, stderr=subprocess.STDOUT, timeout=180,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if process.returncode:
            result = {"name": name, "passed": False, "returncode": process.returncode,
                      "error": (work / "console.log").read_text(encoding="utf-8", errors="replace")[-4000:]}
        else:
            result = b.validate_outputs(work, active, active, edges, rates, station)
            result["name"] = name
            result["synthetic_not_xinyi"] = True
            balance = result["balance"]
            extra = {"native_completion_marker": "COMPLETED_COUPLED" in (work / "console.log").read_text()}
            if name.startswith("dry"):
                extra["no_artificial_water"] = abs(balance["surface_stored_m3"] + balance["native_stored_m3"]) < 1e-8
            if name in ("rain", "ponded", "zero_outlet"):
                extra["water_enters_native"] = balance["to_network_m3"] > 0
            if name.startswith("surcharge"):
                extra["native_water_returns_to_surface"] = balance["to_surface_m3"] > 0
            if name == "zero_outlet":
                extra["zero_declared_outlet_has_zero_discharge"] = abs(balance["drain_m3"]) < 1e-8
            result["checks"].update(extra)
            result["passed"] = all(result["checks"].values())
        b.json_save(work / "result.json", result)
        results.append(result)
        print(name, result["passed"], result.get("combined_error_pct"), flush=True)
    checks = {}
    byname = {r["name"]: r for r in results}
    baseline_record = json.loads((ROOT / "qa" / "v2_native_baseline.json").read_text())
    coupling_source = (ROOT / "engine" / "NativeCoupling.cs").read_text().replace("\r\n", "\n")
    coupling_equations = coupling_source[coupling_source.index("    class Unit {"):]
    surface_source = (ROOT / "engine" / "SurfaceEngine.cs").read_text().replace("\r\n", "\n")
    checks["coupling_equations_unchanged_from_v2"] = hashlib.sha256(coupling_equations.encode()).hexdigest() == baseline_record["coupling_equations_sha256"]
    checks["surface_equations_unchanged_from_v2"] = hashlib.sha256(surface_source.encode()).hexdigest() == baseline_record["surface_equations_sha256"]
    for name, expected in baseline_record["cases"].items():
        actual_case = byname[name]
        checks[name + "_matches_v2_numerical_baseline"] = bool(actual_case["passed"] and all(
            abs((actual_case[metric] if metric == "max_depth_m" else actual_case["balance"][metric]) - value)
            <= max(1e-6, abs(value) * 1e-4) for metric, value in expected.items()))
    if all(r["passed"] for r in results):
        coarse, fine = byname["surcharge"]["balance"], byname["surcharge_fine"]["balance"]
        diff = abs(coarse["to_surface_m3"] - fine["to_surface_m3"]) / max(fine["to_surface_m3"], 1)
        checks["smaller_step_exchange_within_2pct"] = diff < .02
        checks["wet_surface_backpressure_reduces_return"] = (
            byname["surcharge_wet"]["balance"]["to_surface_m3"] < coarse["to_surface_m3"])
        checks["local_datum_translation_invariant"] = abs(
            byname["elevated_ponded"]["balance"]["to_network_m3"]
            - byname["ponded"]["balance"]["to_network_m3"]) < 1e-8
    else:
        diff = None
        checks["all_native_cases_passed"] = False
    summary = {
        "passed": all(r["passed"] for r in results) and all(checks.values()),
        "platform": platform.system(), "architecture": platform.machine(),
        "python": platform.python_version(), "cases": results, "checks": checks,
        "step_exchange_relative_difference": diff,
        "runtime": {k: runtime[k] for k in ("version", "engine_sha256", "library_sha256", "source_commit", "fingerprint")},
        "evidence_directory": str(workroot.relative_to(ROOT)).replace("\\", "/"),
        "scope": "Nine synthetic native regressions; not a full Xinyi event or field calibration.",
    }
    b.json_save(ROOT / "qa" / "portable_engine_tests.json", summary)
    print("ALL_PASSED", summary["passed"])
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
