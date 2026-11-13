"""Read only this application's numerical result files from an uploaded ZIP."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import shutil
import stat
import uuid
import zipfile
from filelock import FileLock, Timeout

from backend import STATE_ROOT, owner_key, json_save

FIELDS = ("final_depth_m", "qx_m2_s", "qrow_m2_s", "max_depth_m",
          "time_of_max_s", "first_gt10_s", "duration_gt10_s")
ALLOWED = {
    "grids.npz", "summary.json", "request.json", "rainfall.json", "provenance.json",
    "example_source.json", "rain_input.npz", "native/history.csv", "native/balance.csv",
    "native/progress.json", "native/console.log", *[f + ".tif" for f in FIELDS],
}
REQUIRED = {"grids.npz", "summary.json", "request.json", "provenance.json",
            "rainfall.json", *[f + ".tif" for f in FIELDS]}
MAX_ARCHIVE = 80 * 1024 * 1024
MAX_EXPANDED = 160 * 1024 * 1024


def _read_members(blob):
    if len(blob) > MAX_ARCHIVE:
        raise ValueError("結果 ZIP 超過 80 MB，請使用這個專案原本下載的結果包。")
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(infos) > 128 or len({n.casefold() for n in names}) != len(names):
                raise ValueError("ZIP 有重複檔名或過多檔案。")
            if sum(i.file_size for i in infos) > MAX_EXPANDED:
                raise ValueError("ZIP 解開後過大，無法載入比較。")
            for info in infos:
                path = PurePosixPath(info.filename)
                if (not info.filename or info.filename != info.orig_filename or path.is_absolute()
                        or ".." in path.parts or "\\" in info.filename or ":" in info.filename
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                    raise ValueError("ZIP 含不接受的路徑、連結或加密檔。")
            if not REQUIRED.issubset(names):
                raise ValueError("這不是完整的信義區結果包；請使用「下載結果包（含 QGIS）」的 ZIP。")
            members = {}
            for info in infos:
                if info.filename not in ALLOWED:
                    continue
                limit = 18 * 1024 * 1024 if info.filename.endswith(".npz") else 8 * 1024 * 1024
                if info.file_size > limit:
                    raise ValueError("結果檔大小超過本版支援範圍。")
                members[info.filename] = archive.read(info)
        summary = json.loads(members["summary.json"].decode("utf-8-sig"))
        checks = summary.get("checks", {})
        if summary.get("passed") is not True or not checks or not all(v is True for v in checks.values()):
            raise ValueError("這筆結果尚未通過原有數值檢查，不能列為完成結果。")
        # NPZ is itself a ZIP. Bound its expanded size before NumPy touches it.
        for name in ("grids.npz", "rain_input.npz"):
            if name not in members:
                continue
            with zipfile.ZipFile(BytesIO(members[name])) as inner:
                entries = inner.infolist()
                if len(entries) > 10 or sum(i.file_size for i in entries) > 20 * 1024 * 1024:
                    raise ValueError("格網資料大小超過本版支援範圍。")
                if name == "grids.npz" and {i.filename for i in entries} != {f + ".npy" for f in FIELDS}:
                    raise ValueError("格網欄位與本專案不符。")
                if len({i.filename for i in entries}) != len(entries):
                    raise ValueError("格網資料有重複欄位。")
        return members
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("結果包格式損壞，請重新選擇原本下載的 ZIP。") from exc


def import_comparison_zip(blob, token):
    """No archive paths are executed or extracted; only fixed allowlisted files are saved."""
    members = _read_members(blob)
    digest = sha256(blob).hexdigest()
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(STATE_ROOT / "comparison-import.lock"), timeout=3):
            return _save_import(members, digest, token)
    except Timeout as exc:
        raise ValueError("另一筆結果正在載入，請稍後再試。") from exc


def _save_import(members, digest, token):
    parent = STATE_ROOT / "comparisons" / owner_key(token)[:24]
    folder = parent / digest[:24]
    if (folder / "import_source.json").exists():
        if json.loads((folder / "import_source.json").read_text(encoding="utf-8"))["sha256"] != digest:
            raise ValueError("結果識別衝突，請重新整理後再試。")
        return folder
    # Each session is bounded; it cannot read another visitor's uploads.
    if parent.exists() and len(list(parent.glob("*/import_source.json"))) >= 6:
        raise ValueError("這個分頁已載入 6 筆結果；請先從清單選擇既有結果。")
    planned = sum(len(v) for v in members.values()) + 4096
    used = sum(p.stat().st_size for p in STATE_ROOT.rglob("*") if p.is_file())
    comparison_root = STATE_ROOT / "comparisons"
    comparison_used = sum(p.stat().st_size for p in comparison_root.rglob("*") if p.is_file())
    if (used + planned > 1_500_000_000 or comparison_used + planned > 350_000_000
            or shutil.disk_usage(STATE_ROOT).free - planned < 600_000_000):
        raise ValueError("伺服器暫存空間不足，這次沒有寫入。請先比較清單中的既有結果。")
    stage = parent / (digest[:24] + "." + uuid.uuid4().hex[:8] + ".tmp")
    stage.mkdir(parents=True, exist_ok=False)
    try:
        for name, content in members.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        # Validate real CRS/grid/data/source before making this upload selectable.
        from comparison_data import build_comparison
        build_comparison(stage, stage, "載入結果", "載入結果", "max_depth_m")
        json_save(stage / "import_source.json", {"sha256": digest, "source": "visitor_result_zip",
                  "scope": "result-format/grid checks; not an independent solver rerun"})
        stage.rename(folder)
    except Exception:
        # Only remove the exact staging directory just created under our own session.
        if stage.resolve().parent == parent.resolve() and stage.name.endswith(".tmp"):
            shutil.rmtree(stage)
        raise
    return folder
