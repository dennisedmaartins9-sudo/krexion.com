"""
Focused unit + static tests for the 2026-02 v2.6.13 RUT referrer/concurrency bug fixes.

Bugs verified:
  1. Custom Referrer URL 'https://getstimulus.ai/' honoured for EVERY visit
     (regression: 13/17 empty referer report).
  2. TikTok in-app preset scrubs foreign markers (fban, fbav, instagram, ...)
     and produces UAs coercible to TikTok in-app markers
     (regression: 8/17 Chrome UAs report).
  3. _make_macro_guard force_referer parameter injects Referer on document
     navigations through redirect chains.
  4. RUT-PARALLEL log lines exist in worker (semaphore block) + dispatcher
     for concurrency observability.
  5. ctx_args → _ctx_headers F821 fix in v230 stealth apply block.
  6. _multi_step_fill has optional fp param + three usages guarded.
  7. POST /api/admin/login smoke check.
"""

import os
import re
import sys
import inspect
import pytest
import requests

sys.path.insert(0, "/app/backend")

import real_user_traffic as rut  # noqa: E402
from referrer_pro import coerce_ua_for_platform, _INAPP_CAPABLE_PLATFORMS  # noqa: E402


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                    break
    except Exception:
        pass


# ────────────────────────── Bug #1 — Referer resolver ─────────────────────
class TestResolveVisitReferer:
    """Every visit must return the operator's custom URL, regardless of UA."""

    CFG = {
        "enabled": True,
        "mode": "custom",
        "value": "https://getstimulus.ai/",
        "pass_to_offer": True,
        "preset_platform": "tiktok",
        "match_ua_to_platform": True,
    }

    UAS = [
        # Desktop chrome
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        # iOS Safari
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        # Facebook in-app (foreign marker)
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/119.0 Mobile Safari/537.36 [FBAN/FB4A;FBAV/443.0]",
        # Android Chrome mobile
        "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36",
        # Empty UA
        "",
    ]

    @pytest.mark.parametrize("ua", UAS)
    def test_custom_url_returned_for_every_ua(self, ua):
        ref, platform, esp, extras = rut._resolve_visit_referer(ua, self.CFG)
        assert ref == "https://getstimulus.ai/", (
            f"Bug#1 regression: expected operator URL for UA={ua!r}, got {ref!r}"
        )
        # platform signal must resolve to tiktok via preset_platform fallback
        assert platform == "tiktok", f"platform_signal expected tiktok, got {platform!r}"
        assert isinstance(extras, dict)

    def test_disabled_cfg_falls_back(self):
        ref, plat, _, _ = rut._resolve_visit_referer(
            "Mozilla/5.0 (Linux; Android)", {"enabled": False}
        )
        # Should NOT be the getstimulus URL
        assert ref != "https://getstimulus.ai/"


# ─────────────────────── Bug #2 — In-app preset scrub ─────────────────────
class TestInappPresetScrub:
    def test_tiktok_scrubs_foreign_and_desktop_uas(self):
        mixed = [
            # desktop chrome
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            # FB in-app (foreign)
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/119.0 Mobile [FBAN/FB4A;FBAV/443.0]",
            # Instagram in-app (foreign)
            "Mozilla/5.0 (Linux; Android 13; SM-A536E) AppleWebKit/537.36 Chrome/119.0 Mobile Safari/537.36 Instagram 300.0.0.0",
            # LinkedInApp
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/119.0 Mobile Safari/537.36 LinkedInApp",
            # Snapchat
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Snapchat/12",
            # Twitter
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36 Twitter",
            # Clean mobile android chrome — should be kept
            "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36",
            # Clean iOS mobile safari — should be kept
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        ]
        out = rut._apply_inapp_preset_to_uas(mixed, want_count=10, preset_platform="tiktok")
        assert out, "output must not be empty"
        assert len(out) == len(mixed) or len(out) == 10, f"unexpected length: {len(out)}"

        foreign = ("fban", "fbav", "fb_iab", "fb4a", "instagram",
                   "linkedinapp", "snapchat", "twitter")
        for ua in out:
            ul = ua.lower()
            for marker in foreign:
                assert marker not in ul, f"foreign marker {marker!r} in scrubbed UA: {ua}"
            # every UA must be mobile
            is_mobile = ("android" in ul) or ("iphone" in ul) or ("ipad" in ul)
            assert is_mobile, f"non-mobile UA returned: {ua}"

    def test_coerce_produces_tiktok_marker(self):
        assert "tiktok" in _INAPP_CAPABLE_PLATFORMS

        clean_mobile = [
            "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        ] * 5

        preset = rut._apply_inapp_preset_to_uas(clean_mobile, want_count=10, preset_platform="tiktok")
        tiktok_markers = ("musical_ly", "aweme", "trill_", "bytedancewebview")
        for ua in preset:
            coerced = coerce_ua_for_platform(ua, "tiktok")
            cl = coerced.lower()
            assert any(m in cl for m in tiktok_markers), (
                f"coerced UA missing tiktok marker: {coerced!r}"
            )


# ─────────────────────── Bug #3 — _make_macro_guard force_referer ─────────
class _FakeRequest:
    def __init__(self, resource_type="document", url="https://tracker.example.com/api/t/xyz",
                 headers=None):
        self.resource_type = resource_type
        self.url = url
        self.headers = headers or {"user-agent": "test-ua", "accept": "*/*"}


class _FakeRoute:
    def __init__(self):
        self.continue_called_with = None
        self.continue_called_no_args = False

    async def continue_(self, **kwargs):
        if kwargs:
            self.continue_called_with = kwargs
        else:
            self.continue_called_no_args = True

    async def fulfill(self, **kwargs):
        pass

    async def abort(self):
        pass


import asyncio


class TestMacroGuardForceReferer:
    def test_document_gets_referer_injected(self):
        handler = rut._make_macro_guard(
            "job-1", 1,
            force_referer="https://getstimulus.ai/",
            target_url="https://tracker.example.com/api/t/xyz",
        )
        route = _FakeRoute()
        req = _FakeRequest(resource_type="document")
        asyncio.run(handler(route, req))
        assert route.continue_called_with is not None, (
            "expected route.continue_ called with headers on document navigation"
        )
        hdrs = route.continue_called_with.get("headers") or {}
        assert hdrs.get("referer") == "https://getstimulus.ai/", (
            f"expected referer injected, got headers={hdrs!r}"
        )
        # capital-R must be popped
        assert "Referer" not in hdrs

    def test_non_document_no_override(self):
        handler = rut._make_macro_guard(
            "job-1", 2,
            force_referer="https://getstimulus.ai/",
            target_url="https://tracker.example.com/api/t/xyz",
        )
        route = _FakeRoute()
        req = _FakeRequest(resource_type="xhr", url="https://tracker.example.com/api/pixel.gif")
        asyncio.run(handler(route, req))
        assert route.continue_called_no_args, (
            "expected route.continue_() called without headers for non-document"
        )
        assert route.continue_called_with is None

    def test_empty_force_referer_no_override(self):
        """Regression guard: force_referer='' MUST NOT override headers."""
        handler = rut._make_macro_guard("job-1", 3, force_referer="", target_url="")
        route = _FakeRoute()
        req = _FakeRequest(resource_type="document")
        asyncio.run(handler(route, req))
        assert route.continue_called_no_args, (
            "empty force_referer must NOT override — got headers override"
        )


# ─────────────────────── Bug #4 — RUT-PARALLEL log lines ──────────────────
class TestParallelLoggingPresent:
    def test_worker_semaphore_log(self):
        src = inspect.getsource(rut)
        # process_one START inside semaphore block
        assert re.search(
            r"\[RUT-PARALLEL job=\{job_id\}\] visit#\{i \+ 1\} process_one START",
            src,
        ), "missing worker RUT-PARALLEL START log line"

    def test_dispatcher_log(self):
        src = inspect.getsource(rut)
        assert re.search(
            r"\[RUT-PARALLEL job=\{job_id\}\] visit#\{attempt_counter \+ 1\} dispatched",
            src,
        ), "missing dispatcher RUT-PARALLEL dispatched log line"


# ─────────────────────── Bug #5 — ctx_args F821 fix ───────────────────────
class TestCtxArgsFix:
    def test_v230_block_uses_ctx_headers(self):
        # Inspect the helper by symbol instead of brittle whole-file line
        # offsets, which move whenever lifecycle/reporting code is added.
        v230_block = inspect.getsource(rut._rut_apply_context_stealth)
        assert "ctx_headers" in v230_block, "expected ctx_headers in v230 stealth helper"
        # No live reference to ctx_args (only comment mentioning history is OK,
        # but no code path should reference the undefined variable)
        code_only = "\n".join(
            ln for ln in v230_block.splitlines()
            if not ln.strip().startswith("#")
        )
        assert "ctx_args" not in code_only, (
            f"ctx_args still referenced in v230 code path: {code_only}"
        )


# ─────────────────────── Bug #6 — _multi_step_fill(fp=) ───────────────────
class TestMultiStepFillFp:
    def test_signature_accepts_fp(self):
        sig = inspect.signature(rut._multi_step_fill)
        assert "fp" in sig.parameters, "_multi_step_fill missing fp param"
        p = sig.parameters["fp"]
        assert p.default is None, "fp param should default to None"

    def test_fp_usages_guarded(self):
        src_lines = inspect.getsource(rut._multi_step_fill).splitlines()
        # each `fp` reference (that isn't a keyword-arg or the signature)
        # should be preceded/guarded by `if fp is not None`
        guarded_count = sum(1 for ln in src_lines if "if fp is not None" in ln)
        assert guarded_count >= 3, (
            f"expected >=3 `if fp is not None` guards, got {guarded_count}"
        )


# ─────────────────────── Bug #7 — Admin login smoke ───────────────────────
class TestAdminLoginSmoke:
    def test_admin_login_200(self):
        assert BASE_URL, "REACT_APP_BACKEND_URL missing"
        r = requests.post(
            f"{BASE_URL}/api/admin/login",
            json={"email": "admin@krexion.local", "password": "Admin@Krexion2026!"},
            timeout=20,
        )
        assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        assert "access_token" in body and isinstance(body["access_token"], str)
        assert body.get("is_admin") is True, f"is_admin flag missing/false: {body}"
