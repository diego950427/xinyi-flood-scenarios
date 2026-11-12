"""Conditional SWMM/2D experiments. No inferred real sewer connections."""
from pathlib import Path
from datetime import datetime, timedelta
import csv
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import uuid
import psutil
from filelock import FileLock, Timeout

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import shape, mapping

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
V1 = PROJECT / "情境研究_V1"
DATA = ROOT / "data"
STATE_ROOT = Path(os.environ.get("XINYI_STATE_DIR", str(ROOT / ".runtime")))
RUNS = STATE_ROOT / "runs"
ENGINE = ROOT / "engine"
NATIVE_ROOT = STATE_ROOT / "native"
NATIVE_BIN = NATIVE_ROOT / "bin"
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
# A user-visible local job must outlive the short-lived command that launched it.
WORKER_FLAGS = CREATE_FLAGS | (subprocess.CREATE_BREAKAWAY_FROM_JOB if os.name == "nt" else 0)
BG = "#081f5c"
INK = "#edeff1"
ACCENT = "#9ebfe9"
sys.path.insert(0, str(ENGINE))
from swmm_output import read_output


def owner_key(token):
    if not isinstance(token, str) or len(token) < 24:
        raise ValueError("缺少這個瀏覽工作階段的識別，請重新整理頁面。")
    return hashlib.sha256(token.encode()).hexdigest()


def owned_run(rid, token):
    p = run_folder(rid) / "owner.json"
    return p.exists() and json_read(p).get("owner") == owner_key(token)


def visible_runs(token):
    return sorted([p for p in RUNS.glob("*") if p.is_dir()
                   and (p / "status.json").exists() and owned_run(p.name, token)], reverse=True)


def json_read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def json_save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    def normalize(obj):
        if isinstance(obj, np.generic):
            return obj.item()
        raise TypeError(f"Unsupported JSON value: {type(obj)}")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=normalize), encoding="utf-8")
    os.replace(tmp, path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def table_save(path, rows):
    rows = list(rows)
    if not rows:
        raise ValueError("Empty table is not a successful result")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def load_grid():
    with rasterio.open(DATA / "terrain20m.tif") as ds:
        z, profile, transform = ds.read(1).astype(float), ds.profile, ds.transform
    with rasterio.open(DATA / "active.tif") as ds:
        active = ds.read(1) > 0
    with rasterio.open(DATA / "xinyi.tif") as ds:
        report = ds.read(1) > 0
    if not np.isfinite(z[active]).all() or np.any(report & ~active):
        raise ValueError("Invalid terrain or reporting mask")
    return z, active, report, profile, transform


def build_units():
    z, active, _, _, transform = load_grid()
    pipes = json_read(DATA / "pipes_reference_only.geojson")
    if "3826" not in json.dumps(pipes.get("crs", {})):
        raise ValueError("Pipe coordinates must explicitly be EPSG:3826")
    buffers = [shape(f["geometry"]).buffer(60) for f in pipes["features"] if f.get("geometry")]
    eligible = rasterize([(g, 1) for g in buffers], out_shape=z.shape,
                         transform=transform, fill=0).astype(bool) & active
    ids = np.full(z.shape, -1, np.int32)
    ids[active] = np.arange(active.sum())
    units = []
    # Fixed 200 m tiles; a single representative low cell per tile. These are NOT real inlet locations.
    for row in range(0, z.shape[0], 10):
        for col in range(0, z.shape[1], 10):
            m = eligible[row:row + 10, col:col + 10]
            if not m.any():
                continue
            zz = np.where(m, z[row:row + 10, col:col + 10], np.inf)
            rr, cc = np.unravel_index(zz.argmin(), zz.shape)
            r, c = row + int(rr), col + int(cc)
            x, y = transform * (c + .5, r + .5)
            units.append({"id": str(len(units)), "cell": int(ids[r, c]), "row": r, "col": c,
                          "x": x, "y": y, "crest": float(z[r, c]),
                          "support_area_m2": int(m.sum()) * 400})
    if not units:
        raise ValueError("No scenario drainage coverage; do not silently run surface-only")
    json_save(DATA / "virtual_units.json", units)
    np.save(DATA / "drainage_coverage.npy", eligible)
    json_save(DATA / "virtual_units.geojson", {
        "type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:3826"}},
        "features": [{"type": "Feature", "properties": {**u, "role": "假設交換單元；非實測雨水口"},
                      "geometry": {"type": "Point", "coordinates": [u["x"], u["y"]]}} for u in units],
    })
    json_save(DATA / "unit_design.json", {
        "unit_count": len(units), "coverage_area_km2": float(eligible.sum() * .0004),
        "source_role": "public pipe XY coverage only; no source invert or connectivity is used",
        "tile_m": 200, "coverage_buffer_m": 60,
        "selection": "lowest eligible 20m terrain cell within each tile",
        "physical_interpretation": "independent equivalent drainage reservoirs; no connection between reservoirs",
        "not_actual_inlets": True, "not_actual_pipes": True,
    })


def events():
    return json_read(DATA / "events.json")


def validate_request(req):
    d = dict(req)
    if d.get("mode") not in ("historical", "custom"):
        raise ValueError("請選擇歷史事件或自訂降雨。")
    if d["mode"] == "historical" and d.get("event_id") not in {e["id"] for e in events()}:
        raise ValueError("這個歷史事件尚無完整可用雨量，不能執行。")
    bounds = {"total_mm": (0, 300), "duration_min": (10, 360), "recession_min": (0, 180),
              "drain_mm_h": (0, 100), "storage_mm": (1, 100), "inlet_area_m2": (.01, 1),
              "infiltration_mm_h": (0, 30), "exchange_cap_s": (.05, 1)}
    defaults = {"total_mm": 100, "duration_min": 60, "recession_min": 60,
                "drain_mm_h": 30, "storage_mm": 20, "inlet_area_m2": .2,
                "infiltration_mm_h": 0, "exchange_cap_s": 1}
    for key, (lo, hi) in bounds.items():
        x = d.get(key, defaults[key])
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not lo <= x <= hi:
            raise ValueError(f"{key} 必須介於 {lo} 與 {hi}。")
        d[key] = float(x)
    if d["duration_min"] % 1 or d["recession_min"] % 1:
        raise ValueError("時間請輸入整數分鐘。")
    if d["mode"] == "custom" and d["total_mm"] / (d["duration_min"] / 60) > 300:
        raise ValueError("平均雨強超過本版 300 mm/h 測試範圍，請降低雨量或延長時間。")
    if d.get("rain_shape", "uniform") not in ("uniform", "middle_peak"):
        raise ValueError("未知雨型。")
    d["rain_shape"] = d.get("rain_shape", "uniform")
    d["model"] = "SWMM_equivalent_units_bidirectional_2D_NOT_actual_network"
    return d


def forcing(req, active):
    d = validate_request(req)
    if d["mode"] == "historical":
        event = next(e for e in events() if e["id"] == d["event_id"])
        a = np.load(DATA / event["data_file"])
        edges = a["edges_s"].astype(float)
        depths = a["depths_mm"].astype(float)
        station = a["station_index"].astype(np.int32) if "station_index" in a else np.zeros(active.shape, np.int32)
        meta = dict(event)
    else:
        minutes = int(d["duration_min"])
        edges = np.arange(0, minutes * 60 + 1, 60, dtype=float)
        weights = np.ones(minutes)
        if d["rain_shape"] == "middle_peak":
            x = (np.arange(minutes) + .5) / minutes
            weights = np.maximum(.01, 1 - abs(2 * x - 1))
        depths = (weights / weights.sum() * d["total_mm"])[:, None]
        station = np.zeros(active.shape, np.int32)
        meta = {"label": f"自訂 {d['total_mm']:g} mm／{minutes} 分鐘",
                "kind": "synthetic_rainfall", "start_local": "2020-01-01T00:00:00+08:00"}
    rain_end = float(edges[-1])
    if d["recession_min"] > 0:
        edges = np.append(edges, rain_end + d["recession_min"] * 60)
        depths = np.vstack([depths, np.zeros((1, depths.shape[1]))])
    if station.shape != active.shape or not np.isfinite(depths).all() or depths.min() < 0:
        raise ValueError("雨量或空間對應不完整。")
    if station[active].min() < 0 or station[active].max() >= depths.shape[1]:
        raise ValueError("雨量站對應索引錯誤。")
    rates = depths / 1000 / np.diff(edges)[:, None]
    meta.update(rain_end_s=rain_end, end_s=float(edges[-1]),
                recession_note="雨後延長段明示假設無雨；不是缺測補零。",
                gauge_window_totals_mm=depths.sum(axis=0).tolist())
    return edges, rates, station, meta


def faces(active):
    ids = np.full(active.shape, -1, np.int32)
    ids[active] = np.arange(active.sum())
    output = []
    for axis in (0, 1):
        a = np.pad(ids, ((0, 0), (1, 1)) if axis == 0 else ((1, 1), (0, 0)), constant_values=-1)
        l, r = (a[:, :-1], a[:, 1:]) if axis == 0 else (a[:-1, :], a[1:, :])
        ok = (l >= 0) | (r >= 0)
        output.append(np.column_stack([l[ok], r[ok], np.full(ok.sum(), axis)]))
    return np.concatenate(output).astype("<i4")


def write_binary(path, z, active, report, edges, rates, station, loss=0, closed=False,
                 dx=20, cap=5, state=None):
    if state is None:
        state = np.zeros((3, *z.shape))
    ff = faces(active)
    with Path(path).open("wb") as f:
        f.write(struct.pack("<iiddd?dii", 20261020, int(active.sum()), dx, .03, cap, closed,
                            loss / 1000 / 3600, rates.shape[1], rates.shape[0]))
        for a in (edges, rates, z[active], state[0][active], state[1][active], state[2][active]):
            f.write(np.asarray(a, dtype="<f8").tobytes())
        f.write(station[active].astype("<i4").tobytes())
        f.write(report[active].astype(np.uint8).tobytes())
        f.write(struct.pack("<i", len(ff)))
        f.write(ff.tobytes())


def write_swmm(work, units, duration_s, req, initial_depth=0):
    """Separate unconnected reservoirs; controls are explicitly hypothetical."""
    # SWMM 5.2.4 project.c floors a floating-point date difference to seconds.
    # A nominal 07:00:00 can become 25,199 s. Keep a scheduling envelope; the
    # coupling driver still stops at duration_s, verified in both native clocks.
    end = datetime(2020, 1, 1) + timedelta(seconds=duration_s + 2)
    text = f"""[TITLE]
CONDITIONAL Xinyi study: equivalent reservoirs, NOT actual Taipei sewer connections.
Rain is applied ONLY to 2D. API stage forcing is required; INP alone is not reproduction.
Each independent reservoir uses local base 0 m and surface 2 m, NOT surveyed elevations.
END_TIME has a 2-second scheduling guard; the driver stops at {duration_s:g} seconds.
[OPTIONS]
FLOW_UNITS CMS
FLOW_ROUTING DYNWAVE
START_DATE 01/01/2020
START_TIME 00:00:00
REPORT_START_DATE 01/01/2020
REPORT_START_TIME 00:00:00
END_DATE {end:%m/%d/%Y}
END_TIME {end:%H:%M:%S}
REPORT_STEP 00:01:00
WET_STEP 00:00:01
DRY_STEP 00:00:01
ROUTING_STEP {req['exchange_cap_s']}
MINIMUM_STEP 0.001
VARIABLE_STEP 0
LENGTHENING_STEP 0
MIN_SURFAREA 0
HEAD_TOLERANCE 0.00001
SURCHARGE_METHOD EXTRAN
MAX_TRIALS 40
ALLOW_PONDING NO
THREADS 1
[EVAPORATION]
CONSTANT 0
"""
    sections = {k: [] for k in ["STORAGE", "OUTFALLS", "ORIFICES", "OUTLETS", "XSECTIONS", "CURVES", "COORDINATES"]}
    links = []
    for u in units:
        i, crest, support = u["id"], u["crest"], u["support_area_m2"]
        # Translating each independent reservoir leaves head differences unchanged.
        # This avoids spurious regulator crest warnings from ft/m cancellation.
        base, native_crest = 0.0, 2.0
        storage_area = support * req["storage_mm"] / 1000 / 2
        qmax = support * req["drain_mm_h"] / 1000 / 3600
        sections["STORAGE"].append(f"T{i} {base:.8f} 100 {initial_depth} FUNCTIONAL 0 0 {storage_area:.8f} 0 0")
        sections["OUTFALLS"] += [f"S{i} {native_crest:.8f} FIXED {native_crest:.8f} NO", f"O{i} {base:.8f} FREE NO"]
        sections["ORIFICES"].append(f"E{i} T{i} S{i} BOTTOM 2 0.6 NO 0")
        sections["OUTLETS"].append(f"D{i} T{i} O{i} 0 TABULAR/DEPTH C{i} YES")
        side = math.sqrt(req["inlet_area_m2"])
        sections["XSECTIONS"].append(f"E{i} RECT_CLOSED {side:.9f} {side:.9f} 0 0")
        sections["CURVES"] += [f"C{i} RATING 0 0", f"C{i} 0.05 {qmax:.12f}", f"C{i} 100 {qmax:.12f}"]
        x, y = u.get("x", 0), u.get("y", 0)
        sections["COORDINATES"] += [f"T{i} {x} {y}", f"S{i} {x + 2} {y + 2}", f"O{i} {x + 4} {y - 4}"]
        links.append({"id": i, "cell": u["cell"], "area": req["inlet_area_m2"], "cd": .6, "crest": crest})
    for name, rows in sections.items():
        text += f"\n[{name}]\n" + "\n".join(rows) + "\n"
    text += "\n[REPORT]\nINPUT NO\nNODES ALL\nLINKS ALL\n"
    (work / "model.inp").write_text(text, encoding="ascii")
    with (work / "units.csv").open("w", encoding="ascii", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(links[0]))
        w.writeheader()
        w.writerows(links)
    (work / "exchange_cap.txt").write_text(str(req["exchange_cap_s"]), encoding="ascii")


def run_folder(run_id):
    if not isinstance(run_id, str) or not run_id or any(x not in "0123456789abcdefghijklmnopqrstuvwxyz_-" for x in run_id):
        raise ValueError("Invalid run ID")
    return RUNS / run_id


def active_job():
    lock = STATE_ROOT / "active_job.json"
    if not lock.exists():
        return None
    try:
        d = json_read(lock)
        status = json_read(run_folder(d["id"]) / "status.json")
        if status["state"] not in ("queued", "running", "finishing"):
            return None
        try:
            proc = psutil.Process(int(d["pid"]))
            if abs(proc.create_time() - d["created"]) < .1 and proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return d
        except psutil.AccessDenied:
            return d  # Inability to inspect never proves termination.
        except psutil.NoSuchProcess:
            pass
        json_save(run_folder(d["id"]) / "status.json", {
            "state": "failed", "message": "計算程序已中斷；未列為完成。請保留紀錄並重新執行。"})
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        pass
    return None


def start_job(req, token):
    d = validate_request(req)
    owner = owner_key(token)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(STATE_ROOT / "submit.lock"), timeout=0):
            if active_job():
                raise RuntimeError("伺服器正在計算另一組，請稍後再試；不會覆蓋或停止別人的工作。")
            if len(visible_runs(token)) >= 10:
                raise RuntimeError("這個工作階段已達 10 組上限，請先下載成果。")
            # Bound cloud disk use without deleting anybody's research records.
            used = sum(p.stat().st_size for p in STATE_ROOT.rglob('*') if p.is_file())
            if used > 1_500_000_000 or shutil.disk_usage(STATE_ROOT).free < 600_000_000:
                raise RuntimeError("伺服器暫存空間不足，請先下載已有成果；需要管理者重啟服務釋放暫存。")
            rid = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:12]
            folder = run_folder(rid)
            folder.mkdir(parents=True)
            json_save(folder / "owner.json", {"owner": owner})
            json_save(folder / "request.json", d)
            json_save(folder / "status.json", {"state": "queued", "message": "準備運算環境、地形與雨量"})
            options = dict(creationflags=WORKER_FLAGS) if os.name == 'nt' else dict(start_new_session=True)
            with (folder / "worker.log").open("w", encoding="utf-8") as log:
                proc = subprocess.Popen([sys.executable, str(ROOT / "worker.py"), rid], cwd=ROOT,
                                        stdout=log, stderr=subprocess.STDOUT, **options)
            json_save(STATE_ROOT / "active_job.json", {"id": rid, "pid": proc.pid,
                      "created": psutil.Process(proc.pid).create_time(), "owner": owner})
            return rid
    except Timeout:
        raise RuntimeError("正在建立計算，請稍後再試。")


def cancel_job(rid, token):
    if not owned_run(rid, token):
        raise ValueError("只能停止這個工作階段自己建立的計算。")
    job = active_job()
    if not job or job["id"] != rid:
        return
    folder = run_folder(rid)
    (folder / "cancel.request").write_text("User requested cancellation", encoding="utf-8")
    work = NATIVE_ROOT / "runs" / rid
    if work.exists():
        (work / "cancel.flag").write_text("cancel", encoding="ascii")


def status_of(rid):
    folder = run_folder(rid)
    status = json_read(folder / "status.json")
    p = NATIVE_ROOT / "runs" / rid / "progress.json"
    if p.exists():
        try:
            status.update(json_read(p))
        except (OSError, json.JSONDecodeError):
            pass
    return status


def execute_job(rid):
    folder = run_folder(rid)
    work = NATIVE_ROOT / "runs" / rid
    work.mkdir(parents=True, exist_ok=False)
    req = validate_request(json_read(folder / "request.json"))
    json_save(folder / "status.json", {"state": "running", "message": "建立 SWMM 與地表輸入"})
    try:
        from cloud_runtime import ensure_runtime
        runtime = ensure_runtime()
        z, active, report, profile, _ = load_grid()
        edges, rates, station, rainmeta = forcing(req, active)
        units = json_read(DATA / "virtual_units.json")
        json_save(folder / "rainfall.json", rainmeta)
        np.savez_compressed(folder / "rain_input.npz", edges_s=edges, rates_m_s=rates, station_index=station)
        write_binary(work / "input.bin", z, active, report, edges, rates, station, loss=req["infiltration_mm_h"])
        write_swmm(work, units, edges[-1], req)
        json_save(folder / "provenance.json", {
            "source_manifest_sha256": sha(DATA / "source_manifest.json"),
            "engine_sha256": sha(Path(runtime["binary"])),
            "swmm_library_sha256": sha(Path(runtime["library"])),
            "engine_sources": {p.name: sha(p) for p in ENGINE.glob("*.cs")},
            "unit_design": json_read(DATA / "unit_design.json"),
            "request": req, "platform": sys.platform, "native_work": "native/",
        })
        if (folder / "cancel.request").exists():
            (work / "cancel.flag").write_text("cancel", encoding="ascii")
        json_save(folder / "status.json", {"state": "running", "message": "SWMM 與二維地表交換計算中"})
        with (work / "console.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(runtime["command"] + ["input.bin", ".", "model.inp", "units.csv"],
                                    cwd=work, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_FLAGS, timeout=7200)
        # Preserve native evidence on failure too.
        native_copy = folder / "native"
        native_copy.mkdir(exist_ok=True)
        for p in work.iterdir():
            if p.is_file():
                shutil.copy2(p, native_copy / p.name)
        if result.returncode:
            cancelled = (folder / "cancel.request").exists()
            json_save(folder / "status.json", {
                "state": "cancelled" if cancelled else "failed",
                "message": "已停止，未完成結果不列為成果。" if cancelled else "求解器未完成；錯誤與原生檔保留在 native/console.log。",
            })
            return
        json_save(folder / "status.json", {"state": "finishing", "message": "核對水量收支與輸出地圖"})
        summary = validate_outputs(work, active, report, edges, rates, station)
        summary.update(request=req, rainfall=rainmeta, unit_count=len(units),
                       claim="條件式情境研究；不是真實管網、淹水預報或發生機率")
        state = np.fromfile(work / "state.bin", dtype="<f8").reshape(7, -1)
        arrays = {}
        names = ["final_depth_m", "qx_m2_s", "qrow_m2_s", "max_depth_m",
                 "time_of_max_s", "first_gt10_s", "duration_gt10_s"]
        outprofile = dict(profile)
        outprofile.update(dtype="float32", count=1, nodata=-9999, compress="deflate")
        for i, name in enumerate(names):
            a = np.full(active.shape, -9999, np.float32)
            a[active] = state[i]
            arrays[name] = a
            with rasterio.open(folder / f"{name}.tif", "w", **outprofile) as ds:
                ds.write(a, 1)
        np.savez_compressed(folder / "grids.npz", **arrays)
        json_save(folder / "summary.json", summary)
        from visuals import export_png
        export_png(folder, arrays["max_depth_m"], summary)
        make_qgis(folder)
        make_download(folder)
        passed = summary["passed"]
        json_save(folder / "status.json", {"state": "completed" if passed else "failed_qa",
                  "message": "計算與數值檢查完成；仍屬情境假設。" if passed else "有輸出，但數值檢查未通過；不得當作可用成果。",
                  "time_s": float(edges[-1]), "end_s": float(edges[-1])})
    except Exception as exc:
        import traceback
        (folder / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        json_save(folder / "status.json", {"state": "failed", "message": str(exc)})
        raise


def validate_outputs(work, active, report, edges, rates, station, dx=20):
    with (work / "balance.csv").open() as f:
        b = {k: float(v) for k, v in next(csv.DictReader(f)).items()}
    state = np.fromfile(work / "state.bin", dtype="<f8")
    if len(state) != int(active.sum()) * 7:
        raise ValueError("Incomplete surface result")
    state = state.reshape(7, -1)
    native = read_output(work / "model.out")
    counts = np.bincount(station[active], minlength=rates.shape[1])
    expected_rain = float(np.dot((rates * np.diff(edges)[:, None]).sum(axis=0), counts) * dx**2)
    denominator = max(expected_rain + b["initial_surface_m3"] + b["initial_native_m3"], 1)
    err = abs(b["combined_residual_m3"]) / denominator * 100
    native_storage = float(native["system"][-1, native["codes"][3].index(12)])
    checks = {
        "native_completion_marker": "COMPLETED_COUPLED" in (work / "console.log").read_text(encoding="utf-8", errors="replace"),
        "full_surface_clock": abs(b["time_s"] - edges[-1]) < .001,
        "full_native_clock": abs(native["times_s"][-1] - edges[-1]) < .01,
        "native_version_52004": native["version"] == 52004,
        "finite_nonnegative": bool(np.isfinite(state).all() and state[0].min() >= 0),
        "max_not_below_final": bool(np.all(state[3] >= state[0] - 1e-9)),
        "duration_in_range": bool(np.all((state[6] >= 0) & (state[6] <= edges[-1] + .001))),
        "rain_integral": abs(b["rain_m3"] - expected_rain) < max(.001, expected_rain * 1e-7),
        "surface_balance": abs(b["surface_residual_m3"]) < max(.001, denominator * 1e-7),
        "combined_balance_under_1pct": abs(b["combined_residual_m3"]) < max(.001, denominator * .01),
        "native_balance_under_1pct": abs(b["native_flow_error_pct"]) < 1,
        "zero_native_warnings": b["warnings"] == 0,
        "no_unaccounted_flood": abs(b["native_flood_m3"]) < .001,
        "native_binary_storage": abs(native_storage - b["native_stored_m3"]) < max(.001, native_storage * 1e-5),
        "no_hidden_depth_correction": b["roundoff_m3"] < max(.001, denominator * 1e-8),
    }
    mh = state[3, report[active]]
    return {"checks": checks, "passed": all(checks.values()), "balance": b,
            "combined_error_pct": err, "native_binary_storage_m3": native_storage,
            "expected_rain_m3": expected_rain, "reporting_area_km2": float(report.sum() * dx**2 / 1e6),
            "area_ever_gt5_km2": float((mh > .05).sum() * dx**2 / 1e6),
            "area_ever_gt10_km2": float((mh > .1).sum() * dx**2 / 1e6),
            "area_ever_gt30_km2": float((mh > .3).sum() * dx**2 / 1e6),
            "max_depth_m": float(mh.max()), "p99_depth_m": float(np.percentile(mh, 99))}


def make_qgis(folder):
    """Reuse the QGIS-generated, relocation-tested project; data names/CRS/grid are fixed."""
    import xml.etree.ElementTree as ET
    folder = Path(folder)
    shutil.copy2(DATA / "xinyi_boundary.geojson", folder / "xinyi_boundary.geojson")
    template = ROOT / "templates/result.qgs"
    tree = ET.parse(template)
    expected = {"./max_depth_m.tif", "./xinyi_boundary.geojson"}
    sources = {e.text for e in tree.findall('.//projectlayers/maplayer/datasource')}
    if sources != expected or tree.findtext('.//projectCrs/spatialrefsys/authid') != 'EPSG:3826':
        raise ValueError("Invalid portable QGIS template")
    shutil.copy2(template, folder / "result.qgs")


def make_download(folder):
    import zipfile
    (folder / "READ_ME.txt").write_text(
        "信義區條件式 SWMM＋二維地表結果\n\n"
        "QGIS：直接開 result.qgs；max_depth_m.tif 與 xinyi_boundary.geojson 必須保留在旁邊。\n"
        "圖層值的單位為公尺，每格 20 × 20 公尺；最大值不是同時水深。\n"
        "這不是校正後預報。排水單元、開口和出口能力是假設，不是真實管網。\n"
        "是否通過數值檢查請看 summary.json 的 passed 與 checks，不以有圖判斷。\n\n"
        "重現：在相同版本專案 使用 request.json 的同一組參數。\n"
        "native/model.inp 單獨執行不會重現：聯動程式會逐步提供地表交換水位。\n"
        "本包保存結果與原生證據，不是完整可攜的程式環境。\n",
        encoding="utf-8")
    with zipfile.ZipFile(folder / "results.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for p in folder.rglob("*"):
            if p.is_file() and not p.name.endswith("~") and p.name not in ("results.zip", "status.json", "worker.log", "owner.json", "error.txt", "cancel.request"):
                if p.name == "input.bin":
                    continue
                archive.write(p, str(p.relative_to(folder)))


