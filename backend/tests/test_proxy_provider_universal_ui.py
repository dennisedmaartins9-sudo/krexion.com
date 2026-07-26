"""Proxy provider universal generator UI tests."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_targeting_profile_returns_full_supports():
    text = (ROOT / "backend" / "proxy_provider_module.py").read_text(encoding="utf-8")
    idx = text.find("async def provider_targeting_profile")
    assert idx > 0
    block = text[idx : idx + 2200]
    assert '"country": True' in block
    assert '"session_mode": True' in block


def test_detect_profile_name_fallback():
    text = (ROOT / "backend" / "proxy_provider_module.py").read_text(encoding="utf-8")
    assert "provider_name: str = \"\"" in text
    assert '"dataimpulse"' in text


def test_frontend_always_shows_full_generator():
    text = (ROOT / "frontend" / "src" / "components" / "MyProxyProvidersCard.js").read_text(encoding="utf-8")
    assert "FULL_GENERATOR_SUPPORTS" in text
    assert "supports.country &&" not in text
    assert "anyGeo" not in text
