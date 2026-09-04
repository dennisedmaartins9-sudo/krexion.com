"""v2.7.69 — Option B Krexion unique mobile browser shell."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_version_at_least_2_7_69():
    from packaging.version import Version

    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert Version(current) >= Version("2.7.69")


def test_mobile_shell_module():
    from krexion_mobile_browser_shell import (
        compute_mobile_shell_layout,
        should_use_mobile_shell,
    )
    import krexion_mobile_browser_shell as shell

    lay = compute_mobile_shell_layout("ios", 393, 852)
    assert lay.top_h == 28
    assert lay.bottom_h == 82
    assert lay.bezel == 0
    assert lay.outer_w == 393
    lay_a = compute_mobile_shell_layout("android", 393, 852)
    assert lay_a.top_h == 56
    assert lay_a.bottom_h == 52
    # Windows-only feature; force the platform gate for CI/Linux
    shell._IS_WINDOWS = True
    assert should_use_mobile_shell("ios", True) is True
    assert should_use_mobile_shell("android", True) is True
    assert should_use_mobile_shell("windows", True) is True
    assert should_use_mobile_shell("windows", False) is False


def test_launcher_wires_mobile_shell():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "apply_krexion_mobile_shell" in src
    assert "should_use_mobile_shell" in src
    assert "stop_mobile_shell" in src


def test_option_b_platform_native_ux():
    from krexion_mobile_browser_shell import (
        _bottom_html_android,
        _bottom_html_ios,
        _top_html_android,
        _top_html_ios,
    )

    ios_top = _top_html_ios("Test", 2)
    ios_bot = _bottom_html_ios("Test", 2)
    assert "Krexion" in ios_top
    assert "url-pill" in ios_bot
    assert "tool-row" in ios_bot
    assert "Safari" not in ios_bot

    and_top = _top_html_android("Pixel", 3)
    and_bot = _bottom_html_android("Pixel", 3)
    assert "omnibox" in and_top
    assert "chrome-bottom" in and_bot
    assert "Chrome" not in and_top


def test_shell_host_exists():
    assert (ROOT / "krexion_mobile_shell_host.py").is_file()
