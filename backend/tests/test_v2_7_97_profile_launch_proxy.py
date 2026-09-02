"""v2.7.97 — Profile launch proxy probe resilience + soft launch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_is_valid_exit_ip_ipv4_and_ipv6():
    from browser_profile_module import _is_valid_exit_ip

    assert _is_valid_exit_ip("203.0.113.10")
    assert _is_valid_exit_ip("2001:db8::1")
    assert not _is_valid_exit_ip("")
    assert not _is_valid_exit_ip("not-an-ip")


def test_format_profile_proxy_probe_failure_includes_probe_error():
    from browser_profile_module import _format_profile_proxy_probe_failure

    msg = _format_profile_proxy_probe_failure(
        {"name": "Test-Profile"},
        {"provider_id": "pp-1", "password": "secret", "server": "http://gw.example:823"},
        {"error": "ConnectTimeout: timed out"},
    )
    assert "Test-Profile" in msg
    assert "ConnectTimeout" in msg


def test_format_profile_proxy_probe_failure_password_hint():
    from browser_profile_module import _format_profile_proxy_probe_failure

    msg = _format_profile_proxy_probe_failure(
        {"name": "P1"},
        {"provider_id": "pp-1", "server": "http://gw.example:823"},
        {},
    )
    assert "password missing" in msg.lower()


def test_proxy_ready_for_soft_launch():
    from browser_profile_module import _proxy_ready_for_soft_launch

    assert _proxy_ready_for_soft_launch({"server": "http://gw:823", "password": "x"})
    assert not _proxy_ready_for_soft_launch({"server": "http://gw:823"})
    assert not _proxy_ready_for_soft_launch({"password": "x"})


def test_ensure_launch_proxy_soft_launch_path():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    start = src.index("async def _ensure_profile_launch_proxy")
    end = src.index("async def _resolve_user", start)
    block = src[start:end]
    assert "_proxy_ready_for_soft_launch" in block
    assert "_launch_proxy_probe_warning" in block
    assert "_format_profile_proxy_probe_failure" in block
    assert "rotating provider session" in block


def test_launcher_reads_proxy_probe_warning():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "_launch_proxy_probe_warning" in src


def test_proxy_url_for_http_embedded_creds_no_name_error():
    from real_user_traffic import _proxy_url_for_http

    url = _proxy_url_for_http({
        "server": "http://user:pass@gw.example.com:823",
    })
    assert "gw.example.com" in url
    assert "user" in url


def test_version_is_2_7_97():
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = [int(x) for x in ver.split(".")]
    assert parts >= [2, 7, 97]
