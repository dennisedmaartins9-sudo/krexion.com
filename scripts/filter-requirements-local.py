#!/usr/bin/env python3
"""Write backend/requirements-local.txt for Windows LOCAL-START.

Uses the same EXCLUDE_PACKAGES list as build/build-backend.py so local
dev matches the native Windows bundle (no uvloop, emergentintegrations, etc.).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_backend", ROOT / "build" / "build-backend.py"
)
BB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BB)


def norm(name: str) -> str:
    return name.lower().replace("-", "_")


def main() -> int:
    excluded = {norm(p) for p in BB.EXCLUDE_PACKAGES}
    src = ROOT / "backend" / "requirements.txt"
    dst = ROOT / "backend" / "requirements-local.txt"
    keep: list[str] = []
    skipped: list[str] = []
    for raw_line in src.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            keep.append(raw_line)
            continue
        pkg = line.split("==")[0].split(">=")[0].split("<=")[0].split("[")[0].strip()
        if norm(pkg) in excluded:
            skipped.append(pkg)
            continue
        keep.append(raw_line)
    dst.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"[filter] {len(keep)} keep, {len(skipped)} excluded -> {dst.name}")
    for pkg in skipped:
        print(f"  skip: {pkg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
