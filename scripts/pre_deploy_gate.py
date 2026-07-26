"""
Pre-deploy validation gate for Krexion RUT + Smart Funnel.

Run BEFORE build/deploy so issues are caught locally instead of on production.

Usage:
  python scripts/pre_deploy_gate.py              # fast gate (~30s): static + unit tests
  python scripts/pre_deploy_gate.py --live       # + 4 live Smart Funnel conversions (~3-5 min)
  python scripts/pre_deploy_gate.py --full       # same as --live

Exit code 0 = safe to deploy. Non-zero = fix before deploy.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
KREXION_CORE = Path(r"C:\Program Files\Krexion\bin\krexion-core.exe")
OUT_DIR = ROOT / "scripts" / "batch_test_results"

REQUIRED_SYMBOLS = {
    "backend/smart_funnel.py": [
        "execute_smart_funnel",
        "SmartFunnelConfig",
        "CONVERSION_SCRIPT",
        "min_deals",
    ],
    "backend/anti_detect_v230.py": [
        "cdp_stealth_js",
        "build_v230_stealth_bundle",
        "fire_pixel_prefire",
        "detect_installed_chromium_major",
    ],
    "backend/tls_anti_detect.py": [
        "prewarm_companion_origins",
    ],
    "backend/real_user_traffic.py": [
        "smart_funnel_enabled",
        "_assess_ip_quality",
        "_auto_identity_label",
        "tls_prewarm: bool = True",
        "ad_chain_simulation_enabled: bool = True",
    ],
    "backend/referrer_pro.py": [
        "resolve_pro_visit",
    ],
}


def _banner(title: str) -> None:
    print(f"\n{'=' * 64}\n  {title}\n{'=' * 64}")


def phase_version() -> tuple[bool, str]:
    ver_path = BACKEND / "VERSION"
    if not ver_path.is_file():
        return False, "backend/VERSION missing"
    ver = ver_path.read_text(encoding="utf-8").strip()
    if not ver:
        return False, "backend/VERSION empty"
    return True, f"VERSION {ver}"


def phase_static_symbols() -> tuple[int, int]:
    ok = 0
    fail = 0
    for rel, needles in REQUIRED_SYMBOLS.items():
        path = ROOT / rel.replace("/", os.sep)
        if not path.is_file():
            print(f"  FAIL  missing file {rel}")
            fail += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [n for n in needles if n not in text]
        if missing:
            print(f"  FAIL  {rel}: missing {missing}")
            fail += 1
        else:
            print(f"  PASS  {rel} ({len(needles)} checks)")
            ok += 1
    return ok, fail


def phase_unit_tests() -> int:
    runner = ROOT / "scripts" / "_gate_unit_runner.py"
    if KREXION_CORE.is_file():
        cmd = [str(KREXION_CORE), str(runner)]
        label = "Krexion runtime"
    else:
        cmd = [sys.executable, str(runner)]
        label = sys.executable
    print(f"  runner: {label}")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=False)
    return proc.returncode


def phase_live_smart_funnel() -> int:
    script = ROOT / "scripts" / "run_4_smart_funnel_tests.py"
    if KREXION_CORE.is_file():
        cmd = [str(KREXION_CORE), str(script)]
    else:
        cmd = [sys.executable, str(script)]
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def phase_last_live_results() -> tuple[bool, str]:
    """Report most recent 4-visit batch if present."""
    if not OUT_DIR.is_dir():
        return True, "no prior live results (skipped)"
    files = sorted(OUT_DIR.glob("smart_funnel_4visits_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return True, "no prior 4-visit summary on disk"
    latest = files[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        return False, f"cannot read {latest.name}: {e}"
    if not isinstance(data, list):
        return False, f"{latest.name} invalid format"
    perfect = sum(1 for r in data if r.get("perfect_conversion"))
    total = len(data)
    ok = perfect == total and total >= 4
    msg = f"last batch {latest.name}: perfect {perfect}/{total}"
    return ok, msg


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-deploy gate for Krexion")
    parser.add_argument("--live", action="store_true", help="Run 4 live Smart Funnel conversion tests")
    parser.add_argument("--full", action="store_true", help="Alias for --live")
    parser.add_argument("--skip-live", action="store_true", help="Only static + unit (default)")
    args = parser.parse_args()
    run_live = (args.live or args.full) and not args.skip_live

    started = datetime.now()
    _banner("PRE-DEPLOY GATE - Krexion RUT / Smart Funnel")
    print(f"  started: {started.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  repo:    {ROOT}")

    failures = 0

    _banner("Phase 1 - Version")
    ok, msg = phase_version()
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        failures += 1

    _banner("Phase 2 - Static symbol checks")
    sym_ok, sym_fail = phase_static_symbols()
    failures += sym_fail
    print(f"  summary: {sym_ok} files ok, {sym_fail} failed")

    _banner("Phase 3 - Unit tests (v2.6.33-35 + Smart Funnel)")
    rc = phase_unit_tests()
    if rc != 0:
        failures += 1
        print(f"  FAIL  unit tests (exit {rc})")
    else:
        print("  PASS  all unit tests")

    if run_live:
        _banner("Phase 4 - Live Smart Funnel (4 visits, offer 250)")
        print("  This uses real proxies + browser. Expect ~3-5 minutes.")
        rc = phase_live_smart_funnel()
        if rc != 0:
            failures += 1
            print(f"  FAIL  live batch (exit {rc})")
        else:
            print("  PASS  4/4 perfect conversion")
        ok_prev = True
    else:
        _banner("Phase 4 - Live tests (skipped)")
        print("  Run with --live or --full before deploy for conversion proof.")
        ok_prev, prev_msg = phase_last_live_results()
        mark = "PASS" if ok_prev else "INFO"
        print(f"  {mark}  {prev_msg}")

    elapsed = (datetime.now() - started).total_seconds()
    _banner("GATE RESULT")
    if failures == 0:
        if run_live:
            print("  [OK] ALL CHECKS PASSED -- safe to build & deploy")
        else:
            print("  [OK] FAST CHECKS PASSED -- run with --live before deploy for full proof")
        print(f"  elapsed: {elapsed:.1f}s")
        return 0

    print(f"  [FAIL] GATE FAILED ({failures} phase(s)) -- do NOT deploy yet")
    print(f"  elapsed: {elapsed:.1f}s")
    if not run_live:
        print("  Tip: python scripts/pre_deploy_gate.py --live")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
