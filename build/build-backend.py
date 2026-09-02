"""
Krexion Native Build — Embedded-Python Backend Bundler
======================================================

Produces a self-contained Windows directory at
``build/dist/krexion-backend.dist/`` that contains:

    krexion-core.exe          (renamed Python 3.11 embeddable interpreter)
    python311.dll             (CPython runtime, shipped alongside)
    python311.zip             (CPython stdlib)
    python311._pth            (path config — site-packages enabled)
    Lib/site-packages/        (all wheels from backend/requirements.txt)
    app/server.py             (Krexion FastAPI entrypoint)
    app/<all modules>         (license_module.py, releases_module.py, etc)
    app/Krexion-User-Package/ (legacy ZIP payload — bundled so the
                               native build can still serve it as a
                               fallback to old customers)

The renaming `python.exe` → `krexion-core.exe` is what makes Task
Manager / Services.msc / Process Explorer ONLY ever show the
customer-facing "krexion-core.exe" — no third-party python branding
leaks through. This is the same trick Calibre, Anki, and OBS use.

Run with:
    python build/build-backend.py

Or via the GitHub Actions workflow `.github/workflows/build-windows-release.yml`
which calls us on a `windows-latest` runner so wheels resolve natively.

Cross-platform note: this script is designed to run on **Windows
GitHub runners** (the artifact must contain real Windows binaries).
It does run on Linux too but only for layout / dry-run testing; the
resulting bundle won't actually execute on Windows because pip will
have resolved Linux wheels.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────
PY_VERSION = "3.11.9"
PY_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PY_VERSION}/"
    f"python-{PY_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
PAYLOAD_DIR = REPO_ROOT / "Krexion-User-Package"
BUILD_DIR = REPO_ROOT / "build"
DIST_DIR = BUILD_DIR / "dist" / "krexion-backend.dist"
FINGERPRINT_FILE = BUILD_DIR / ".deps-fingerprint"

# Packages we explicitly EXCLUDE from the native Windows bundle. Each
# entry is here for a concrete reason — see the trailing comment. The
# list is intentionally aggressive: we'd rather miss a niche feature
# than have the whole build fail because a Unix-only or mobile-tooling
# dep can't resolve a Windows wheel.
#
# Whenever you add a backend feature that actually USES one of these,
# remove it from this list and tag the line with `# REQUIRED FOR <feature>`.
EXCLUDE_PACKAGES = {
    # ── Unix-only (will fail at import OR install time on Windows) ───
    "daemonize",         # uses os.fork — Unix only; we use Windows Services instead
    "uvloop",            # libuv asyncio loop; no Windows support. uvicorn falls back to asyncio
    "pexpect",           # pty/fcntl-based — Unix only
    "ptyprocess",        # transitive of pexpect — Unix only
    "plumbum",           # SSH/local exec helper; Windows is half-broken & unused
    "pytun-pmd3",        # TUN/TAP networking — Unix only
    "sslpsk-pmd3",       # PSK SSL — C build issues on Windows
    # ── iOS / mobile-device automation (not used by native runtime) ──
    "adb_shell",
    "appium-python-client",
    "appium_python_client",
    "developer_disk_image",
    "pure-python-adb",
    "pymobiledevice3",
    "tidevice3",
    "pykdebugparser",
    "lzfse",             # iOS firmware compression
    "pyimg4",            # iOS .img4 format
    "pyusb",             # libusb — Unix-leaning, not needed for native Krexion
    "opack",             # Apple OPACK
    "hexdump",           # mobile debug tool
    "remotezip",
    "remotezip2",
    "pycrashreport",     # iOS crash report parser
    "ipsw-parser",
    "ipsw_parser",
    "librt",             # Linux real-time POSIX library
    "pygnuutils",        # GNU coreutils helper
    "bpylist2",          # Apple bplist
    "construct",         # binary struct parser — mostly used by iOS tools
    "qh3",               # HTTP/3 stack — flaky on Windows wheels
    # ── Dev / REPL tools (zero runtime use) ──────────────────────────
    "ipython",
    "ipython_pygments_lexers",
    "jedi",
    "parso",
    "asttokens",
    "stack-data",
    "stack_data",
    "executing",
    "pure_eval",
    "decorator",
    "matplotlib-inline",
    "matplotlib_inline",
    "prompt_toolkit",
    "blessed",
    "readchar",
    "inquirer3",
    "editor",
    "xonsh",
    # ── Linters / formatters (CI-only) ────────────────────────────────
    "black",
    "ruff",
    "pylint",
    "mypy",
    "mypy_extensions",
    "pytest",
    "pytest-asyncio",
    "pytest_asyncio",
    "pluggy",
    "iniconfig",
    "flake8",
    "isort",
    "pycodestyle",
    "pyflakes",
    "mccabe",
    "pytokens",
    # ── Heavy unused packages (huge size, zero backend imports) ──────
    "huggingface_hub",
    "huggingface-hub",
    "hf-xet",
    "hf_xet",
    "tokenizers",
    "scipy",
    "ImageHash",
    "imagehash",
    # ── Emergent internal helper (preview-pod only) ───────────────────
    "emergentintegrations",
}


def log(msg: str, prefix: str = "==>") -> None:
    print(f"{prefix} {msg}", flush=True)


def requirements_fingerprint(req_file: Path) -> str:
    """Stable hash — when this matches, pip/site-packages can be reused."""
    h = hashlib.sha256()
    h.update(req_file.read_bytes())
    h.update(PY_VERSION.encode("utf-8"))
    h.update(b"|".join(sorted(p.encode("utf-8") for p in EXCLUDE_PACKAGES)))
    return h.hexdigest()


def deps_cache_valid(req_file: Path) -> bool:
    """True when a prior build left a complete embed Python + wheels."""
    site_pkg = DIST_DIR / "Lib" / "site-packages"
    python_exe = DIST_DIR / ("python.exe" if os.name == "nt" else "python")
    if not site_pkg.is_dir() or not python_exe.exists():
        return False
    if not FINGERPRINT_FILE.exists():
        return False
    try:
        return FINGERPRINT_FILE.read_text(encoding="utf-8").strip() == requirements_fingerprint(req_file)
    except OSError:
        return False


def write_deps_fingerprint(req_file: Path) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(requirements_fingerprint(req_file), encoding="utf-8")


def _python_exe() -> Path:
    return DIST_DIR / ("python.exe" if os.name == "nt" else "python")


def _pip_base_args(python_exe: Path) -> list[str]:
    return [
        str(python_exe), "-m", "pip", "install",
        "--no-warn-script-location",
        "--no-compile",
        "--prefer-binary",
        "--disable-pip-version-check",
    ]


def _install_desktop_packages(python_exe: Path) -> None:
    """Desktop dashboard packages — allow sdist for pure-Python deps."""
    desktop_pkgs = [
        "pywebview==5.4",
        "pystray==0.19.5",
        "Pillow==10.4.0",
        "pythonnet==3.0.3",
        "psutil==6.1.0",
        "proxy-tools==0.1.0",
        "bottle>=0.12.25",
        "typing_extensions>=4.0",
    ]
    log("Installing desktop dashboard packages (allow sdist fallback)")
    r = subprocess.run(
        [*_pip_base_args(python_exe), "--upgrade", *desktop_pkgs],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        tail = (r.stdout + r.stderr).strip().splitlines()[-15:]
        log("  desktop package install non-zero exit:", prefix="!!!")
        for line in tail:
            log(f"    {line}")
    else:
        log("  desktop packages OK")


def fast_rebuild_from_cached_deps(req_file: Path) -> None:
    """Reuse cached site-packages when requirements unchanged (~3-8 min)."""
    log("FAST BUILD — requirements unchanged, reusing cached site-packages")
    python_exe = _python_exe()
    enable_site_packages()
    _install_desktop_packages(python_exe)
    verify_core_packages(python_exe)
    # Refresh source layers only — deps stay cached.
    app_dir = DIST_DIR / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir, ignore_errors=True)
    copy_backend_source()
    compile_strip_backend_source()
    copy_desktop_package()
    rebrand_python_exe()
    write_build_manifest()
    write_deps_fingerprint(req_file)


def ensure_clean_dist() -> None:
    if DIST_DIR.exists():
        log(f"Removing previous build at {DIST_DIR}")
        shutil.rmtree(DIST_DIR, ignore_errors=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)


def download(url: str, dest: Path) -> None:
    log(f"Downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    log(f"  -> {dest}  ({dest.stat().st_size // 1024} KB)")


def extract_embed_python() -> None:
    """Download the official python-3.11.x-embed-amd64.zip and unzip
    its contents directly into DIST_DIR so we end up with the layout
    Inno Setup expects (krexion-core.exe at the root of {app}\\bin)."""
    zip_path = BUILD_DIR / f"python-{PY_VERSION}-embed.zip"
    if not zip_path.exists():
        download(PY_EMBED_URL, zip_path)
    log(f"Extracting {zip_path.name} into {DIST_DIR}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(DIST_DIR)


def enable_site_packages() -> None:
    """The embeddable distribution ships with `python311._pth` that
    intentionally disables `import site` (so it stays minimal). We
    flip that ON so `Lib/site-packages` becomes importable — which is
    what pip-installed wheels rely on."""
    pth = next(DIST_DIR.glob("python*._pth"), None)
    if not pth:
        raise RuntimeError("python*._pth not found inside embed zip — layout changed?")
    log(f"Enabling site-packages in {pth.name}")
    content = pth.read_text(encoding="utf-8")
    # Uncomment the "#import site" line + add Lib/site-packages on path
    content = content.replace("#import site", "import site")
    if "Lib\\site-packages" not in content:
        content += "\nLib\\site-packages\napp\n"
    pth.write_text(content, encoding="utf-8")


def install_pip() -> None:
    """Bootstrap pip into the embed Python."""
    get_pip = BUILD_DIR / "get-pip.py"
    if not get_pip.exists():
        download(GET_PIP_URL, get_pip)
    python_exe = DIST_DIR / ("python.exe" if os.name == "nt" else "python")
    if not python_exe.exists():
        # On Linux dry-runs the embed zip doesn't include a working
        # interpreter; skip pip install but keep the layout intact so
        # the rest of the script can at least be validated.
        log("python.exe not found (cross-platform dry-run?) — skipping pip bootstrap")
        return
    log("Bootstrapping pip into embed Python")
    subprocess.run([str(python_exe), str(get_pip), "--no-warn-script-location"], check=True)


def filtered_requirements() -> Path:
    """Write a requirements file that drops packages we don't want in
    the native bundle (iOS/Android, dev linting, Emergent internals).

    Package names are normalised (lowercase + ``-`` → ``_``) before
    comparison so we catch both ``pytest-asyncio`` and ``pytest_asyncio``,
    ``HuggingFace_hub`` and ``huggingface-hub``, etc.
    """
    def norm(s: str) -> str:
        return s.lower().replace("-", "_")

    excluded_norm = {norm(p) for p in EXCLUDE_PACKAGES}

    src = BACKEND_DIR / "requirements.txt"
    dst = BUILD_DIR / "requirements-native.txt"
    keep, skipped = [], []
    for raw_line in src.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            keep.append(raw_line)
            continue
        pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
        if norm(pkg) in excluded_norm:
            skipped.append(pkg)
            continue
        keep.append(raw_line)
    dst.write_text("\n".join(keep) + "\n", encoding="utf-8")
    log(f"Filtered requirements: {len(keep)} keep, {len(skipped)} excluded → {dst.name}")
    for s in skipped:
        log(f"  excluded: {s}", prefix="   ")
    return dst


def pip_install_requirements(req_file: Path) -> None:
    """Install all filtered requirements with a resilient two-pass strategy:

      1. **Bulk install** -r requirements-native.txt — fastest path.
      2. If that fails (any single package not resolving a Windows wheel
         is enough to abort pip's whole transaction), fall back to a
         **per-package** install with ``--no-deps`` and SKIP packages
         that fail. We then verify that the CORE Krexion runtime
         packages (fastapi, uvicorn, motor, pymongo, pydantic, etc) are
         present and importable — only THAT determines build success.

    This means a new transitive dep introduced upstream that has no
    Windows wheel won't block the entire native build any more.
    """
    python_exe = DIST_DIR / ("python.exe" if os.name == "nt" else "python")
    if not python_exe.exists():
        log("Cross-platform dry-run — skipping pip install")
        return

    # ── Pass 1: bulk install (fast path) ─────────────────────────────
    log("Pass 1: bulk install -r " + req_file.name)
    r = subprocess.run(
        [
            *_pip_base_args(python_exe),
            "--only-binary", ":all:",
            "-r", str(req_file),
        ],
        check=False,
    )
    if r.returncode == 0:
        log("  bulk install OK")
        verify_core_packages(python_exe)
        return

    log(f"  bulk install returned exit {r.returncode} — falling back to per-package", prefix="!!!")

    # ── Pass 2: batched install, skip-on-failure ─────────────────────
    failed: list[str] = []
    succeeded = 0
    lines = [
        l.strip() for l in req_file.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]
    batch_size = 30
    log(f"Pass 2: installing {len(lines)} packages in batches of {batch_size}")
    for start in range(0, len(lines), batch_size):
        batch = lines[start:start + batch_size]
        r = subprocess.run(
            [
                *_pip_base_args(python_exe),
                "--only-binary", ":all:",
                *batch,
            ],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            succeeded += len(batch)
            continue
        # Fall back to singles only for this batch.
        for line in batch:
            pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
            r1 = subprocess.run(
                [*_pip_base_args(python_exe), "--only-binary", ":all:", line],
                capture_output=True, text=True,
            )
            if r1.returncode == 0:
                succeeded += 1
            else:
                failed.append(pkg)
                tail = (r1.stderr or "").strip().splitlines()[-3:]
                log(f"  skip {pkg}: " + " | ".join(tail), prefix="  ⚠")

    log(f"Pass 2 done: {succeeded} installed, {len(failed)} skipped")
    if failed:
        log("Skipped (no Windows wheel / install error):")
        for p in failed:
            log(f"  - {p}")

    # ── Pass 3: GUARANTEE the desktop dashboard packages are installed ──
    # v1.0.12 fix: passes 1 & 2 use --only-binary :all: which makes pip
    # refuse to install ANY package (including pure-Python ones like
    # `proxy_tools`, a pywebview dependency) that doesn't ship a wheel.
    # Result: `pip install pywebview==5.4` died on its proxy_tools dep,
    # pywebview itself got silently SKIPPED, the build still succeeded
    # because verify_core_packages didn't check for pywebview, and the
    # customer's installed app crashed with:
    #   ModuleNotFoundError: No module named 'webview'
    # ...the moment they double-clicked the desktop icon. This is the
    # ACTUAL root cause of the v1.0.4-1.0.11 "software open ni hota" bug.
    #
    # Fix: install pywebview + pystray + Pillow + pythonnet + their
    # pure-Python deps WITHOUT the --only-binary constraint, allowing
    # pip to fall back to sdist for the handful of source-only packages
    # (proxy_tools, bottle's older versions, etc). These packages are
    # pure-Python source distributions that build instantly without a
    # C compiler, so allowing sdist here is safe and adds ~5 s to the
    # build.
    _install_desktop_packages(python_exe)
    verify_core_packages(python_exe)


def verify_core_packages(python_exe: Path) -> None:
    """Hard-fail the build only if the CORE Krexion runtime packages
    aren't importable. Everything else is best-effort.

    v1.0.12 fix: added the desktop-dashboard packages (webview, pystray,
    PIL) to the verification list. Pre-1.0.12 builds could ship without
    these and the customer install would crash on first launch with
    'ModuleNotFoundError: No module named webview'. Adding them to the
    verify list means the BUILD fails loudly if pip silently skipped
    one - much better than discovering it post-install.
    """
    core = [
        "fastapi", "uvicorn", "starlette", "pydantic", "pydantic_core",
        "motor", "pymongo", "bcrypt", "cryptography", "httpx",
        "passlib", "jose", "stripe", "playwright",
        # Desktop dashboard runtime - missing one of these means the
        # customer's krexion-tray.bat crashes silently at import time.
        "webview", "pystray", "PIL", "psutil",
    ]
    log("Verifying core packages importable: " + ", ".join(core))
    code = "; ".join(f"import {p}" for p in core)
    r = subprocess.run([str(python_exe), "-c", code], capture_output=True, text=True)
    if r.returncode != 0:
        # Surface which import failed
        raise RuntimeError(
            f"Core-package import failed (stderr trimmed):\n  {r.stderr.strip().splitlines()[-1]}"
        )
    log("  all core packages OK")


def copy_backend_source() -> None:
    """Copy the FastAPI backend source files into bundle/app/.

    We DON'T copy the entire backend folder — only the .py files and
    helper assets the runtime actually needs. Skips __pycache__,
    tests/, .env, and any node_modules-like artefacts.
    """
    app_dir = DIST_DIR / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    skip_dirs = {
        "__pycache__",
        "tests",
        "test_data",
        ".pytest_cache",
        # Runtime data folders — populated at runtime by the SaaS backend
        # in this dev pod. They are NOT source code and we don't want to
        # ship 100 MB of someone else's RUT screenshots / recorder
        # sessions / upload artefacts in every customer's installer.
        # On the customer's PC these folders get recreated empty on
        # first run by the native runtime.
        "real_user_traffic_results",
        "visual_recorder_sessions",
        "form_filler_results",
        "uploaded_resources",
        "demo_results",
    }
    skip_files = {".env", ".gitignore"}

    copied = 0
    for src in BACKEND_DIR.rglob("*"):
        if any(part in skip_dirs for part in src.parts):
            continue
        if src.name in skip_files:
            continue
        # v1.0.22 fix: include extension-less filenames like `VERSION`
        # explicitly. Previously the suffix-allowlist skipped VERSION,
        # so the bundled backend had NO version file and _read_version
        # fell back to the hardcoded 1.0.17 in desktop/__init__.py.
        # That's why the customer's v1.0.21 install kept showing v1.0.17
        # in the dashboard top-right pill.
        allowed_suffix = src.suffix in {".py", ".json", ".html", ".txt", ".md", ".yml", ".yaml", ".ico", ".png", ".js"}
        allowed_no_suffix = src.is_file() and src.suffix == "" and src.name in {"VERSION"}
        if src.is_file() and (allowed_suffix or allowed_no_suffix):
            rel = src.relative_to(BACKEND_DIR)
            dest = app_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    log(f"Copied {copied} backend source files into {app_dir}")


# Scripts launched via `python -m …` or subprocess must keep readable .py sources.
_NATIVE_KEEP_PY = frozenset({
    "server.py",
    "krexion_mobile_shell_host.py",
})


def compile_strip_backend_source() -> None:
    """Compile backend to .pyc and remove .py sources (native IP protection).

    Same goal as the cloud Docker image: customers inspecting
    ``Program Files\\Krexion\\bin\\app`` see bytecode artefacts, not
    readable Python. Entry/subprocess scripts stay as .py.
    """
    import compileall

    app_dir = DIST_DIR / "app"
    if not app_dir.is_dir():
        return
    log("Bytecode-compiling native backend (strip .py sources)")
    compileall.compile_dir(
        str(app_dir),
        force=True,
        quiet=1,
        legacy=True,
    )
    stripped = 0
    for py in app_dir.rglob("*.py"):
        if py.name in _NATIVE_KEEP_PY:
            continue
        if "tests" in py.parts:
            continue
        try:
            py.unlink()
            stripped += 1
        except OSError as exc:
            log(f"  could not strip {py.name}: {exc}", prefix="   ")
    log(f"  stripped {stripped} .py files (kept {', '.join(sorted(_NATIVE_KEEP_PY))})")

    # Also bundle the legacy Krexion-User-Package so /api/license/
    # download-installer can still serve the ZIP fallback to older
    # customers who don't get the native redirect path yet.
    if PAYLOAD_DIR.exists():
        dest = app_dir / "Krexion-User-Package"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(PAYLOAD_DIR, dest)
        log(f"Bundled legacy ZIP payload at {dest}")


def rebrand_python_exe() -> None:
    """Rename python.exe → krexion-core.exe so Task Manager only ever
    shows our customer-facing name. python.exe is just a small launcher
    that loads python311.dll, so any renamed copy still works the
    same way.

    Same trick for pythonw.exe → krexion-coreapp.exe (the GUI-mode
    interpreter used by the desktop dashboard / tray app).

    Important: in v1.0.7 and earlier this function only COPIED the
    originals, which left python.exe + pythonw.exe sitting next to the
    renamed binaries. The 2026-01 white-label audit confirmed customers
    were still seeing "python.exe" in Task Manager (its PE Version Info
    field reads "Python" and is matched on by Task Manager's search).
    We now DELETE the originals after copying so only Krexion-branded
    binaries survive on disk. Admins who need `python -m pip` can call
    `krexion-core.exe -m pip ...` — the renamed binary behaves
    identically.
    """
    if os.name != "nt":
        log("Cross-platform dry-run — skipping .exe rename")
        return

    mapping = [
        ("python.exe", "krexion-core.exe"),
        ("pythonw.exe", "krexion-coreapp.exe"),  # GUI-mode (no console window)
    ]
    for src_name, dst_name in mapping:
        src = DIST_DIR / src_name
        dst = DIST_DIR / dst_name
        if src.exists():
            # shutil.copy2 preserves PE metadata. We then delete the
            # original so Task Manager never has a chance to display
            # the un-branded name.
            shutil.copy2(src, dst)
            try:
                src.unlink()
                log(f"  rebranded {src_name} -> {dst_name} (original removed)")
            except Exception as exc:  # noqa: BLE001
                # Don't fail the build if delete fails — copy is enough
                # for the rename to take effect. Log and continue.
                log(f"  rebranded {src_name} -> {dst_name} (could not delete original: {exc})")


def copy_desktop_package() -> None:
    """Copy the ``/desktop`` package into the bundle so the dashboard
    runs from ``krexion-coreapp.exe -m desktop.krexion_dashboard``.

    Lands at ``{DIST_DIR}/app/desktop/`` because:
      * ``python311._pth`` adds ``app`` to sys.path
      * The NSSM backend service sets ``AppDirectory={app}\\bin\\app``
      * `krexion-tray.bat` cds into the same directory before launching
    """
    src = REPO_ROOT / "desktop"
    if not src.exists():
        log("desktop/ package not found at repo root — skipping (dashboard will not be shipped)")
        return
    dest = DIST_DIR / "app" / "desktop"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".pytest_cache",
    ))
    # v1.0.22 fix: overwrite the bundled desktop/__init__.py so its
    # __version__ matches the CURRENT VERSION file (was hardcoded
    # 1.0.17 before, and that hardcode is what every fallback path
    # used → customer always saw "v1.0.17" in the dashboard pill).
    try:
        version_file = BACKEND_DIR / "VERSION"
        if version_file.exists():
            current_ver = version_file.read_text(encoding="utf-8").strip()
            init_path = dest / "__init__.py"
            if init_path.exists():
                txt = init_path.read_text(encoding="utf-8")
                import re as _re
                new_txt = _re.sub(
                    r'__version__\s*=\s*["\'][^"\']*["\']',
                    f'__version__ = "{current_ver}"',
                    txt,
                )
                init_path.write_text(new_txt, encoding="utf-8")
                log(f"Patched desktop/__init__.__version__ = {current_ver}")
    except Exception as exc:  # noqa: BLE001
        log(f"Could not sync desktop/__init__.__version__: {exc}")
    log(f"Bundled desktop dashboard at {dest}")


def write_build_manifest() -> None:
    """Drop a small JSON manifest next to the bundle that the Inno
    setup [Code] section can read for diagnostic / about-page use."""
    import json
    from datetime import datetime, timezone

    manifest = {
        "name": "Krexion Native Backend Bundle",
        "version": os.environ.get("KREXION_BUILD_VERSION", "dev"),
        "python_version": PY_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "built_on": f"{platform.system()} {platform.machine()}",
        "exclude_packages": sorted(EXCLUDE_PACKAGES),
    }
    (BUILD_DIR / "krexion-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    log("Wrote build/krexion-manifest.json")


def main() -> int:
    log(f"Krexion native backend build starting (host: {platform.system()})")
    log(f"  REPO_ROOT = {REPO_ROOT}")
    log(f"  DIST_DIR  = {DIST_DIR}")

    if not BACKEND_DIR.exists():
        log(f"ERROR: backend folder not found at {BACKEND_DIR}", prefix="!!!")
        return 1

    try:
        req = filtered_requirements()
        if deps_cache_valid(req):
            fast_rebuild_from_cached_deps(req)
        else:
            ensure_clean_dist()
            extract_embed_python()
            enable_site_packages()
            install_pip()
            pip_install_requirements(req)
            copy_backend_source()
            compile_strip_backend_source()
            copy_desktop_package()
            rebrand_python_exe()
            write_build_manifest()
            write_deps_fingerprint(req)
    except subprocess.CalledProcessError as e:
        log(f"ERROR: subprocess failed: {e}", prefix="!!!")
        return 2
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {type(e).__name__}: {e}", prefix="!!!")
        return 3

    # Final size report
    total = sum(p.stat().st_size for p in DIST_DIR.rglob("*") if p.is_file())
    log(f"Build OK — bundle size: {total / 1024 / 1024:.1f} MB at {DIST_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
