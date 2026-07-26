"""Run pytest-style unit tests without pytest (Krexion runtime has no pytest)."""
from __future__ import annotations

import importlib.util
import os
import sys
import traceback
import types
from pathlib import Path

# Krexion runtime has no pytest; tests only `import pytest` at module level.
if "pytest" not in sys.modules:
    sys.modules["pytest"] = types.ModuleType("pytest")

KREXION_APP = Path(r"C:\Program Files\Krexion\bin\app")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\Program Files\Krexion\browser-engine")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(KREXION_APP))
sys.path.insert(0, str(BACKEND))

TEST_FILES = [
    BACKEND / "tests" / "test_smart_funnel.py",
    BACKEND / "tests" / "test_v2_6_33_tiktok_android_inapp_completeness.py",
    BACKEND / "tests" / "test_v2_6_34_rut_referrer_completeness.py",
    BACKEND / "tests" / "test_v2_6_35_anti_detect_completeness.py",
]


def _load_module(path: Path):
    name = path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    passed = 0
    failed = 0
    errors: list[str] = []

    for path in TEST_FILES:
        if not path.is_file():
            errors.append(f"MISSING {path.name}")
            failed += 1
            continue
        try:
            mod = _load_module(path)
        except Exception as e:
            errors.append(f"LOAD {path.name}: {e}")
            failed += 1
            continue

        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            label = f"{path.stem}::{name}"
            try:
                fn()
                passed += 1
                print(f"  PASS  {label}")
            except Exception as e:
                failed += 1
                errors.append(f"{label}: {e}")
                print(f"  FAIL  {label}: {e}")
                traceback.print_exc()

    print(f"\nUNIT SUMMARY: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for err in errors:
            print(f"  - {err}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
