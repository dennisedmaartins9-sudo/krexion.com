"""v2.7.105c — Atomic lead claim, after/consume modes, strict defaults, shell honesty."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_normalize_modes():
    from browser_profile_automation import _normalize_after_mode, _normalize_consume_mode

    assert _normalize_after_mode("CLOSE") == "close"
    assert _normalize_after_mode("next_row") == "next_lead"
    assert _normalize_after_mode("") == "manual"
    assert _normalize_consume_mode("on_start") == "on_start"
    assert _normalize_consume_mode("claim") == "on_start"
    assert _normalize_consume_mode("") == "on_submit"


def test_placeholders_and_fingerprint():
    from browser_profile_automation import (
        extract_placeholders_from_steps,
        _row_fingerprint,
        _row_email,
    )

    steps = [
        {"action": "fill", "value": "{{email}}"},
        {"action": "type", "text": "Hello {first_name}"},
    ]
    ph = extract_placeholders_from_steps(steps)
    assert "email" in ph
    assert "first_name" in ph
    row = {"email": "a@b.com", "first_name": "Ada"}
    assert _row_email(row) == "a@b.com"
    assert len(_row_fingerprint(row)) == 24


def test_strict_proxy_defaults_on_when_proxy_enabled():
    from browser_profile_module import _strict_proxy_mode

    assert _strict_proxy_mode({
        "anti_detect": {},
        "proxy": {"enabled": True, "server": "http://gw:1"},
    }) is True
    assert _strict_proxy_mode({
        "anti_detect": {"proxy_check_block_on_fail": False},
        "proxy": {"enabled": True},
    }) is False
    assert _strict_proxy_mode({"anti_detect": {}}) is False


def test_public_view_proxy_age_and_strict():
    from browser_profile_module import _public_view

    checked = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    view = _public_view({
        "id": "p1",
        "user_id": "u1",
        "name": "T",
        "proxy": {"enabled": True, "server": "http://h:1", "password": "secret"},
        "anti_detect": {},
        "last_proxy_check": {"ok": True, "ip": "1.2.3.4", "checked_at": checked},
        "is_mobile": True,
    })
    assert view["proxy"]["password"] == ""
    assert view["strict_proxy"] is True
    assert view["proxy_check_stale"] is True
    assert view["proxy_check_age_hours"] is not None
    assert view["proxy_check_age_hours"] >= 24


def test_prune_reservations_drops_expired():
    from browser_profile_automation import _prune_reservations

    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    kept = _prune_reservations({
        "reserved_rows": [
            {"lead_row_index": 0, "expires_at": past, "fingerprint": "a"},
            {"lead_row_index": 1, "expires_at": future, "fingerprint": "b"},
        ]
    })
    assert len(kept) == 1
    assert kept[0]["lead_row_index"] == 1


def test_claim_next_skips_reserved_rows():
    from browser_profile_automation import claim_next_data_file_row

    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    rows = [
        {"email": "a@x.com", "name": "A"},
        {"email": "b@x.com", "name": "B"},
    ]
    doc = {
        "id": "df1",
        "user_id": "u1",
        "type": "data_file",
        "reserved_rows": [
            {"lead_row_index": 0, "fingerprint": "x", "expires_at": future},
        ],
    }

    db = MagicMock()
    db.uploaded_resources.find_one_and_update = AsyncMock(return_value=doc)
    db.uploaded_resources.find_one = AsyncMock(return_value=doc)
    db.uploaded_resources.update_one = AsyncMock()

    async def _run():
        with patch(
            "browser_profile_automation.load_data_file_rows",
            AsyncMock(return_value=rows),
        ):
            lead, idx, meta = await claim_next_data_file_row(
                db, "u1", "df1", consume_now=False,
            )
            assert idx == 1
            assert lead["email"] == "b@x.com"
            assert meta.get("reserved") is True

    asyncio.run(_run())


def test_launcher_wires_after_mode_and_strict_mobile():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "after == \"close\"" in src or "after == 'close'" in src
    assert "next_lead" in src
    assert "strict_mobile_shell" in src
    assert "request_stop(session_id)" in src
    assert "not a real iPhone/Android" in src


def test_module_validate_route_and_models():
    src = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert '"/validate-automation"' in src or "'/validate-automation'" in src
    assert "consume_mode" in src
    assert "strict_mobile_shell" in src
    assert "claim_next" in src

    from browser_profile_module import ProfileAutomationLaunch, BulkRunJsonBody

    a = ProfileAutomationLaunch(enabled=True, after_mode="close", consume_mode="on_start")
    assert a.after_mode == "close"
    assert a.consume_mode == "on_start"
    b = BulkRunJsonBody(profile_ids=["x"], automation_upload_id="y", claim_next=True)
    assert b.claim_next is True


def test_frontend_has_after_consume_validate_ui():
    fe = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "src"
        / "pages"
        / "BrowserProfilesPage.js"
    )
    src = fe.read_text(encoding="utf-8")
    assert "after_mode" in src
    assert "consume_mode" in src
    assert "validate-automation" in src
    assert "strict_mobile_shell" in src
    assert "bp-launch-mobile-honesty" in src
    assert "claim_next" in src
    assert "Recheck proxy" in src


def test_anti_detect_config_has_strict_mobile():
    from browser_profile_module import AntiDetectConfig

    cfg = AntiDetectConfig()
    assert cfg.proxy_check_block_on_fail is True
    # v2.7.105d — default ON so mobile launches abort instead of plain Chromium
    assert cfg.strict_mobile_shell is True
