"""v2.7.100 — Manual proxy auth hydrate + mobile shell sizing fixes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_resolve_launch_proxy_cfg_exists():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "async def resolve_launch_proxy_cfg" in src
    assert "_canonical_proxy_raw_line" in src
    assert "gateway password lookup" in src


def test_prepare_proxy_persists_raw_line():
    from browser_profile_module import _prepare_proxy_for_profile_create

    doc = {
        "proxy": {
            "enabled": True,
            "server": "http://gw.dataimpulse.com:10003",
            "username": "user__cr.us",
            "password": "secret123",
        }
    }
    _prepare_proxy_for_profile_create(doc)
    assert "raw_line" in doc["proxy"]
    assert "secret123" in doc["proxy"]["raw_line"]


def test_launcher_uses_resolve_launch_proxy_cfg():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "resolve_launch_proxy_cfg" in src
    assert "password is missing" in src


def test_legacy_ios_safari_shell_removed():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "apply_ios_safari_shell_to_pids" not in src


def test_mobile_shell_engine_size_without_dpi_square():
    src = (ROOT / "krexion_mobile_browser_shell.py").read_text(encoding="utf-8")
    assert "def _shell_content_origin" in src
    assert "match CSS viewport, not DPI" in src
    assert "_hide_stray_cb" in src


def test_version_is_2_7_100_or_later():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 100]
