"""Regression tests for proxy/link/click bug fixes (Jul 2026)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_stored_proxy_status_includes_alive():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "STORED_PROXY_ACTIVE_STATUSES" in text
    assert '"alive"' in text
    assert 'status": {"$in": STORED_PROXY_ACTIVE_STATUSES' in text


def test_form_filler_uses_proxy_string():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    idx = text.find("if use_proxies:")
    assert idx > 0
    block = text[idx : idx + 600]
    assert "proxy_string" in block
    assert "proxy_ip" not in block


def test_rut_defer_click_helpers():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "def _kx_rut_defer_sign()" in text
    assert "def _kx_rut_defer_verify" in text
    assert "def build_kx_rut_defer_qs()" in text
    assert "def _should_defer_click_log_to_rut" in text
    assert "_kx_rut_defer=1" in text
    assert "if not _defer_click_to_rut:" in text


def test_link_cache_invalidation_helper():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "def invalidate_link_cache" in text
    assert "_link_cache.pop" in text
    assert "invalidate_link_cache(" in text


def test_append_rut_defer_qs():
    text = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "def _append_rut_defer_click_qs" in text
    assert "_kx_rut_defer" in text
    assert "_append_rut_defer_click_qs(target_url)" in text


def test_silent_skip_includes_tracker_block():
    text = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "skipped_tracker_block" in text
    assert "_SILENT_SKIP_STATUSES" in text
    idx = text.find("_SILENT_SKIP_STATUSES")
    block = text[idx : idx + 220]
    assert "skipped_tracker_block" in block


def test_proxy_provider_id_in_submit_params():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert '"proxy_provider_id"' in text


def test_export_clicks_dedupes_by_id():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "_seen_export_ids" in text
    idx = text.find("async def export_clicks")
    assert idx > 0
    block = text[idx : idx + 5000]
    assert '"id": 1, "click_id": 1' in block


def test_with_params_referrer_mode_adds_platform_params():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert 'referrer_mode == "with_params"' in text
    assert "generate_platform_params" in text


def test_failed_visit_rolls_back_link_clicks():
    text = (ROOT / "backend" / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "Roll back link counter when visit failed after early log" in text
    assert '"clicks": -1' in text
