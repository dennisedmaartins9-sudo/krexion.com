"""DataImpulse username must be login__cr.us;state.california;sessid.X
(v2.6.96 — key is 'state' with full slug, not 'st' with 2-letter code)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "playwright.async_api" not in sys.modules:
    sys.modules["playwright"] = MagicMock()
    sys.modules["playwright.async_api"] = MagicMock(
        async_playwright=MagicMock(),
        Page=object,
        BrowserContext=object,
        Browser=object,
    )

from proxy_provider_module import (  # noqa: E402
    _apply_targeting_to_username,
    _gateway_base_username,
    _rotate_session_in_username,
)
from real_user_traffic import (  # noqa: E402
    _build_state_targeted_proxy,
    _parse_proxy_line,
)

_LOGIN = "8a3acf2fe62ceb8690a2"
_HOST = "gw.dataimpulse.com"


def _assert_dataimpulse_ca_order(user: str) -> None:
    assert user.startswith(f"{_LOGIN}__cr.us;state.california"), user
    assert user.find("__cr.us") < user.find(";state.california") < user.find(";sessid."), user
    assert not user.startswith(f"{_LOGIN};sessid."), user
    assert "__cr.us;state.california" in user
    assert ";sessid." not in user.split("__cr.us", 1)[0]


def test_gateway_base_strips_generated_dataimpulse_line():
    stale = f"{_LOGIN}__cr.us;state.california;sessid.old12345"
    base = _gateway_base_username(stale, _HOST)
    assert base == _LOGIN, base


def test_gateway_base_strips_legacy_st_dot_format():
    """Old st.ca format must also be stripped cleanly."""
    stale = f"{_LOGIN}__cr.us;st.ca;sessid.old12345"
    base = _gateway_base_username(stale, _HOST)
    assert base == _LOGIN, base


def test_gateway_base_strips_mangled_live_username():
    mangled = f"{_LOGIN};sessid.55511122__cr.us;state.california"
    base = _gateway_base_username(mangled, _HOST)
    assert base == _LOGIN, base
    assert "sessid" not in base.lower()


def test_targeting_rebuilds_correct_dataimpulse_order():
    user = _apply_targeting_to_username(
        _LOGIN,
        _HOST,
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    user = _rotate_session_in_username(user)
    _assert_dataimpulse_ca_order(user)


def test_force_replace_heals_stale_generated_line():
    stale = f"{_LOGIN}__cr.us;state.california;sessid.old12345"
    user = _apply_targeting_to_username(
        stale,
        _HOST,
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    user = _rotate_session_in_username(user)
    _assert_dataimpulse_ca_order(user)
    assert "old12345" not in user


def test_force_replace_heals_mangled_live_username():
    mangled = f"{_LOGIN};sessid.55511122__cr.us;state.california"
    user = _apply_targeting_to_username(
        mangled,
        _HOST,
        {"country": "US", "state": "CA", "_want_sid": True, "force_replace": True},
    )
    user = _rotate_session_in_username(user)
    _assert_dataimpulse_ca_order(user)
    assert "55511122" not in user


def test_row_first_rebuild_from_generated_dataimpulse_line():
    stale = f"{_LOGIN}__cr.us;state.california;sessid.old12345"
    parsed = _parse_proxy_line(f"http://{stale}:secret@{_HOST}:10000")
    assert parsed and parsed.get("is_rotating_gateway")
    out = _build_state_targeted_proxy(parsed, "CA", "US")
    _assert_dataimpulse_ca_order(out["username"])
    assert "old12345" not in out["username"]
    assert "sessttl." in out["username"]


def test_row_first_rebuild_from_mangled_live_username():
    mangled = f"{_LOGIN};sessid.55511122__cr.us;state.california"
    parsed = _parse_proxy_line(f"http://{mangled}:secret@{_HOST}:10000")
    out = _build_state_targeted_proxy(parsed, "CA", "US")
    _assert_dataimpulse_ca_order(out["username"])
    assert "55511122" not in out["username"]


def test_rotate_dataimpulse_dot_sessid():
    before = f"{_LOGIN}__cr.us;state.california;sessid.11111111"
    after = _rotate_session_in_username(before)
    assert after.startswith(f"{_LOGIN}__cr.us;state.california;sessid.")
    assert "11111111" not in after
    assert after != before


def test_north_carolina_uses_full_slug():
    """NC → state.north_carolina (not st.nc) so DataImpulse actually targets."""
    user = _apply_targeting_to_username(
        _LOGIN,
        _HOST,
        {"country": "US", "state": "NC", "_want_sid": True, "force_replace": True},
    )
    assert ";state.north_carolina" in user, user
    assert ";st.nc" not in user, user
    assert ";st." not in user.split("state.")[0], user


def test_new_york_slug_format():
    user = _apply_targeting_to_username(
        _LOGIN,
        _HOST,
        {"country": "US", "state": "NY", "_want_sid": True, "force_replace": True},
    )
    assert ";state.new_york" in user, user
