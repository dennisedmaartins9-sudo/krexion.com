"""v2.7.110 — WebKit mobile viewport zoom + shell frame polish."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webkit_context_uses_dsf_one_for_mobile():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "WebKit mobile context DSF=1.0" in src or "webkit_dsf_spoof" in src
    assert '1.0 if (_profile_engine == "webkit" and is_mobile' in src
    assert "set_viewport_size" in src
    assert "devicePixelRatio" in src


def test_shell_content_origin_no_double_scale():
    from krexion_mobile_browser_shell import (
        compute_mobile_shell_layout,
        _shell_content_origin,
    )

    lay = compute_mobile_shell_layout("ios", 390, 844).with_frame_scale(0.8)
    cx, cy = _shell_content_origin(lay, (100, 50))
    assert cx == 100
    # oy + top_h*fs  — NOT (oy + …) * fs
    assert cy == int(round(50 + 28 * 0.8))


def test_shell_reposition_no_dpi_multiply():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "same logical px space as engine HWND" in src
    assert "outer_w * dpi * fs" not in src.split("v2.7.110")[-1].split("def force_discover")[0]


def test_polish_webkit_fallback_exported_and_wired():
    from krexion_mobile_browser_shell import polish_webkit_phone_fallback

    assert callable(polish_webkit_phone_fallback)
    # Non-Windows CI: no-op False
    assert polish_webkit_phone_fallback() is False
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "polish_webkit_phone_fallback" in src
    assert "apply_ios_safari_shell_to_pids" not in src


def test_version_2_7_110():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.110")
