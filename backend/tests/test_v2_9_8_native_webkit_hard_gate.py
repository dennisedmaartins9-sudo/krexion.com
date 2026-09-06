"""v2.9.8 — Native WebKit packaging hard-gate (AdsPower parity)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_9_9():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.9")


def test_native_workflow_hard_gates_webkit():
    yml = (REPO / ".github" / "workflows" / "build-windows-release.yml").read_text(
        encoding="utf-8"
    )
    assert "webkit-* folder missing from bundle" in yml
    assert "throw" in yml
    # Soft Android-fallback copy must be gone
    assert "fall back to Android Chrome" not in yml
    assert 'Write-Warning "webkit-*' not in yml
    # Playwright install failure must throw, not warn-and-continue
    assert "Playwright install failed" in yml
    assert "continuing build (chromium-bundle may be partial)" not in yml
    # v2.9.9 — throw strings must be ASCII (em-dash breaks PS parser)
    block = yml.split("Ship all three: full chromium")[1].split("Install NSSM")[0]
    assert "\u2014" not in block  # em dash
    assert " - chromium/webkit bundle incomplete" in block or "- chromium/webkit" in block
