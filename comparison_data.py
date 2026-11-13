"""Read-only, full-resolution comparison of accepted Xinyi scenario outputs.

This module does not run a solver or infer missing time-series grids.  Source
declarations and numerical QA are reported as such, not as field validation.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MODEL = "SWMM_equivalent_units_bidirectional_2D_NOT_actual_network"
FIELDS = {
    "max_depth_m": {"label": "整段最大水深", "unit": "m", "kind": "depth"},
    "final_depth_m": {"label": "結束時水深", "unit": "m", "kind": "depth"},
    "duration_gt10_s": {"label": "超過 10 cm 的累積時間", "unit": "s", "kind": "duration"},
    "first_gt10_s": {"label": "首次超過 10 cm 的時間", "unit": "s", "kind": "event_time"},
    "time_of_max_s": {"label": "最大水深出現時間", "unit": "s", "kind": "event_time"},
}
CHECKS = {
    "full_surface_clock", "full_native_clock", "native_version_52004",
    "finite_nonnegative", "max_not_below_final", "duration_in_range",
    "rain_integral", "surface_balance", "combined_balance_under_1pct",
    "native_balance_under_1pct", "zero_native_warnings", "no_unaccounted_flood",
    "native_binary_storage", "no_hidden_depth_correction",
}
REQUEST_KEYS = ("mode", "event_id", "total_mm", "duration_min", "rain_shape",
                "recession_min", "drain_mm_h", "storage_mm", "inlet_area_m2",
                "infiltration_mm_h", "exchange_cap_s", "model")
BUDGET_KEYS = ("initial_surface_m3", "initial_native_m3", "rain_m3",
               "infiltration_m3", "boundary_out_m3", "to_network_m3",
               "to_surface_m3", "drain_m3", "surface_stored_m3",
               "native_stored_m3", "native_flood_m3", "surface_residual_m3",
               "combined_residual_m3", "native_flow_error_pct", "warnings", "roundoff_m3")


def _file(folder: Path, name: str) -> Path:
    base = Path(folder).resolve(strict=True)
    path = (base / name).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("比較檔案必須位於選取的結果資料夾內。")
    return path


def _json(path: Path) -> dict:
    if path.stat().st_size > 2_000_000:
        raise ValueError("比較中繼資料過大。")
    def reject_constant(_):
        raise ValueError("中繼資料含非有限數字。")
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("比較中繼資料必須是物件。")
    return value


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} 缺少有效數字。")
    return float(value)


def _same_grid(dataset, shape, transform, crs) -> None:
    if (dataset.shape != shape or dataset.count != 1 or dataset.crs != crs
            or not np.allclose(tuple(dataset.transform), tuple(transform), rtol=0, atol=1e-9)):
        raise ValueError("結果與共同地形的格網、座標系或位置不一致；不能逐格比較。")


def _load_grid():
    with rasterio.open(DATA / "terrain20m.tif") as ds:
        z = ds.read(1).astype(np.float32)
        transform, crs, bounds = ds.transform, ds.crs, ds.bounds
        terrain_nodata = ds.nodata
    if (crs is None or crs.to_epsg() != 3826 or
            not np.allclose(tuple(transform)[:6], (20, 0, transform.c, 0, -20, transform.f), rtol=0, atol=1e-9)):
        raise ValueError("共同地形必須使用 EPSG:3826、原始 20 m 正北向格網。")
    masks = []
    for filename in ("active.tif", "xinyi.tif"):
        with rasterio.open(DATA / filename) as ds:
            _same_grid(ds, z.shape, transform, crs)
            masks.append(ds.read(1) > 0)
    active, report = masks
    if (not active.any() or not report.any() or np.any(report & ~active)
            or not np.isfinite(z[active]).all()
            or (terrain_nodata is not None and np.any(z[active] == terrain_nodata))):
        raise ValueError("共同地形或信義區範圍無效。")
    # Current common input hashes are checked, while old runs' original input
    # binaries are not present.  This is not independent proof of old terrain.
    manifest = _json(DATA / "source_manifest.json")
    for name in ("terrain20m.tif", "active.tif", "xinyi.tif"):
        if _sha(DATA / name) != manifest.get(name, {}).get("sha256"):
            raise ValueError("共同地形或範圍與本專案來源清冊不符。")
    return z, active, report, transform, crs, bounds


def _known_manifests() -> set[str]:
    hashes = {_sha(DATA / "source_manifest.json")}
    # The two preserved V2 examples retain the original, pre-sanitization
    # manifest hash. Only these bundled declarations extend the allow-list.
    catalog_path = ROOT / "examples" / "catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        for row in catalog:
            run_id = row.get("id", "")
            if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
                p = _file(ROOT / "examples" / run_id, "provenance.json")
                value = _json(p).get("source_manifest_sha256", "")
                if re.fullmatch(r"[0-9a-f]{64}", value):
                    hashes.add(value)
    return hashes


def _read_last_csv(folder: Path, name: str) -> dict:
    path = _file(folder, name)
    if path.stat().st_size > 8_000_000:
        raise ValueError("比較時間紀錄過大。")
    last = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            last = row
    if last is None:
        raise ValueError("比較結果缺少完整時間紀錄。")
    return last


def _field_mask(values, active, field, end_s):
    values = np.asarray(values)
    active = np.asarray(active, dtype=bool)
    if values.shape != active.shape or values.dtype.kind not in "fiu":
        raise ValueError("結果陣列尺寸或數值型別不符。")
    if (not np.isfinite(values[active]).all()
            or np.any(np.abs(values[active]) > np.finfo(np.float32).max)):
        raise ValueError("結果有效格含非有限值，或超出可安全傳送的數值範圍。")
    never = active & (values == -1) if field == "first_gt10_s" else np.zeros_like(active)
    valid = active & ~never
    if np.any(values[valid] < 0):
        raise ValueError("結果含未定義的負值；不得把它補成零。")
    if FIELDS[field]["unit"] == "s" and np.any(values[valid] > end_s + .01):
        raise ValueError("格網時間超出該情境的完整計算時間。")
    return valid, never


def _rain_integral(folder, active, end_s):
    path = _file(folder, "rain_input.npz")
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) != 3 or sum(p.file_size for p in archive.infolist()) > active.size * 8 + 500_000:
            raise ValueError("降雨壓縮檔結構或解壓大小不符。")
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != {"edges_s", "rates_m_s", "station_index"}:
            raise ValueError("降雨輸入缺少時間、雨強或雨站分配。")
        edges, rates, station = data["edges_s"], data["rates_m_s"], data["station_index"]
        if (edges.ndim != 1 or edges.size < 2 or rates.ndim != 2 or rates.shape[0] != edges.size - 1
                or rates.shape[1] < 1 or station.shape != active.shape or station.dtype.kind not in "iu"
                or not np.isfinite(edges).all() or not np.isfinite(rates).all()
                or edges[0] != 0 or abs(float(edges[-1]) - end_s) > .01
                or np.any(np.diff(edges) <= 0) or np.any(rates < 0)
                or station[active].min() < 0 or station[active].max() >= rates.shape[1]):
            raise ValueError("降雨輸入的時間、雨強或雨站分配不合理。")
        counts = np.bincount(station[active], minlength=rates.shape[1])
        expected = float(np.dot((rates * np.diff(edges)[:, None]).sum(axis=0), counts) * 400)
    return _number(expected, "積分雨量")


def _verified_budget(summary, native_balance, expected_rain):
    native = {}
    for key in BUDGET_KEYS:
        try:
            value = float(native_balance[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("原生收支紀錄不完整。") from exc
        native[key] = _number(value, key)
        reported = _number(summary.get("balance", {}).get(key), key)
        if not math.isclose(reported, value, rel_tol=1e-10, abs_tol=1e-6):
            raise ValueError("摘要收支與原生 balance.csv 不一致。")
    reported_rain = _number(summary.get("expected_rain_m3"), "摘要積分雨量")
    rain_tolerance = max(.001, expected_rain * 1e-7)
    if abs(reported_rain - expected_rain) >= rain_tolerance or abs(native["rain_m3"] - expected_rain) >= rain_tolerance:
        raise ValueError("摘要或原生雨量與輸入雨型積分不一致。")
    denominator = max(expected_rain + native["initial_surface_m3"] + native["initial_native_m3"], 1)
    # Same bookkeeping equations as NativeCoupling.cs, using native CSV values.
    combined = (native["initial_surface_m3"] + native["initial_native_m3"] + native["rain_m3"]
                - native["infiltration_m3"] - native["boundary_out_m3"] - native["drain_m3"]
                - native["native_flood_m3"] + native["roundoff_m3"]
                - native["surface_stored_m3"] - native["native_stored_m3"])
    surface = (native["initial_surface_m3"] + native["rain_m3"] + native["to_surface_m3"]
               - native["to_network_m3"] - native["infiltration_m3"] - native["boundary_out_m3"]
               + native["roundoff_m3"] - native["surface_stored_m3"])
    for recorded, recomputed in ((native["combined_residual_m3"], combined),
                                 (native["surface_residual_m3"], surface)):
        if not math.isclose(recorded, recomputed, rel_tol=1e-8, abs_tol=max(1e-6, denominator * 1e-12)):
            raise ValueError("原生收支差與逐項水量重算不一致。")
    # Match backend.validate_outputs: denominator uses forcing-integrated rain,
    # not the slightly different accumulated native-rain floating-point sum.
    error = abs(native["combined_residual_m3"]) / denominator * 100
    reported_error = _number(summary.get("combined_error_pct"), "摘要收支差")
    if not math.isclose(reported_error, error, rel_tol=1e-8, abs_tol=1e-10):
        raise ValueError("摘要收支百分比與原生紀錄重算不一致。")
    if (abs(native["surface_residual_m3"]) >= max(.001, denominator * 1e-7)
            or abs(native["combined_residual_m3"]) >= max(.001, denominator * .01)
            or abs(native["native_flow_error_pct"]) >= 1 or native["warnings"] != 0
            or abs(native["native_flood_m3"]) >= .001
            or native["roundoff_m3"] >= max(.001, denominator * 1e-8)):
        raise ValueError("原生收支重新核對未通過原有數值門檻。")
    return native, error


def _read_scenario(folder, label, field, grid, known):
    folder = Path(folder).resolve(strict=True)
    z, active, report, transform, crs, _ = grid
    summary = _json(_file(folder, "summary.json"))
    request = _json(_file(folder, "request.json"))
    provenance = _json(_file(folder, "provenance.json"))
    checks = summary.get("checks", {})
    if (summary.get("passed") is not True or not CHECKS.issubset(checks)
            or any(v is not True for v in checks.values())):
        raise ValueError("只能比較已通過完整數值檢查的結果。")
    if (request.get("model") != MODEL or summary.get("request") != request
            or provenance.get("request") != request):
        raise ValueError("結果的模型或輸入紀錄不一致。")
    manifest_hash = provenance.get("source_manifest_sha256")
    if manifest_hash not in known:
        raise ValueError("結果未宣告使用本專案已知的資料來源清冊。")
    if (folder / "status.json").exists():
        if _json(_file(folder, "status.json")).get("state") != "completed":
            raise ValueError("此情境尚未完成，不能比較。")
    rainfall = summary.get("rainfall", {})
    end_s = _number(rainfall.get("end_s"), "結束時間")
    rain_end = _number(rainfall.get("rain_end_s"), "降雨結束時間")
    if end_s <= 0 or not 0 <= rain_end <= end_s:
        raise ValueError("降雨與結束時間不合理。")
    progress = _json(_file(folder, "native/progress.json"))
    history = _read_last_csv(folder, "native/history.csv")
    native_balance = _read_last_csv(folder, "native/balance.csv")
    clocks = [summary.get("balance", {}).get("time_s"), progress.get("time_s"), progress.get("end_s")]
    try:
        clocks += [float(history["time_s"]), float(native_balance["time_s"])]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("原生時間紀錄不完整。") from exc
    if any(abs(_number(t, "完成時間") - end_s) > .01 for t in clocks):
        raise ValueError("結果尚未到達相同的完整結束時間。")
    expected_rain = _rain_integral(folder, active, end_s)
    budget, error = _verified_budget(summary, native_balance, expected_rain)
    npz_path = _file(folder, "grids.npz")
    with zipfile.ZipFile(npz_path) as archive:
        members = archive.infolist()
        if (len(members) != 7 or sum(p.file_size for p in members) > z.size * 8 * 7 + 65536
                or len({p.filename for p in members}) != len(members)):
            raise ValueError("格網壓縮檔結構或解壓大小不符。")
    with np.load(npz_path, allow_pickle=False) as data:
        if set(data.files) != set(FIELDS) | {"qx_m2_s", "qrow_m2_s"}:
            raise ValueError("結果不是本專案完整七欄格網。")
        arrays = {}
        for key in FIELDS:
            array = data[key]
            _field_mask(array, active, key, end_s)
            with rasterio.open(_file(folder, f"{key}.tif")) as ds:
                _same_grid(ds, z.shape, transform, crs)
                raster = ds.read(1)
                if not np.array_equal(raster[active], array[active]):
                    raise ValueError("GeoTIFF 與壓縮格網數值不一致。")
            arrays[key] = np.asarray(array, dtype=np.float32)
    if np.any(arrays["max_depth_m"][active] + 1e-6 < arrays["final_depth_m"][active]):
        raise ValueError("最大水深小於最後水深。")
    values = arrays[field]
    valid, never = _field_mask(values, active, field, end_s)
    metrics = {
        "active_cells": int(active.sum()), "reporting_cells": int(report.sum()),
        "reporting_area_km2": float(report.sum() * 400 / 1e6),
        "field_valid_reporting_cells": int((valid & report).sum()),
        "field_never_reporting_cells": int((never & report).sum()),
        "rain_duration_s": rain_end, "simulation_duration_s": end_s,
        "max_depth_m": float(arrays["max_depth_m"][report].max()),
        "p99_depth_m": float(np.percentile(arrays["max_depth_m"][report], 99)),
        "area_ever_gt5_km2": float(np.sum(arrays["max_depth_m"][report] > .05) * .0004),
        "area_ever_gt10_km2": float(np.sum(arrays["max_depth_m"][report] > .1) * .0004),
        "area_ever_gt30_km2": float(np.sum(arrays["max_depth_m"][report] > .3) * .0004),
        "combined_error_pct": error, "expected_rain_m3": expected_rain,
        "budget": budget,
    }
    numeric_request = {}
    for key in REQUEST_KEYS:
        if key in request:
            value = request[key]
            if isinstance(value, str):
                if len(value) > 120 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                    raise ValueError("輸入紀錄含未支援的文字。")
                numeric_request[key] = value
            else:
                numeric_request[key] = _number(value, key)
    source = {"source_manifest_sha256": manifest_hash,
              "grid_checked": True, "original_terrain_independently_verified": False,
              "grids_sha256": _sha(npz_path), "summary_sha256": _sha(folder / "summary.json"),
              "request_sha256": _sha(folder / "request.json")}
    for key in ("engine_sha256", "swmm_library_sha256", "swmm_dll_sha256"):
        value = provenance.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
            source[key] = value
    source["engine_sources"] = {key: value for key, value in provenance.get("engine_sources", {}).items()
                                if key in ("NativeCoupling.cs", "SurfaceEngine.cs")
                                and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)}
    source["precomputed_example"] = (folder / "example_source.json").is_file()
    scenario = {"label": str(label)[:160], "request": numeric_request,
                "metrics": metrics, "provenance": source}
    return scenario, values, valid, never


def _encode(values, mask=None, dtype="float32-le"):
    if dtype == "uint8":
        data = np.ascontiguousarray(values, dtype=np.uint8)
    else:
        data = np.array(values, dtype="<f4", order="C", copy=True)
        if mask is not None:
            data[~mask] = np.nan
    return {"dtype": dtype, "shape": list(data.shape), "encoding": "base64",
            "data": base64.b64encode(data.tobytes(order="C")).decode("ascii")}


def _compare_arrays(a, b, valid_a, valid_b):
    common = valid_a & valid_b
    difference = np.full(a.shape, np.nan, dtype=np.float32)
    difference[common] = b[common] - a[common]
    selected = np.concatenate((a[valid_a], b[valid_b]))
    absolute_max = float(selected.max()) if selected.size else 0.0
    difference_max = float(np.abs(difference[common]).max()) if common.any() else 0.0
    scales = {"absolute": [0.0, absolute_max if absolute_max > 0 else 1.0],
              "difference": [-difference_max, difference_max] if difference_max > 0 else [-1.0, 1.0],
              "absolute_has_data": bool(selected.size), "difference_has_data": bool(common.any())}
    return difference, common, scales


def _warnings(a, b, field):
    warnings = []
    ra, rb = a["request"], b["request"]
    def rain_key(r):
        return ((r.get("mode"), r.get("event_id")) if r.get("mode") == "historical" else
                (r.get("mode"), r.get("total_mm"), r.get("duration_min"), r.get("rain_shape")))
    if rain_key(ra) != rain_key(rb):
        warnings.append("兩邊的降雨條件不同；差異不能只歸因於排水設定。")
    if a["metrics"]["simulation_duration_s"] != b["metrics"]["simulation_duration_s"]:
        warnings.append("兩邊的計算時長不同；結束水深與累積時間不是同一時點的比較。")
    if any(ra.get(k) != rb.get(k) for k in ("drain_mm_h", "storage_mm", "inlet_area_m2", "infiltration_mm_h")):
        warnings.append("兩邊的排水、暫存或入滲假設不同。")
    if a["provenance"]["engine_sources"] != b["provenance"]["engine_sources"]:
        warnings.append("兩邊使用的求解程式版本不同。")
    if field == "first_gt10_s":
        warnings.append("灰格表示該情境未曾超過 10 cm；只有兩邊都曾超過的格子才算時間差。")
    return warnings


def _boundaries():
    source = _json(DATA / "xinyi_boundary.geojson")
    declared_crs = source.get("crs", {}).get("properties", {}).get("name", "")
    if not declared_crs.endswith(":3826"):
        raise ValueError("區界資料必須明示 EPSG:3826。")
    rings = []
    for feature in source.get("features", []):
        geom = feature.get("geometry", {})
        polygons = [geom.get("coordinates", [])] if geom.get("type") == "Polygon" else geom.get("coordinates", [])
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("區界不是多邊形。")
        for polygon in polygons:
            for ring in polygon:
                points = [[_number(p[0], "區界 X"), _number(p[1], "區界 Y")] for p in ring]
                if len(points) >= 4:
                    rings.append(points)
    return rings


def build_comparison(folder_a, folder_b, label_a, label_b, field="max_depth_m") -> dict:
    """Return JSON-safe arrays (base64 LE float32/uint8), without source paths.

    ``valid_mask`` is the shared terrain domain; ``reporting_mask`` is Xinyi.
    ``a_valid_mask``/``b_valid_mask`` exclude the -1 never-crossed sentinel.
    Difference is B minus A only where both are valid. Terrain is never raised
    by maximum water depths, which occur at different times in different cells.
    """
    if field not in FIELDS:
        raise ValueError("不支援的比較欄位。")
    grid, known = _load_grid(), _known_manifests()
    z, active, report, transform, crs, bounds = grid
    a, av, am, an = _read_scenario(folder_a, label_a, field, grid, known)
    b, bv, bm, bn = _read_scenario(folder_b, label_b, field, grid, known)
    difference, dm, scales = _compare_arrays(av, bv, am, bm)
    z_min, z_max = float(z[active].min()), float(z[active].max())
    arrays = {"terrain_m": _encode(z, active), "terrain_relative_m": _encode(z - z_min, active),
              "a": _encode(av, am), "b": _encode(bv, bm), "difference": _encode(difference, dm)}
    for name, mask in (("valid_mask", active), ("reporting_mask", report),
                       ("a_valid_mask", am), ("b_valid_mask", bm), ("difference_valid_mask", dm),
                       ("a_never_mask", an), ("b_never_mask", bn)):
        arrays[name] = _encode(mask, dtype="uint8")
    common_report = dm & report
    values = difference[common_report]
    statistics = {"common_reporting_cells": int(common_report.sum()),
                  "only_a_valid_reporting_cells": int((am & ~bm & report).sum()),
                  "only_b_valid_reporting_cells": int((bm & ~am & report).sum()),
                  "positive_reporting_cells": int(np.sum(values > 0)),
                  "negative_reporting_cells": int(np.sum(values < 0)),
                  "unchanged_reporting_cells": int(np.sum(values == 0)),
                  "mean_difference": float(values.mean(dtype=np.float64)) if values.size else None,
                  "min_difference": float(values.min()) if values.size else None,
                  "max_difference": float(values.max()) if values.size else None}
    return {
        "version": 1, "field": {"id": field, **FIELDS[field]},
        "grid": {"rows": z.shape[0], "cols": z.shape[1], "cell_size_m": 20,
                 "crs": crs.to_string(), "transform": list(transform)[:6],
                 "bounds": {"west": bounds.left, "south": bounds.bottom, "east": bounds.right, "north": bounds.top},
                 "origin": {"x": (bounds.left + bounds.right) / 2, "y": (bounds.bottom + bounds.top) / 2, "z": z_min},
                 "terrain_min_m": z_min, "terrain_max_m": z_max,
                 "active_cells": int(active.sum()), "reporting_cells": int(report.sum()),
                 "cell_location": "center: x=c+(col+0.5)*a; y=f+(row+0.5)*e; rows increase southward"},
        "arrays": arrays, "scales": scales, "scenarios": [a, b],
        "difference_summary": statistics, "difference_definition": "B - A",
        "warnings": _warnings(a, b, field), "boundary_rings": _boundaries(),
        "notes": [
            "比較使用完整 20 m 格網；沒有降採樣或補值。指標統計限信義區，背景地形包含周邊計算域。",
            "地形、格網與來源宣告已核對；舊結果未封存完整輸入地形，未獨立重驗原計算使用的全部地形。",
            "最大水深不是同一時刻的水面；這裡只在地形上著色，不把各格最大值拼成水面。",
            "時間均從各情境起算點開始，不是同一日的鐘點；目前沒有逐格時間序列動畫。",
            "這是已完成的假設排水情境比較，不是實際淹水預報或發生機率。",
        ],
    }
