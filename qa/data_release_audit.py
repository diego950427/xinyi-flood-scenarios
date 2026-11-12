"""Offline release-data checks; no solver or licensing claims are inferred from PASS."""
from pathlib import Path
import hashlib
import json
import re
import sys

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks = {}
    manifest = read(ROOT / "data/public_manifest.json")
    checks["all_public_data_hashes_match"] = all(
        (ROOT / "data" / r["file"]).is_file() and sha(ROOT / "data" / r["file"]) == r["release_sha256"]
        for r in manifest["files"])
    checks["unchanged_numeric_files_match_v2"] = all(
        r["v2_sha256"] == r["release_sha256"] for r in manifest["files"] if not r["metadata_paths_sanitized"])
    checks["metadata_numeric_values_preserved_at_packaging"] = all(r["numeric_values_preserved"] for r in manifest["files"])
    leaks = []
    text_suffixes = {".json", ".geojson", ".csv", ".txt", ".xml", ".qgs", ".log", ".inp"}
    scans = []
    for base in [ROOT / "data", ROOT / "examples"]:
        for p in base.rglob("*"):
            if p.is_file():
                scans.append(p)
                if p.suffix in text_suffixes:
                    text = p.read_text(encoding="utf-8-sig")
                    # Values are never printed. Only filenames identify a finding.
                    if re.search(r"[A-Za-z]:[\\/](?:Users|CU)[\\/]|USER_HOME|github_pat_|ghp_[A-Za-z0-9]{20}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY", text):
                        leaks.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    checks["no_private_machine_paths_or_obvious_credentials"] = not leaks
    checks["no_executable_or_secret_files"] = not any(p.suffix.lower() in {".dll", ".exe", ".key", ".pem"} for p in scans)
    with rasterio.open(ROOT / "data/terrain20m.tif") as ds:
        terrain, terrain_crs, resolution = ds.read(1), ds.crs.to_epsg(), ds.res
    with rasterio.open(ROOT / "data/active.tif") as ds:
        active = ds.read(1) > 0
    with rasterio.open(ROOT / "data/xinyi.tif") as ds:
        district = ds.read(1) > 0
    checks["terrain_epsg3826_20m"] = terrain_crs == 3826 and resolution == (20.0, 20.0)
    checks["exact_domain_and_reporting_masks"] = int(active.sum()) == 89394 and int(district.sum()) == 28097 and not (district & ~active).any()
    checks["finite_active_terrain"] = bool(np.isfinite(terrain[active]).all())
    event_rows = []
    for e in read(ROOT / "data/events.json"):
        with np.load(ROOT / "data" / e["data_file"], allow_pickle=False) as a:
            event_rows.append({"id": e["id"], "array_names": list(a.files), "bytes": (ROOT / "data" / e["data_file"]).stat().st_size})
    checks["four_event_arrays_readable"] = len(event_rows) == 4
    example_rows = []
    for entry in read(ROOT / "examples/catalog.json"):
        folder = ROOT / "examples" / entry["id"]
        source = read(folder / "example_source.json")
        summary = read(folder / "summary.json")
        matched = all(sha(folder / f["path"]) == f["sha256"] == f["original_sha256"]
                      for f in source["included_numeric_files"])
        supporting = all(sha(folder / f["path"]) == f["sha256"]
                         for f in source.get("included_supporting_files", []))
        presentation = source.get("regenerated_presentation_files", [])
        presentation_valid = ({f['path'] for f in presentation} == {'result.qgs', 'READ_ME.txt'}
                              and all(sha(folder / f['path']) == f['sha256'] for f in presentation)
                              and sha(folder / 'result.qgs') == sha(ROOT / 'templates/result.qgs'))
        example_rows.append({"id": entry["id"], "included_original_numeric_files_unchanged": matched,
                             "supporting_evidence_matches": supporting,
                             "regenerated_presentation_separately_declared": presentation_valid,
                             "original_summary_unchanged": sha(folder / "summary.json") == source["original_summary_sha256"],
                             "clearly_precomputed_windows_result": source["is_precomputed_example"] and not source["is_cloud_validation"],
                             "original_numerical_acceptance": summary["passed"] and all(summary["checks"].values())})
    checks["two_examples_preserve_completed_original_results"] = len(example_rows) == 2 and all(
        all(v for k, v in row.items() if k != "id") for row in example_rows)
    report = {"passed": all(checks.values()), "checks": checks, "privacy_findings": leaks,
              "scope": "data and examples only; repository code, cloud computation and redistribution terms require separate review",
              "files_scanned": len(scans), "bytes_scanned": sum(p.stat().st_size for p in scans),
              "events": event_rows, "examples": example_rows}
    (ROOT / "qa/data_release_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": checks, "privacy_findings": leaks}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
