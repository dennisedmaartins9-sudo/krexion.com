"""v2.9.3 — Strict mobile shell must retry frame; visual glue accepted when SetParent fails."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_at_least_2_9_3():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.9.3")


def test_setparent_retries_and_never_lies():
    src = (ROOT / "krexion_branded_browser.py").read_text(encoding="utf-8")
    assert "v2.9.3" in src
    assert "WS_CLIPSIBLINGS" in src
    assert "range(6)" in src
    assert "GetParent" in src
    assert "last_parent == shell" in src
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if "return True" in s and "or True" in s:
            raise AssertionError(f"SetParent lie: {s}")


def test_shell_retries_frame_every_tick_and_accepts_visual_glue():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "try_frame_engine_into_shell" in src
    assert "engine_visually_framed_in_shell" in src
    assert "Keep retrying frame every tick" in src
    force = src.split("def force_discover_and_mark_embedded")[1].split("def mobile_shell_status")[0]
    assert "try_frame_engine_into_shell" in force
    assert "Google" in force


def test_launcher_gives_cloak_more_frame_time():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "else 45.0" in src
    assert "range(10)" in src
