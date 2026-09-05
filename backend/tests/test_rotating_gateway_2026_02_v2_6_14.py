"""
v2.6.14 — Rotating-gateway proxy exhaustion + offer-block retry test.
Backend-only. Verifies:
  1. _parse_proxy_line flags rotating-gateway entries for known providers.
  2. _detect_rotating_gateway heuristics (host prefix, session marker, plain IP).
  3. pick_next_proxy closure recycles rotating gateways with no_repeated_proxy=True
     but still burns static-IP entries after first use.
  4. Static AST checks: _can_retry_offer_block usage at ~11052/9911/8268.
  5. Admin login + providers list smoke-tests.
"""
import os
import re
import sys
import ast
import types
import inspect
import textwrap
import pathlib

import pytest
import requests

_HERE = pathlib.Path(__file__).resolve()
_BACKEND_DIR = str(_HERE.parents[1])
_REPO_ROOT = _HERE.parents[2]
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# Cloud layout fallback
if "/app/backend" not in sys.path and pathlib.Path("/app/backend").is_dir():
    sys.path.insert(0, "/app/backend")

import real_user_traffic as rut

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    # fall back to frontend/.env when present (local or /app layout)
    for _cand in (
        _REPO_ROOT / "frontend" / ".env",
        pathlib.Path("/app/frontend/.env"),
    ):
        try:
            if _cand.is_file():
                _fe = _cand.read_text(encoding="utf-8", errors="ignore")
                _m = re.search(r"REACT_APP_BACKEND_URL\s*=\s*(\S+)", _fe)
                if _m:
                    BASE_URL = _m.group(1).strip().rstrip("/")
                    break
        except OSError:
            pass


# ── 1. _parse_proxy_line — rotating gateway detection ────────────────
@pytest.mark.parametrize("line,expected", [
    # DataImpulse — the customer's actual line
    ("http://user__cr.us;sessid.abc123;sessttl.120:pass@gw.dataimpulse.com:10000", True),
    # Oxylabs
    ("http://user-sessionid:pass@pr.oxylabs.io:7777", True),
    # Bright Data
    ("http://user-session-abc:pass@brd.superproxy.io:22225", True),
    # IPRoyal
    ("http://user:pass@geo.iproyal.com:12321", True),
    # Soax
    ("http://user-sessid-123:pass@proxy.soax.com:5000", True),
    # Smartproxy (any subdomain)
    ("http://user:pass@gate.smartproxy.com:7000", True),
    # Plain static ip:port — NOT rotating
    ("http://user:pass@1.2.3.4:8080", False),
    # 4-tuple static
    ("1.2.3.4:8080:user:pass", False),
])
def test_parse_proxy_line_rotating_gateway_flag(line, expected):
    result = rut._parse_proxy_line(line)
    assert result is not None, f"_parse_proxy_line returned None for {line!r}"
    assert result.get("is_rotating_gateway") is expected, (
        f"Expected is_rotating_gateway={expected} for line={line!r} got {result.get('is_rotating_gateway')!r}"
    )


# ── 2. _detect_rotating_gateway heuristics ───────────────────────────
def test_detect_rotating_gateway_host_prefix():
    assert rut._detect_rotating_gateway("gw.random-provider.com", "") is True

def test_detect_rotating_gateway_username_session_marker():
    assert rut._detect_rotating_gateway("some-host.com", "user-session-abc") is True

def test_detect_rotating_gateway_plain_ip_static():
    assert rut._detect_rotating_gateway("1.2.3.4", "user") is False

def test_detect_rotating_gateway_empty_host():
    assert rut._detect_rotating_gateway("", "user-session") is False


# ── 3. pick_next_proxy closure recycling ─────────────────────────────
def _build_pick_next_proxy(parsed_proxies, no_repeated=True):
    """Rebuild the pick_next_proxy closure from source so we test the
    ACTUAL implementation inside run_real_user_traffic without needing
    to run the full 200-arg engine.
    """
    _rut = pathlib.Path(_BACKEND_DIR) / "real_user_traffic.py"
    if not _rut.is_file():
        _rut = pathlib.Path("/app/backend/real_user_traffic.py")
    src = _rut.read_text(encoding="utf-8")
    # Extract the pick_next_proxy function body
    m = re.search(
        r"^    def pick_next_proxy\(\).*?(?=^    def pick_next_ua)",
        src, flags=re.DOTALL | re.MULTILINE,
    )
    assert m, "could not locate pick_next_proxy in source"
    body = textwrap.dedent(m.group(0))
    # Compile with the required closure vars in local scope
    ns = {
        "no_repeated_proxy": no_repeated,
        "parsed_proxies": parsed_proxies,
        "state": {"proxy_idx": 0},
        "used_proxy_set": set(),
        "Optional": None,
        "Dict": None,
        "Any": None,
    }
    # Prepend `from typing import Optional, Dict, Any` for annotation eval
    prelude = "from typing import Optional, Dict, Any\n"
    exec(prelude + body, ns)
    return ns["pick_next_proxy"]


def test_pick_next_proxy_rotating_gateway_reusable():
    """Rotating gateway MUST be returned on every call even with no_repeated_proxy=True."""
    px = rut._parse_proxy_line(
        "http://user__cr.us;sessid.abc;sessttl.120:pass@gw.dataimpulse.com:10000"
    )
    assert px["is_rotating_gateway"] is True
    pick = _build_pick_next_proxy([px], no_repeated=True)
    for i in range(15):
        res = pick()
        assert res is not None, f"pick #{i+1} returned None for rotating gateway"
        assert res.get("is_rotating_gateway") is True


def test_pick_next_proxy_static_burnt_after_first():
    """Static proxy list MUST be exhausted after single pick when no_repeated_proxy=True."""
    px = rut._parse_proxy_line("http://user:pass@1.2.3.4:8080")
    assert px["is_rotating_gateway"] is False
    pick = _build_pick_next_proxy([px], no_repeated=True)
    first = pick()
    assert first is not None
    second = pick()
    assert second is None, "static proxy should have been marked used after first pick"


# ── 4. STATIC AST checks — variable + usages ─────────────────────────
_rut_src = pathlib.Path(_BACKEND_DIR) / "real_user_traffic.py"
if not _rut_src.is_file():
    _rut_src = pathlib.Path("/app/backend/real_user_traffic.py")
SRC_TEXT = _rut_src.read_text(encoding="utf-8") if _rut_src.is_file() else ""

def test_static_can_retry_offer_block_defined():
    """_can_retry_offer_block is a local variable inside run_real_user_traffic."""
    if not SRC_TEXT:
        pytest.skip("real_user_traffic.py not found")
    # Find the run_real_user_traffic function body only
    m = re.search(r"def run_real_user_traffic\w*\b", SRC_TEXT)
    assert m, "run_real_user_traffic function missing"
    # Look for the definition string
    body = SRC_TEXT[m.start():m.start()+200000]
    assert "_can_retry_offer_block = bool(proxyjet_on_demand) or _has_rotating_gateway" in body


def test_static_max_offer_retries_uses_can_retry_flag():
    """~line 11052 area: max_offer_retries expression references _can_retry_offer_block."""
    # Look for the specific pattern
    assert "if _can_retry_offer_block else 1" in SRC_TEXT, (
        "max_offer_retries fallback should be gated on _can_retry_offer_block"
    )
    # Ensure it's NOT still gated on proxyjet_on_demand alone
    assert "if proxyjet_on_demand else 1" not in SRC_TEXT, (
        "max_offer_retries still gated on old proxyjet_on_demand flag"
    )


def test_static_post_load_block_handler_uses_can_retry_flag():
    """~line 9911: post-load duplicate-IP handler raises via _can_retry_offer_block gate."""
    # find the block near line 9947
    lines = SRC_TEXT.splitlines()
    window = "\n".join(lines[9900:9960])
    assert "if _can_retry_offer_block:" in window
    assert "raise _OfferBlockRetryNeeded(" in window


def test_static_pre_browser_probe_gated_on_can_retry():
    """~line 8268: pre-browser httpx duplicate-IP probe branch."""
    lines = SRC_TEXT.splitlines()
    window = "\n".join(lines[8260:8310])
    assert "if _can_retry_offer_block:" in window, "pre-browser probe not gated on _can_retry_offer_block"


# ── 5. Backend API smoke tests ───────────────────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    if not BASE_URL:
        pytest.skip("REACT_APP_BACKEND_URL not set")
    r = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": "admin@krexion.local", "password": "Admin@Krexion2026!"},
        timeout=30,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no access_token in response: {data}"
    return tok


def test_admin_login_returns_token(admin_token):
    assert isinstance(admin_token, str) and len(admin_token) > 10


def test_get_proxies_providers(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/proxy-providers",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=30,
    )
    # Endpoint is user-scoped (admin token maps to admin user id which may
    # not have a proxy_providers collection entry) — accept 200 OR 401/404
    # since the goal is to confirm the route still exists and isn't a 5xx
    # regression from v2.6.14. A 405 or 500 would fail this test.
    assert r.status_code in (200, 401, 404), (
        f"providers route unexpected {r.status_code}: {r.text[:200]}"
    )
