"""Unit tests for ROW-FIRST state-match (rotating gateway + Smartproxy)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from real_user_traffic import (  # noqa: E402
    _build_state_targeted_proxy,
    _detect_rotating_gateway,
    _host_from_proxy_server,
    _normalize_state,
    _parse_proxy_line,
)


class TestHostFromProxyServer:
    def test_extracts_host(self):
        assert _host_from_proxy_server("http://user:pass@gate.smartproxy.com:7000") == "gate.smartproxy.com"


class TestBuildStateTargetedProxy:
    def test_smartproxy_state_injected(self):
        base = _parse_proxy_line("http://user-sp123:secret@us.smartproxy.net:3128")
        assert base and base.get("is_rotating_gateway")
        out = _build_state_targeted_proxy(base, "NE", "US")
        assert out["username"]
        un = out["username"].lower()
        assert "state" in un
        assert "us_nebraska" in un or "nebraska" in un
        assert out["server"].startswith("http://")
        assert out["username"] != base.get("username")

    def test_smartproxy_california_format(self):
        from proxy_provider_module import _apply_targeting_to_username

        user = _apply_targeting_to_username(
            "user-sp123",
            "gate.smartproxy.com",
            {"country": "US", "state": "CA", "_want_sid": True},
        )
        assert "us_california" in user.lower()

    def test_session_rotates_between_calls(self):
        base = _parse_proxy_line("http://user-session-abc:pass@gate.smartproxy.com:7000")
        a = _build_state_targeted_proxy(base, "CA", "US")
        b = _build_state_targeted_proxy(base, "CA", "US")
        assert a["username"] != b["username"]

    def test_empty_state_returns_copy(self):
        base = _parse_proxy_line("http://u:p@1.2.3.4:8080")
        out = _build_state_targeted_proxy(base, "", "US")
        assert out.get("server") == base.get("server")


class TestRotatingGatewayDetection:
    def test_smartproxy_net(self):
        assert _detect_rotating_gateway("us.smartproxy.net", "user")

    def test_static_ip_not_gateway(self):
        assert not _detect_rotating_gateway("203.0.113.10", "admin")


class TestRowFirstFlagsInSource:
    def test_row_first_state_match_flag_present(self):
        src = Path(__file__).resolve().parents[1] / "real_user_traffic.py"
        text = src.read_text(encoding="utf-8")
        assert "_row_first_state_match" in text
        assert "_use_row_first" in text
        assert "_build_state_targeted_proxy" in text

    def test_normalize_state_nebraska(self):
        assert _normalize_state("Nebraska") == "NE"
        assert _normalize_state("NE") == "NE"
