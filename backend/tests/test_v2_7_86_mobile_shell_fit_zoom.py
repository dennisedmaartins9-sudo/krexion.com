"""v2.7.86 — mobile shell fit-to-screen default + zoom menu."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_at_least_2_7_86():
    from packaging.version import Version

    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert Version(current) >= Version("2.7.86")


def test_fit_frame_scale_clamped():
    from krexion_mobile_browser_shell import compute_fit_frame_scale, compute_mobile_shell_layout

    lay = compute_mobile_shell_layout("android", 393, 852)
    scale = compute_fit_frame_scale(lay)
    assert 0.55 <= scale <= 1.0


def test_layout_with_frame_scale():
    from krexion_mobile_browser_shell import compute_mobile_shell_layout

    lay = compute_mobile_shell_layout("ios", 393, 852).with_frame_scale(0.8)
    assert lay.frame_scale == 0.8
    assert lay.display_outer_w == int(round(393 * 0.8))


def test_adjust_shell_frame_scale_updates_active():
    from krexion_mobile_browser_shell import (
        MobileShellLayout,
        _ACTIVE,
        adjust_shell_frame_scale,
        compute_mobile_shell_layout,
    )

    lay = compute_mobile_shell_layout("android", 393, 852).with_frame_scale(0.9)
    _ACTIVE["sess-zoom"] = {"layout": lay, "origin_x": 10, "origin_y": 20}
    nxt = adjust_shell_frame_scale("sess-zoom", "in")
    assert nxt > 0.9
    assert _ACTIVE["sess-zoom"]["layout"].frame_scale == nxt
    _ACTIVE.pop("sess-zoom", None)


def test_interactive_menu_wires_zoom_commands():
    src = (ROOT / "krexion_mobile_shell_interactive.py").read_text(encoding="utf-8")
    assert "openMenuSheet" in src
    assert "def fit_screen" in src
    assert "def zoom_in" in src
    assert "KREXION MENU" in src


def test_launcher_handles_shell_zoom_commands():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "adjust_shell_frame_scale" in src
    assert '"fit_screen"' in src or "'fit_screen'" in src


def test_apply_shell_uses_fit_by_default():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "compute_fit_frame_scale" in src
    assert "with_frame_scale(compute_fit_frame_scale(layout))" in src
