"""Unit tests — light reporting + live JPEG downscale (v2.6.65).

Concurrency is operator-chosen (no RAM hard-cap). These helpers only
cover preview/reporting lightness.
"""
import importlib

import pytest


@pytest.fixture()
def tune(monkeypatch):
    for key in (
        "RUT_MAX_CONCURRENCY",
        "KREXION_ALLOW_HIGH_CONCURRENCY",
        "KREXION_LIGHTWEIGHT",
        "KREXION_FORCE_HEADLESS_SHELL",
        "KREXION_FORCE_FULL_CHROMIUM",
        "KREXION_FORCE_HEAVY_REPORTING",
        "RUT_LIVE_FRAMES",
    ):
        monkeypatch.delenv(key, raising=False)
    import hardware_tune as mod
    importlib.reload(mod)
    return mod


def test_recommended_tiers_still_documented(tune):
    """Tier math still available for diagnostics / docs — not an engine clamp."""
    assert tune.recommended_rut_concurrency(ram_gb=8, cpu_cores=8) == 2
    assert tune.recommended_rut_concurrency(ram_gb=24, cpu_cores=8) == 8


def test_lightweight_reporting_on_low_tier(tune, monkeypatch):
    monkeypatch.setattr(tune, "recommended_rut_concurrency", lambda **_: 2)
    assert tune.lightweight_reporting_enabled() is True
    monkeypatch.setattr(tune, "recommended_rut_concurrency", lambda **_: 8)
    assert tune.lightweight_reporting_enabled() is False


def test_lightweight_env_forces_shell(tune, monkeypatch):
    monkeypatch.setenv("KREXION_LIGHTWEIGHT", "1")
    assert tune.lightweight_reporting_enabled() is True
    assert tune.want_headless_shell() is True


def test_downscale_live_jpeg_shrinks_width(tune):
    pytest.importorskip("PIL")
    import io
    from PIL import Image

    img = Image.new("RGB", (1600, 2400), color=(40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    raw = buf.getvalue()
    out = tune.downscale_live_jpeg(raw, max_width=720, quality=42)
    assert len(out) < len(raw)
    with Image.open(io.BytesIO(out)) as resized:
        assert resized.width == 720
        assert resized.height == 1080
