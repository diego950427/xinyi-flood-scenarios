"""Reproducible, project-local native SWMM 5.2.4 + C# coupling runtime.

No download, package installation or system configuration happens here. Linux
dependencies are declared in packages.txt and official solver sources are bundled.
Each calculation is a separate process because SWMM has process-global state.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from filelock import FileLock

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "engine"
VENDOR = ENGINE / "vendor" / "Stormwater-Management-Model-5.2.4"
RUNTIME_ROOT = Path(os.environ.get("XINYI_RUNTIME_ROOT", ROOT / ".runtime")).resolve()
VERSION = 52004


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _source_fingerprint() -> str:
    manifest = json.loads((ENGINE / "vendor" / "source_manifest.json").read_text())
    h = hashlib.sha256()
    for rel, expected in sorted(manifest["files"].items()):
        actual = digest(VENDOR / rel)
        if actual != expected:
            raise RuntimeError("Bundled EPA source integrity mismatch: " + rel)
        h.update((rel + actual).encode())
    for path in sorted(ENGINE.glob("*.cs")):
        h.update((path.name + digest(path)).encode())
    h.update(Path(__file__).read_bytes())
    h.update((platform.system() + platform.machine()).encode())
    if os.name == "nt":
        supplied = os.environ.get("XINYI_SWMM_LIBRARY")
        h.update(("external:" + digest(Path(supplied).resolve(strict=True))).encode() if supplied else b"vendored-gcc")
    return h.hexdigest()


def _tool(name: str) -> str:
    result = shutil.which(name)
    if not result:
        raise RuntimeError(f"Missing native build dependency {name}; see packages.txt / README.")
    return result


def _run(command: list[str], log, *, env=None, cwd=None) -> None:
    # Commands are argument arrays, never interpreted by a shell.
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                            env=env, cwd=cwd, timeout=300,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    log.flush()
    if result.returncode:
        raise RuntimeError(f"Native build failed ({Path(command[0]).name}); see .runtime/build.log.")


def _library_version(library: Path) -> int:
    loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
    lib = loader(str(library))
    lib.swmm_getVersion.argtypes = []
    lib.swmm_getVersion.restype = ctypes.c_int
    value = int(lib.swmm_getVersion())
    if value != VERSION:
        raise RuntimeError(f"Expected official SWMM 5.2.4 (52004), got {value}.")
    return value


def ensure_runtime() -> dict:
    """Return command prefix, binary/library paths and verified SHA-256 evidence.

    Call once at worker startup. Builds are protected across browser sessions and
    workers. Cache identity includes exact upstream + coupling source content.
    Windows can use an existing official DLL via XINYI_SWMM_LIBRARY, or compile
    the same vendored source with an available GCC via XINYI_CC.
    """
    if sys.byteorder != "little" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise RuntimeError("This result format requires a tested 64-bit little-endian host.")
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    fingerprint = _source_fingerprint()
    native_bin = RUNTIME_ROOT / "bin" / fingerprint[:16]
    native_bin.mkdir(parents=True, exist_ok=True)
    executable = native_bin / "CoupledEngine.exe"
    library = native_bin / ("swmm5.dll" if os.name == "nt" else "libswmm5.so")
    stamp = native_bin / "runtime.json"
    with FileLock(str(RUNTIME_ROOT / "build.lock"), timeout=360):
        valid = False
        if stamp.exists() and executable.exists() and library.exists():
            saved = json.loads(stamp.read_text())
            valid = (saved.get("fingerprint") == fingerprint
                     and saved.get("engine_sha256") == digest(executable)
                     and saved.get("library_sha256") == digest(library))
            if os.name != "nt":
                config = executable.with_suffix(".exe.config")
                valid = valid and config.exists() and saved.get("dllmap_sha256") == digest(config)
        if not valid:
            with (RUNTIME_ROOT / "build.log").open("w", encoding="utf-8") as log:
                if os.name == "nt":
                    supplied = os.environ.get("XINYI_SWMM_LIBRARY")
                    if supplied:
                        source = Path(supplied).resolve(strict=True)
                        # The runtime dependency DLLs remain beside the chosen original.
                        # Copy only the exact requested solver; use OS-supported DLL dirs.
                        shutil.copy2(source, library)
                        for name in ("vcruntime140.dll", "vcruntime140_1.dll", "vcomp140.dll"):
                            if (source.parent / name).exists():
                                shutil.copy2(source.parent / name, native_bin / name)
                    else:
                        compiler = os.environ.get("XINYI_CC") or _tool("gcc")
                        source_dir = VENDOR / "src" / "solver"
                        c_files = sorted(source_dir.glob("*.c"))
                        compiler_env = dict(os.environ)
                        compiler_env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + compiler_env.get("PATH", "")
                        # MinGW's linker can reject Unicode absolute output paths.
                        # All vendored and build paths share the project root, so
                        # relative filenames stay ASCII without relocating data.
                        _run([compiler, "-shared", "-O2", "-static-libgcc", "-o",
                              os.path.relpath(library, source_dir), "-Iinclude",
                              *[p.name for p in c_files], "-lm"], log,
                             cwd=source_dir, env=compiler_env)
                    csc = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
                    if not csc.exists():
                        raise RuntimeError("The .NET Framework 64-bit C# compiler is unavailable.")
                    _run([str(csc), "/nologo", "/optimize+", "/platform:x64", "/out:" + str(executable),
                          str(ENGINE / "SurfaceEngine.cs"), str(ENGINE / "NativeCoupling.cs")], log)
                elif platform.system() == "Linux":
                    build_dir = RUNTIME_ROOT / "build" / fingerprint[:16]
                    _run([_tool("cmake"), "-S", str(VENDOR), "-B", str(build_dir),
                          "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTS=OFF"], log)
                    _run([_tool("cmake"), "--build", str(build_dir), "--target", "swmm5", "--parallel", "2"], log)
                    candidates = list(build_dir.rglob("libswmm5.so"))
                    if not candidates:
                        raise RuntimeError("EPA native build produced no shared library.")
                    shutil.copy2(candidates[0], library)
                    _run([_tool("mcs"), "-optimize+", "-platform:x64", "-define:UNIX",
                          "-out:" + str(executable), str(ENGINE / "SurfaceEngine.cs"),
                          str(ENGINE / "NativeCoupling.cs")], log)
                    # A relative dllmap resolves beside the managed executable, not cwd.
                    executable.with_suffix(".exe.config").write_text(
                        '<configuration><dllmap dll="swmm5.dll" target="libswmm5.so" os="linux" /></configuration>\n',
                        encoding="utf-8")
                else:
                    raise RuntimeError("Supported native hosts are 64-bit Windows and Linux.")
                version = _library_version(library)
                saved = {"fingerprint": fingerprint, "version": version,
                         "engine_sha256": digest(executable), "library_sha256": digest(library),
                         "platform": platform.system(), "machine": platform.machine(),
                         "library_origin": "external-user-selected" if os.name == "nt" and os.environ.get("XINYI_SWMM_LIBRARY") else "built-from-vendored-EPA",
                         "source_commit": "7952ca837988b1c32f791812eccc9fd64547e093"}
                if os.name != "nt":
                    saved["dllmap_sha256"] = digest(executable.with_suffix(".exe.config"))
                stamp.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        version = _library_version(library)
    command = [str(executable)] if os.name == "nt" else [_tool("mono"), str(executable)]
    return {**saved, "command": command, "binary": str(executable), "library": str(library),
            "native_bin": str(native_bin), "runtime_root": str(RUNTIME_ROOT), "version": version}


if __name__ == "__main__":
    runtime = ensure_runtime()
    print(json.dumps(runtime, indent=2))
