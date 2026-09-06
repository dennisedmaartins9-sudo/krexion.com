#!/usr/bin/env python3
"""
Bundle CloakBrowser C++ Chromium as Krexion Kernel for installers.

Usage:
  python backend/scripts/bundle_krexion_kernel.py --dest build/krexion-kernel [--platform windows-x64]

On Windows CI this downloads/ensures the Cloak binary and copies the chrome
tree into ``dest`` so Inno/Electron can ship AdsPower-class kernel offline.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve


def _download_windows_tree(dest: Path) -> Path:
    """Download Cloak windows-x64 archive and extract chrome.exe tree into dest."""
    try:
        from cloakbrowser.config import (  # type: ignore
            DOWNLOAD_BASE_URL,
            GITHUB_DOWNLOAD_BASE_URL,
            PLATFORM_CHROMIUM_VERSIONS,
        )
    except Exception as e:
        raise SystemExit(f"cloakbrowser package required: {e}") from e

    version = PLATFORM_CHROMIUM_VERSIONS.get("windows-x64") or ""
    if not version:
        raise SystemExit("cloakbrowser PLATFORM_CHROMIUM_VERSIONS missing windows-x64")

    archive = f"cloakbrowser-windows-x64.zip"
    urls = [
        f"{DOWNLOAD_BASE_URL}/chromium-v{version}/{archive}",
        f"{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{version}/{archive}",
    ]
    dest.mkdir(parents=True, exist_ok=True)
    tmp_zip = dest / archive
    last_err = None
    for url in urls:
        try:
            print(f"[krexion-kernel] downloading {url}")
            urlretrieve(url, tmp_zip)
            last_err = None
            break
        except Exception as e:
            last_err = e
            print(f"[krexion-kernel] download failed: {e}")
    if last_err is not None or not tmp_zip.is_file():
        raise SystemExit(f"failed to download Cloak windows kernel: {last_err}")

    extract = dest / "_extract"
    if extract.exists():
        shutil.rmtree(extract, ignore_errors=True)
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tmp_zip, "r") as zf:
        zf.extractall(extract)
    tmp_zip.unlink(missing_ok=True)

    # Find chrome.exe inside extract tree
    chrome = None
    for cand in extract.rglob("chrome.exe"):
        chrome = cand
        break
    if chrome is None:
        raise SystemExit("chrome.exe not found inside Cloak windows archive")

    # Copy sibling tree next to chrome.exe into dest root
    src_dir = chrome.parent
    for item in src_dir.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
    shutil.rmtree(extract, ignore_errors=True)
    out = dest / "chrome.exe"
    if not out.is_file():
        raise SystemExit(f"expected {out} after extract")
    return out


def _ensure_native_tree(dest: Path) -> Path:
    """Use cloakbrowser.ensure_binary on the current platform and copy tree."""
    try:
        import cloakbrowser  # type: ignore
    except Exception as e:
        raise SystemExit(f"cloakbrowser package required: {e}") from e

    path = Path(cloakbrowser.ensure_binary())
    if not path.is_file():
        raise SystemExit(f"cloak ensure_binary returned missing path: {path}")

    dest.mkdir(parents=True, exist_ok=True)
    src_dir = path.parent
    for item in src_dir.iterdir():
        target = dest / item.name
        try:
            if item.is_dir():
                if not target.exists():
                    shutil.copytree(item, target)
            else:
                # Rename chrome → keep chrome / chrome.exe name for resolver
                if item.name.lower() in ("chrome", "chrome.exe"):
                    target = dest / item.name
                shutil.copy2(item, target)
        except Exception as e:
            print(f"[krexion-kernel] copy skip {item.name}: {e}")

    # Guarantee expected binary name
    if sys.platform.startswith("win"):
        out = dest / "chrome.exe"
    else:
        out = dest / "chrome"
        if not out.is_file() and path.is_file():
            shutil.copy2(path, out)
    if not out.is_file():
        # fall back to whatever ensure returned, copied as chrome
        shutil.copy2(path, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True, help="Output folder (installer krexion-kernel/)")
    ap.add_argument(
        "--platform",
        default="",
        help="windows-x64|native (default: native = current OS)",
    )
    args = ap.parse_args()
    dest = Path(args.dest).resolve()
    platform = (args.platform or "native").strip().lower()

    if dest.exists():
        # Keep cache if chrome already present
        existing = dest / ("chrome.exe" if platform.startswith("win") or sys.platform.startswith("win") else "chrome")
        if existing.is_file() and not os.environ.get("KREXION_KERNEL_FORCE_REFRESH"):
            print(f"[krexion-kernel] cached {existing}")
            print(existing)
            return 0

    if platform in ("windows-x64", "win", "windows"):
        out = _download_windows_tree(dest)
    else:
        out = _ensure_native_tree(dest)

    print(f"[krexion-kernel] ready: {out} ({out.stat().st_size} bytes)")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
