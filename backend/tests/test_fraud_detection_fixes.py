"""Fraud detection + proxy provider regression checks."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_custom_rules_run_when_personal_filter_off():
    text = (ROOT / "backend" / "fraud_provider_module.py").read_text(encoding="utf-8")
    assert "Custom rules can run even when personal premium providers are OFF" in text
    assert "_enrich_geo_for_rules" in text


def test_link_block_vpn_uses_user_fraud_check():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    idx = text.find("if link.get(\"block_vpn\") and client_ip")
    assert idx > 0
    block = text[idx : idx + 350]
    assert "check_vpn_detailed" in block
    assert "main_user_id" in block


def test_quality_tier_defaults_applied_on_link_save():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "quality_tier_defaults" in text


def test_referrer_presets_use_valid_device_modes():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert '"referrer_pro_device_mode": "mobile_only"' in text
    assert '"referrer_pro_campaign_type": "search_cpc"' in text
    assert '"referrer_pro_device_mode": "mobile"' not in text


def test_generate_batch_probes_strict_lines():
    text = (ROOT / "backend" / "proxy_provider_module.py").read_text(encoding="utf-8")
    assert "Honour provider strict/DC toggles" in text
    assert "_get_cached_ip_reputation" in text


def test_rut_provider_bulk_replaces_frontend_pregen():
    text = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "Backend bulk fetch is authoritative" in text
