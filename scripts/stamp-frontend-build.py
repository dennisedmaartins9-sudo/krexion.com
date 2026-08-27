#!/usr/bin/env python3
"""Stamp + verify a production frontend build before native installer packaging."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

UI_FRESHNESS_MARKER = "Krexion Browser Profiles"
STALE_UI_MARKER = "AdsPower/GoLogin-style"
BUILD_VERSION_FILENAME = "build-version.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_version(repo: Path) -> str:
    return (repo / "backend" / "VERSION").read_text(encoding="utf-8").strip()


def _resolve_build_dir(repo: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    for candidate in (repo / "frontend" / "build", repo / "build" / "frontend-build"):
        if (candidate / "index.html").exists():
            return candidate
    raise SystemExit("frontend build directory not found (run yarn build first)")


def _find_main_js(build_dir: Path) -> Path:
    static_js = build_dir / "static" / "js"
    if not static_js.exists():
        raise SystemExit(f"missing {static_js}")
    mains = sorted(static_js.glob("main.*.js"))
    if not mains:
        raise SystemExit("no main.*.js bundle found")
    return mains[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", help="frontend build directory override")
    args = parser.parse_args()

    repo = _repo_root()
    version = _read_version(repo)
    build_dir = _resolve_build_dir(repo, args.dir)
    main_js = _find_main_js(build_dir)
    body = main_js.read_text(encoding="utf-8", errors="ignore")

    if STALE_UI_MARKER in body:
        raise SystemExit(f"stale UI text found in {main_js.name}")
    if UI_FRESHNESS_MARKER not in body:
        raise SystemExit(f"freshness marker missing from {main_js.name}")

    stamp = {
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "marker": "krexion-browser-profiles-v1",
        "main_js": main_js.name,
    }
    (build_dir / BUILD_VERSION_FILENAME).write_text(
        json.dumps(stamp, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK stamped frontend build {version} → {build_dir / BUILD_VERSION_FILENAME}")


if __name__ == "__main__":
    main()
