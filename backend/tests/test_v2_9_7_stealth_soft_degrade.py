"""v2.9.7 — Fingerprint soft-degrade honesty + Inno WebKit gate."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_9_7():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.7")


def test_launcher_surfaces_soft_stealth_degrade():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_stealth_ok = await _rut_apply_context_stealth(" in src
    assert "_soft_degraded" in src
    assert "Stealth degraded — RUT anti-detect inject partially failed" in src
    assert "RUT stealth SOFT-DEGRADED" in src
    assert "RUT-parity stealth ON" in src


def test_health_scores_stealth_degraded_warning():
    src = (ROOT / "browser_profile_health.py").read_text(encoding="utf-8")
    assert "Stealth degraded" in src
    assert "stealth degraded on last Open" in src


def test_inno_requires_browser_engine_bundle():
    iss = (REPO / "installer" / "krexion-setup.iss").read_text(encoding="utf-8")
    line = [
        ln
        for ln in iss.splitlines()
        if "chromium-bundle" in ln and "Source:" in ln
    ][0]
    assert "skipifsourcedoesntexist" not in line
