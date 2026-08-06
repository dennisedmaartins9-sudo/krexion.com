"""
Krexion Desktop Updater — handles self-update flow
====================================================
Triggered from the dashboard's "Update Now" banner click. Steps:

  1. Download Krexion-Setup.exe to %TEMP% (license redirect → GitHub,
     or direct CDN fallback for native Setup-latest.exe)
  2. Launch installer with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
     /CLOSEAPPLICATIONS — Inno Setup will:
        * Stop the running Krexion services
        * Overwrite the program files
        * Restart the services
     User data (%PROGRAMDATA%\\Krexion + license) is preserved by virtue
     of being in a separate path the installer never touches.
  3. Exit current dashboard process (the fresh installer's [Run] section
     will spawn a new instance once install finishes).

This module is called BY the dashboard JS via a tiny endpoint
``/api/desktop/run-update`` exposed in desktop_module.py — keeps all
subprocess logic out of the browser sandbox.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

logger = logging.getLogger("krexion.updater")

CLOUD = os.environ.get("KREXION_CLOUD_URL", "https://krexion.com").rstrip("/")
LICENSE_FILE = Path(os.environ.get("LICENSE_KEY_FILE", "C:/ProgramData/Krexion/license-key.txt"))
# Stable native CDN path written by build-windows-release.yml
NATIVE_CDN_URL = os.environ.get(
    "KREXION_NATIVE_INSTALLER_URL",
    f"{CLOUD}/downloads/windows/Krexion-Setup-latest.exe",
)


def _read_license_key() -> str:
    try:
        return LICENSE_FILE.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""


def _stream_download(url: str, dest: Path, *, headers: dict | None = None) -> bool:
    """Stream a URL to dest. Returns True on HTTP 200 + non-empty file."""
    try:
        with requests.get(url, stream=True, timeout=120, allow_redirects=True, headers=headers or {}) as r:
            if r.status_code != 200:
                logger.error(f"Installer download HTTP {r.status_code} from {url}: {r.text[:200]}")
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        f.write(chunk)
            size = dest.stat().st_size if dest.exists() else 0
            if size < 1_000_000:
                # Real Setup.exe is hundreds of MB — tiny body is an error HTML page
                logger.error(f"Installer download too small ({size} bytes) from {url}")
                try:
                    dest.unlink(missing_ok=True)
                except Exception:  # noqa: BLE001
                    pass
                return False
            logger.info(f"Installer downloaded to {dest} ({size} bytes) from {url}")
            return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Installer download failed from {url}: {exc}")
        return False


def download_installer(target_version: str | None = None) -> Path | None:
    """Download the latest native installer .exe to %TEMP%.

    Order:
      1. License-gated redirect (admin-published GitHub asset)
      2. Public CDN Krexion-Setup-latest.exe (always mirrors latest native build)
    """
    suffix = f"-{target_version}" if target_version else ""
    dest = Path(tempfile.gettempdir()) / f"Krexion-Setup{suffix}.exe"

    key = _read_license_key()
    if key:
        license_url = f"{CLOUD}/api/license/download-installer/{key}"
        if _stream_download(license_url, dest):
            return dest
        logger.warning("License installer download failed — trying public CDN.")
    else:
        logger.warning("No license key file — trying public CDN for installer.")

    if _stream_download(NATIVE_CDN_URL, dest):
        return dest
    return None


def run_installer(installer_path: Path) -> bool:
    """Spawn the installer in silent-update mode. Returns True if the
    process was successfully launched (not necessarily completed)."""
    if not installer_path.exists():
        logger.error(f"Installer not found at {installer_path}")
        return False
    try:
        # /VERYSILENT       - no UI, no progress bar
        # /SUPPRESSMSGBOXES - auto-Yes for everything
        # /NORESTART        - we manage restart ourselves (services
        #                     auto-restart via NSSM AppExit=Restart)
        # /CLOSEAPPLICATIONS - close ours cleanly before overwriting
        # /RESTARTAPPLICATIONS - relaunch tray + services
        subprocess.Popen(
            [
                str(installer_path),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
        logger.info("Installer spawned in silent-update mode.")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Installer launch failed: {exc}")
        return False


def apply_update(target_version: str | None = None) -> dict:
    """High-level orchestrator the dashboard endpoint calls."""
    installer = download_installer(target_version)
    if installer is None:
        return {
            "ok": False,
            "stage": "download",
            "message": "Installer download failed. Check internet connection and try again.",
        }
    ok = run_installer(installer)
    if not ok:
        return {
            "ok": False,
            "stage": "launch",
            "message": "Could not launch installer. Antivirus may be blocking — please run as admin.",
        }
    return {
        "ok": True,
        "stage": "running",
        "message": "Installer started silently. Krexion will restart in a moment.",
        "installer": str(installer),
    }


if __name__ == "__main__":
    # Manual test entry point: `krexion-coreapp.exe -m desktop.updater`
    logging.basicConfig(level=logging.INFO)
    result = apply_update(target_version=sys.argv[1] if len(sys.argv) > 1 else None)
    print(result)
