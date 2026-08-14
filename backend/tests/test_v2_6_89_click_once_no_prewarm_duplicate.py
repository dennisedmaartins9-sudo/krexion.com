"""v2.6.89 — Clicks≈Hosts: skip TLS prewarm when affiliate click already committed."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_tls_prewarm_skipped_for_tracker_and_ptro():
    src = _src()
    idx = src.index("v2.6.89/90 — REGRESSION FIX")
    chunk = src[idx : idx + 2200]
    assert "_tls_prewarm_effective = bool(tls_prewarm)" in chunk
    assert "_is_tracker_target" in chunk
    assert "_ptro_swapped" in chunk
    assert "_affiliate_click_fired" in chunk
    assert "sole affiliate click" in chunk
    assert "Clicks>>Hosts inflation" in chunk


def test_no_offer_prewarm_resolve_after_v289():
    """v2.6.34 offer-only prewarm was removed — it duplicated Everflow clicks."""
    src = _src()
    assert "_resolved_offer_prewarm = await _resolve_tracker_via_localhost(" not in src
    assert "TLS prewarm → offer only (not tracker)" not in src


def test_version_at_least_2_6_89():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    parts = [int(x) for x in version.split(".")]
    assert parts >= [2, 6, 89]
