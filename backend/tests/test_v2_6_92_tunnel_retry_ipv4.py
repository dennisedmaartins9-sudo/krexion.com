"""v2.6.92 — tunnel retry after failed tracker goto; prefer IPv4."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_affiliate_click_not_set_before_goto():
    src = _src()
    idx = src.index("resp = await page.goto(_visit_target_url, timeout=35000")
    assert "_affiliate_click_fired = True" not in src[idx - 500 : idx]
    assert "_affiliate_click_fired = True" in src[idx : idx + 900]


def test_ipv6_exit_skipped_for_ipv4_retry():
    src = _src()
    assert 'IPv6 exit' in src
    assert "retrying for IPv4" in src


def test_decodo_geo_probe_uses_short_timeout():
    src = _src()
    assert "httpx.Timeout(8.0, connect=5.0)" in src
    assert "Keep the whole probe under the 28s wait_for" in src


def test_version_is_2_6_92():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert version == "2.6.92"
