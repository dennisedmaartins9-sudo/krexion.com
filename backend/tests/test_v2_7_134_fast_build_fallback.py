"""v2.7.134 — FAST BUILD falls back to full rebuild on corrupt cache."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_134():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.134")


def test_build_backend_has_fast_build_fallback():
    src = (REPO / "build/build-backend.py").read_text(encoding="utf-8")
    assert "FAST BUILD failed" in src
    assert "_full_rebuild" in src
    assert "doing full rebuild" in src


def test_ci_cache_key_bumped():
    wf = (REPO / ".github/workflows/build-windows-release.yml").read_text(
        encoding="utf-8"
    )
    assert "deps-v2-" in wf
    assert "deps-v1-" not in wf
