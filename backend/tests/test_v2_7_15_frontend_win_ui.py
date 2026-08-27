"""v2.7.15 — Frontend WIN antidetect UI surface checks."""
from __future__ import annotations

from pathlib import Path

FE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"


def test_frontend_win_bundle_controls():
    fe = FE.read_text(encoding="utf-8")
    for needle in (
        'canvas_mode: "noise"',
        'webrtc_mode: "proxy"',
        "proxy_check_on_launch",
        "use_persistent_context",
        "bp-fingerprint-",
        "bp-cookie-robot-",
        'data-testid="bp-local-api-docs"',
        "/fingerprint",
        "cookie-robot",
        "/local/docs",
    ):
        assert needle in fe, f"missing {needle}"
