"""v2.6.90 — Clicks==Hosts: browser-only single affiliate touch."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

RUT = Path(__file__).resolve().parents[1] / "real_user_traffic.py"


def _src() -> str:
    return RUT.read_text(encoding="utf-8")


def test_pass_to_offer_no_server_side_resolve_before_browser():
    src = _src()
    idx = src.index("v2.6.90 — SINGLE CLICK (Clicks == Hosts):")
    chunk = src[idx : idx + 900]
    assert "_resolve_tracker_via_localhost(" not in chunk
    assert "browser-only 1 click" in chunk


def test_resolve_not_in_pass_to_offer_main_path():
    src = _src()
    ptro = src.index('if _referer_cfg.get("pass_to_offer") and _visit_target_url:')
    # Next affiliate resolve after pass-to-offer block should be bypass-only
    nxt = src.find("_resolve_tracker_via_localhost(", ptro + 20)
    bypass = src.find("Proxy can't reach your own tracker", ptro)
    assert bypass != -1
    assert nxt > bypass, "Main pass-to-offer must not call server-side resolve"


def test_reachability_skipped_in_single_click_modes():
    src = _src()
    assert "Single-click mode — skipping pre-flight reachability probe" in src
    idx = src.index("if _is_tracker_target or _referer_cfg.get(\"pass_to_offer\")")
    assert "skip_duplicate_ip" in src[idx : idx + 80]


def test_tls_prewarm_off_by_default():
    src = _src()
    assert "tls_prewarm: bool = False" in src


def test_tls_prewarm_skipped_when_skip_duplicate_ip():
    src = _src()
    idx = src.index("v2.6.89/90 — REGRESSION FIX")
    chunk = src[idx : idx + 700]
    assert "skip_duplicate_ip" in chunk
    assert "_referer_cfg.get(\"pass_to_offer\")" in chunk


def test_version_is_2_6_90():
    version = (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    assert version == "2.6.90"
