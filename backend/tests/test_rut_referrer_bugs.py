"""
Regression tests for RUT referrer resolution bug fixes (11 bugs).
Tests the /api/links/preview-referrer endpoint which exercises resolve_pro_visit
plus regression checks on adjacent endpoints (health, admin login, referrer-pro
defaults, RUT job list).

Bug reference:
  #1  network_click_chain must set network_click_referer for search + email too
  #2  search_engine override honoured (pro-mode uses correct SE)
  #3  legacy google_search mode accepts search_engine/country/strip_path
  #5  email pool + network_click_chain returns network_click_referer
  #6  search pool + network_click_chain returns network_click_referer
  #7  random_list bare homepages deepened (unit tested; smoke here)
  #8  all-zero weight pool falls back to equal weights (not empty)
  #9  pass_to_offer without Referer (unit tested; smoke here)
  #10 hostname exact matching (unit tested; regression via preview)
  #11 parse_weighted_pool returns sorted by weight desc
"""

import os
import json
import uuid
import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Read from frontend/.env if not exported
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.strip().split("=", 1)[1].strip('"').rstrip("/")
                    break
    except Exception:
        pass

assert BASE_URL, "REACT_APP_BACKEND_URL is not set"

ADMIN_EMAIL = "admin@krexion.local"
ADMIN_PASSWORD = "Krexion@2026"


# ─────────────────────────── Fixtures ──────────────────────────────────

@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_token(api):
    r = api.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def test_user(api, admin_token):
    """Create a fresh regular test user and activate via admin."""
    email = f"TEST_rutbug_{uuid.uuid4().hex[:8]}@example.com"
    reg = api.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "TestPass123!", "name": "RUT Bug Test"},
        timeout=15,
    )
    assert reg.status_code == 200, f"Register failed: {reg.status_code} {reg.text}"
    data = reg.json()
    user_id = data["user"]["id"]
    user_token = data["access_token"]

    # Activate the user so features unlock
    r = api.put(
        f"{BASE_URL}/api/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "active"},
        timeout=15,
    )
    assert r.status_code == 200, f"Activation failed: {r.status_code} {r.text}"
    return {"id": user_id, "email": email, "token": user_token}


@pytest.fixture(scope="session")
def user_headers(test_user):
    return {
        "Authorization": f"Bearer {test_user['token']}",
        "Content-Type": "application/json",
    }


# ─────────────────────────── Regression / Health ────────────────────────

class TestRegressionHealth:
    """Sanity checks — adjacent endpoints unchanged."""

    def test_admin_login(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_referrer_pro_defaults(self, api):
        r = api.get(f"{BASE_URL}/api/referrer-pro/defaults", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "platforms" in data
        assert "email_default_weights" in data
        assert isinstance(data["platforms"], list) and len(data["platforms"]) > 0
        # sanity: known platforms in defaults
        for p in ("facebook", "google", "email"):
            assert p in data["platforms"], f"missing platform {p} in defaults"

    def test_get_links_endpoint(self, api, user_headers):
        r = api.get(f"{BASE_URL}/api/links", headers=user_headers, timeout=15)
        # 200 or auth-related is fine; 500 is a fail
        assert r.status_code != 500, f"GET /api/links 500: {r.text}"
        assert r.status_code in (200, 401, 403), r.status_code

    def test_get_rut_jobs_endpoint(self, api, user_headers):
        r = api.get(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            timeout=15,
        )
        assert r.status_code != 500, f"GET /api/real-user-traffic/jobs 500: {r.text}"
        assert r.status_code in (200, 401, 403), r.status_code


# ─────────────────────── Preview endpoint helpers ────────────────────────

def _preview(api, headers, payload, timeout=30):
    """Call preview-referrer and return parsed json."""
    r = api.post(
        f"{BASE_URL}/api/links/preview-referrer",
        headers=headers,
        data=json.dumps(payload),
        timeout=timeout,
    )
    assert r.status_code == 200, f"preview-referrer HTTP {r.status_code}: {r.text[:400]}"
    body = r.json()
    assert body.get("ok") is True, f"preview response not ok: {body}"
    assert "samples" in body and "distribution" in body
    return body


# ─────────────────────────── Bug #1 / #5 / #6 ────────────────────────────

class TestNetworkClickReferer:
    """
    Retired-chain contract — stale clients may still submit the old flag,
    but no platform may receive a synthetic network click referer.
    """

    def test_google_pool_with_network_click(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps({"google": 100}),
            "referrer_pro_network_click_chain": True,
            "sample_count": 10,
        })
        for s in body["samples"]:
            assert "error" not in s, f"resolver error: {s}"
            assert s["platform"] == "google", f"expected google, got {s['platform']}"
            assert not s["network_click_referer"], s

    def test_email_pool_with_network_click(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps({"email": 100}),
            "referrer_pro_network_click_chain": True,
            "sample_count": 10,
        })
        for s in body["samples"]:
            assert "error" not in s, f"resolver error: {s}"
            assert s["platform"] == "email", f"expected email, got {s['platform']}"
            assert not s["network_click_referer"], s

    def test_bing_pool_with_network_click(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps({"bing": 100}),
            "referrer_pro_network_click_chain": True,
            "sample_count": 8,
        })
        for s in body["samples"]:
            assert "error" not in s
            assert s["platform"] == "bing"
            assert not s["network_click_referer"], s


# ─────────────────────────── Bug #2 ─────────────────────────────────────

class TestSearchEngineOverride:
    """Bug #2 — search_engine override MUST rewrite google→bing/ddg."""

    def test_google_pool_forced_bing(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps({"google": 100}),
            "referrer_pro_search_engine": "bing",
            "sample_count": 10,
        })
        for s in body["samples"]:
            assert "error" not in s
            ref = s["referer"] or ""
            assert "bing.com" in ref, (
                f"Bug #2: expected bing.com referer when search_engine=bing, got {ref!r} "
                f"(platform={s['platform']})"
            )
            assert "google.com" not in ref, (
                f"Bug #2: referer still contains google.com despite override: {ref!r}"
            )

    def test_google_pool_forced_ddg(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps({"google": 100}),
            "referrer_pro_search_engine": "ddg",
            "sample_count": 10,
        })
        for s in body["samples"]:
            assert "error" not in s
            ref = s["referer"] or ""
            assert ref.startswith("https://duckduckgo.com"), (
                f"Bug #2: ddg alias not honoured, referer={ref!r}"
            )


# ─────────────────────────── Bug #3 ─────────────────────────────────────

class TestLegacyGoogleSearchMode:
    """
    Bug #3 — legacy google_search mode with search_engine=bing + country=de must
    be accepted by the RUT jobs endpoint without a validation error.
    We just verify the POST is not rejected with 422/500 due to the new fields;
    422 for missing required (e.g. link_id) is fine — that means the payload
    shape was accepted.
    """

    def test_rut_job_create_accepts_legacy_fields(self, api, user_headers):
        payload = {
            "link_id": "does-not-exist-" + uuid.uuid4().hex[:6],
            "referer_mode": "google_search",
            "search_engine": "bing",
            "country": "de",
            "strip_search_path": True,
            "visits": 1,
        }
        r = api.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=json.dumps(payload),
            timeout=20,
        )
        # 500 = broken; anything else means shape accepted or rejected on
        # business logic (missing link, feature gate, etc.) — that's fine.
        assert r.status_code != 500, (
            f"Bug #3: RUT job endpoint 500 for legacy google_search fields: {r.text[:500]}"
        )
        # explicit-schema validation should not complain about our fields
        if r.status_code == 422:
            errs = r.json().get("detail", [])
            bad = [
                e for e in errs
                if isinstance(e, dict)
                and any(
                    fld in str(e.get("loc", []))
                    for fld in ("search_engine", "country", "referer_mode", "strip_search_path")
                )
            ]
            assert not bad, f"Bug #3: RUT rejected new legacy fields: {bad}"


# ─────────────────────────── Bug #7 / #9 / #10 ───────────────────────────

class TestSmokeUnchangedPaths:
    """Bugs #7/#9/#10 primarily covered by unit tests — smoke here."""

    def test_preview_default_settings_200(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "sample_count": 5,
        })
        assert len(body["samples"]) == 5
        # every sample has a platform string
        assert all(s.get("platform") for s in body["samples"] if "error" not in s)


# ─────────────────────────── Bug #8 ─────────────────────────────────────

class TestZeroWeightFallback:
    """Bug #8 — all-zero weights fall back to equal-weight (not empty)."""

    def test_all_zero_weights_equal_fallback(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps(
                {"facebook": 0, "tiktok": 0, "instagram": 0}
            ),
            "sample_count": 30,
        })
        dist = body["distribution"]
        assert dist, f"Bug #8: distribution empty for all-zero weights: {body}"
        platforms_picked = {d["platform"] for d in dist}
        expected = {"facebook", "tiktok", "instagram"}
        missing = expected - platforms_picked
        assert not missing, (
            f"Bug #8: expected equal-fallback across {expected}, but missing {missing}. "
            f"got={platforms_picked}"
        )
        # roughly equal — none should completely dominate (>75%)
        for d in dist:
            if d["platform"] in expected:
                assert d["pct"] < 75.0, (
                    f"Bug #8: {d['platform']} dominates at {d['pct']}% — not equal fallback"
                )


# ─────────────────────────── Bug #11 ────────────────────────────────────

class TestDistributionSortedByWeight:
    """Bug #11 — parse_weighted_pool sorts by weight desc; distribution
    should roughly reflect input weights AND be sorted by count desc."""

    def test_distribution_sorted_by_weight(self, api, user_headers):
        body = _preview(api, user_headers, {
            "offer_url": "https://example.com/offer",
            "referrer_pro_platform_pool": json.dumps(
                {"tiktok": 10, "facebook": 50, "google": 30}
            ),
            "sample_count": 60,
        })
        dist = body["distribution"]
        assert dist, "empty distribution"

        # distribution is sorted by count desc in the endpoint response
        counts = [d["count"] for d in dist]
        assert counts == sorted(counts, reverse=True), (
            f"distribution not sorted by count desc: {dist}"
        )

        # facebook (weight 50) should be top and > tiktok (weight 10)
        top_plat = dist[0]["platform"]
        assert top_plat == "facebook", (
            f"Bug #11: expected facebook (weight 50) to top distribution, got {top_plat}. "
            f"dist={dist}"
        )
        counts_by_plat = {d["platform"]: d["count"] for d in dist}
        fb = counts_by_plat.get("facebook", 0)
        gg = counts_by_plat.get("google", 0)
        tt = counts_by_plat.get("tiktok", 0)
        # allow noise but ordering by weight must roughly hold
        assert fb >= gg, f"Bug #11: facebook({fb}) should be >= google({gg}). dist={dist}"
        assert gg >= tt, f"Bug #11: google({gg}) should be >= tiktok({tt}). dist={dist}"


# ─────────────────────────── Cleanup ────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_user(request, api, admin_token, test_user):
    yield
    # Best-effort delete the test user
    try:
        api.delete(
            f"{BASE_URL}/api/admin/users/{test_user['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
    except Exception:
        pass
