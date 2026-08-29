"""
Native frontend bundle version stamp + cloud sync.

Prevents the "backend updated but UI still looks old" failure mode:
  • CI stamps build-version.json into every production frontend bundle
  • Native backend compares backend/VERSION vs bundled UI on startup
  • When stale, downloads matching zip from krexion.com/downloads/ui/
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).parent / "VERSION"
BUILD_VERSION_FILENAME = "build-version.json"

# Substring that must exist in main.*.js — catches same-version stale bundles.
UI_FRESHNESS_MARKER = "Krexion Browser Profiles"
STALE_UI_MARKER = "AdsPower/GoLogin-style"

_sync_lock = threading.Lock()


def current_backend_version() -> str:
    try:
        if VERSION_FILE.exists():
            return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except Exception:  # noqa: BLE001
        pass
    return "0.0.0"


def resolve_frontend_dir() -> Optional[Path]:
    """Resolve the directory that serves the native React SPA."""
    env_dir = os.environ.get("FRONTEND_BUILD_DIR", "").strip()
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))
    root = Path(__file__).resolve().parent
    candidates.extend([
        root.parent.parent / "frontend",            # Inno: {app}/frontend
        root.parent.parent / "frontend" / "build",
        root.parent / "frontend",
        root.parent / "frontend" / "build",
        Path("/app/frontend/build"),
    ])
    for candidate in candidates:
        try:
            if candidate.exists() and (candidate / "index.html").exists():
                return candidate
        except Exception:  # noqa: BLE001
            continue
    return None


def read_frontend_bundle_meta(fe_dir: Optional[Path]) -> dict[str, Any]:
    if not fe_dir:
        return {}
    stamp = fe_dir / BUILD_VERSION_FILENAME
    if not stamp.exists():
        return {}
    try:
        data = json.loads(stamp.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def read_frontend_bundle_version(fe_dir: Optional[Path]) -> Optional[str]:
    version = read_frontend_bundle_meta(fe_dir).get("version")
    if not version:
        return None
    return str(version).strip().lstrip("vV")


def _find_main_js(fe_dir: Path) -> Optional[Path]:
    static_js = fe_dir / "static" / "js"
    if not static_js.exists():
        return None
    mains = sorted(static_js.glob("main.*.js"), key=lambda p: p.stat().st_mtime, reverse=True)
    return mains[0] if mains else None


def _main_js_is_stale(fe_dir: Path) -> bool:
    main_js = _find_main_js(fe_dir)
    if not main_js:
        return True
    try:
        body = main_js.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return True
    if STALE_UI_MARKER in body:
        return True
    if UI_FRESHNESS_MARKER not in body:
        return True
    return False


def frontend_bundle_is_stale(
    fe_dir: Optional[Path] = None,
    backend_version: Optional[str] = None,
) -> bool:
    """True when the bundled SPA should be replaced."""
    fe_dir = fe_dir or resolve_frontend_dir()
    if not fe_dir or not fe_dir.exists():
        return True

    backend_version = (backend_version or current_backend_version()).lstrip("vV").strip()
    bundled_ver = read_frontend_bundle_version(fe_dir)
    if not bundled_ver:
        return True
    if bundled_ver.lstrip("vV") != backend_version:
        return True
    return _main_js_is_stale(fe_dir)


def cloud_ui_bundle_url(version: str) -> str:
    cloud = (os.environ.get("KREXION_CLOUD_URL") or "https://krexion.com").rstrip("/")
    ver = version.lstrip("vV").strip()
    return f"{cloud}/downloads/ui/krexion-ui-{ver}.zip"


def sync_frontend_from_cloud(
    fe_dir: Optional[Path] = None,
    version: Optional[str] = None,
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    """Download the cloud UI zip for *version* and atomically replace *fe_dir*."""
    version = (version or current_backend_version()).lstrip("vV").strip()
    fe_dir = fe_dir or resolve_frontend_dir()
    if not fe_dir:
        return {"ok": False, "error": "frontend_dir_not_found"}

    url = cloud_ui_bundle_url(version)
    if not _sync_lock.acquire(blocking=False):
        return {"ok": False, "error": "sync_already_running"}

    try:
        logger.info("[frontend-sync] downloading %s → %s", url, fe_dir)
        resp = requests.get(url, timeout=timeout, stream=True)
        if resp.status_code != 200:
            return {
                "ok": False,
                "error": f"download_failed_http_{resp.status_code}",
                "url": url,
            }

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "ui.zip"
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)

            extract_dir = Path(tmp) / "extract"
            extract_dir.mkdir()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            bundle_root = extract_dir
            if not (bundle_root / "index.html").exists():
                nested = [p for p in extract_dir.iterdir() if p.is_dir()]
                if len(nested) == 1 and (nested[0] / "index.html").exists():
                    bundle_root = nested[0]
                else:
                    return {"ok": False, "error": "invalid_zip_layout", "url": url}

            parent = fe_dir.parent
            parent.mkdir(parents=True, exist_ok=True)
            backup = parent / f"frontend.old.{version}"
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            if fe_dir.exists():
                if fe_dir.is_dir():
                    shutil.move(str(fe_dir), str(backup))
                else:
                    fe_dir.unlink()
            shutil.copytree(bundle_root, fe_dir)
            try:
                shutil.rmtree(backup, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass

        still_stale = frontend_bundle_is_stale(fe_dir, version)
        if still_stale:
            return {
                "ok": False,
                "error": "sync_completed_but_bundle_still_stale",
                "url": url,
                "path": str(fe_dir),
            }

        return {"ok": True, "version": version, "path": str(fe_dir), "url": url}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[frontend-sync] failed")
        return {"ok": False, "error": str(exc), "url": url}
    finally:
        _sync_lock.release()


def frontend_sync_status() -> dict[str, Any]:
    mode = (os.environ.get("KREXION_MODE") or "local").lower()
    backend_ver = current_backend_version()
    fe_dir = resolve_frontend_dir()
    fe_ver = read_frontend_bundle_version(fe_dir)
    stale = frontend_bundle_is_stale(fe_dir, backend_ver) if mode == "native" else False

    # Cloud: compare backend VERSION vs stamped bundle on frontend nginx.
    if mode == "cloud" and not fe_ver:
        for url in (
            "http://frontend/build-version.json",
            f"{(os.environ.get('KREXION_CLOUD_URL') or 'https://krexion.com').rstrip('/')}/build-version.json",
        ):
            try:
                resp = requests.get(url, timeout=8)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if isinstance(data, dict) and data.get("version"):
                    fe_ver = str(data["version"]).strip().lstrip("vV")
                    stale = fe_ver.lstrip("vV") != backend_ver.lstrip("vV")
                    break
            except Exception:  # noqa: BLE001
                continue

    return {
        "backend_version": backend_ver,
        "frontend_version": fe_ver,
        "frontend_dir": str(fe_dir) if fe_dir else None,
        "frontend_sync_needed": stale,
        "mode": mode,
    }
