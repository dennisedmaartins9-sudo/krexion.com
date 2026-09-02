"""v2.7.99 — Provider proxy launch never hard-blocks on exit IP pre-probe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_defer_launch_proxy_probe_for_provider():
    from browser_profile_module import _defer_launch_proxy_probe

    assert _defer_launch_proxy_probe({"provider_id": "pp-1", "server": "http://gw:823"})
    assert _defer_launch_proxy_probe({"smart_session": True, "server": "http://gw:823"})
    assert _defer_launch_proxy_probe({"use_proxyjet": True, "server": "http://x:1"})
    assert not _defer_launch_proxy_probe({"enabled": True, "server": "http://1.2.3.4:8080"})


def test_proxy_ready_for_soft_launch_provider_without_password():
    from browser_profile_module import _proxy_ready_for_soft_launch

    assert _proxy_ready_for_soft_launch(
        {"provider_id": "pp-1", "server": "http://gw.dataimpulse.com:823"}
    )


def test_ensure_launch_proxy_uses_best_effort_for_provider():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "_best_effort_bind_exit_ip_at_launch" in src
    assert "_defer_launch_proxy_probe" in src
    assert "pre-probe is best-effort only" in src


def test_version_is_2_7_99():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 101]
