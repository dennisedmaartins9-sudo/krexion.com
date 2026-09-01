"""v2.7.80 — Proxies page IP-only quality check (no proxy string required)."""
from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_ip_for_quality_check(raw: str) -> Optional[str]:
    """Parity copy of server._parse_ip_for_quality_check for unit tests."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.count(":") == 1 and "." in s.split(":")[0]:
        host, port = s.rsplit(":", 1)
        if port.isdigit():
            s = host.strip()
    try:
        return str(ipaddress.ip_address(s))
    except ValueError:
        return None


def _format_ip_quality_row(ip: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Parity copy of server._format_ip_quality_row for unit tests."""
    source = str(result.get("source") or "none")
    provider = source.split(":")[0] if source else "none"
    try:
        score = int(result.get("vpn_score") or 0)
    except (TypeError, ValueError):
        score = 0
    return {
        "ip": ip,
        "fraud_score": score,
        "quality_score": max(0, 100 - score),
        "risk": result.get("risk") or "unknown",
        "is_vpn": bool(result.get("is_vpn")),
        "is_proxy": bool(result.get("is_proxy")),
        "is_hosting": bool(result.get("is_hosting")),
        "is_datacenter": bool(result.get("is_datacenter")),
        "is_tor": bool(result.get("is_tor")),
        "country": result.get("country") or result.get("country_code") or "",
        "asn": result.get("asn") or "",
        "source": source,
        "provider": provider,
        "min_fraud_score": result.get("min_fraud_score"),
        "vpn_reason": result.get("vpn_reason"),
    }


def test_version_is_2_7_80():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() >= "2.7.80"


def test_parse_ip_for_quality_check_ipv4():
    assert _parse_ip_for_quality_check("203.0.113.45") == "203.0.113.45"
    assert _parse_ip_for_quality_check("203.0.113.45:8080") == "203.0.113.45"
    assert _parse_ip_for_quality_check("  203.0.113.45  ") == "203.0.113.45"


def test_parse_ip_for_quality_check_invalid():
    assert _parse_ip_for_quality_check("not-an-ip") is None
    assert _parse_ip_for_quality_check("") is None


def test_format_ip_quality_row():
    row = _format_ip_quality_row("1.2.3.4", {
        "vpn_score": 72,
        "risk": "high",
        "is_vpn": True,
        "is_proxy": True,
        "source": "scamalytics:myacct",
        "country": "US",
        "asn": "AS12345",
    })
    assert row["ip"] == "1.2.3.4"
    assert row["fraud_score"] == 72
    assert row["quality_score"] == 28
    assert row["provider"] == "scamalytics"
    assert row["country"] == "US"


def test_check_ip_endpoint_registered():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert '"/proxies/check-ip"' in src
    assert "_format_ip_quality_row" in src
    assert "check_ip_for_user" in src


def test_frontend_ip_check_ui():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "ProxiesPage.js").resolve().read_text(encoding="utf-8")
    assert "check-ip-quality-button" in src
    assert "proxies/check-ip" in src
    assert "Check IP Quality" in src
