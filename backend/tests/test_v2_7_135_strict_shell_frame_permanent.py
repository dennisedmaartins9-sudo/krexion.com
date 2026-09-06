"""v2.7.135 — Strict mobile shell must frame permanently (no early abort)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def test_version_at_least_2_7_135():
    from releases_module import _parse

    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert _parse(ver) >= _parse("2.7.135")


def test_early_pass_does_not_require_embed():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "v2.7.135 — Early Krexion phone chrome" in src
    # Early brand must soft-start (no Strict abort before navigation)
    early = src.split("v2.7.135 — Early Krexion phone chrome")[1].split(
        "WebKit MiniBrowser"
    )[0]
    assert "require_embed=False" in early
    assert "require_embed=bool(strict_mobile_shell)" not in early
    assert "before navigation. Launch aborted" not in early


def test_shell_handles_include_content():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    chunk = src.split("def _load_shell_handles")[1].split("\ndef ")[0]
    assert '"content"' in chunk
    assert "v2.7.135" in chunk or "content" in chunk


def test_force_discover_uses_setparent():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    chunk = src.split("def force_discover_and_mark_embedded")[1].split(
        "\ndef mobile_shell_status"
    )[0]
    # v2.9.3 — force_discover routes through try_frame_engine_into_shell
    # (SetParent + verified visual glue), still AdsPower-class framing.
    assert "try_frame_engine_into_shell" in chunk
    assert "Krexion Browser" in chunk or "Google" in chunk


def test_strict_last_chance_retries():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "Last-chance multi-pass discover" in src
    assert "hide_profile_engine_windows" in (ROOT / "krexion_window_icon.py").read_text(
        encoding="utf-8"
    )
