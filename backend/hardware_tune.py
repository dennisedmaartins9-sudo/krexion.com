"""Host RAM/CPU tuning helpers for RUT concurrency + light reporting.

Kept free of Playwright/heavy imports so unit tests and diagnostics can
import this without pulling the full RUT engine.
"""
from __future__ import annotations

import os
from typing import Optional


def detect_host_ram_gb() -> int:
    """Best-effort host RAM in GB (0 if unknown)."""
    try:
        import psutil as _ps
        return max(0, int(round(_ps.virtual_memory().total / (1024 ** 3))))
    except Exception:
        return 0


def detect_host_cpu_cores() -> int:
    try:
        import psutil as _ps
        return max(1, int(_ps.cpu_count(logical=True) or os.cpu_count() or 1))
    except Exception:
        return max(1, int(os.cpu_count() or 1))


def recommended_rut_concurrency(
    ram_gb: Optional[int] = None,
    cpu_cores: Optional[int] = None,
) -> int:
    """RAM/CPU-safe RUT worker count — same tiers as hardware-profile.

    MICRO <=6GB → 1 | LOW 7-10 → 2 | MID 11-16 → 4 | HIGH 17-32 → 8 | BEAST → 16
    CPU ceiling: cores * 2.
    """
    if ram_gb is None:
        ram_gb = detect_host_ram_gb()
    if cpu_cores is None:
        cpu_cores = detect_host_cpu_cores()
    ram_gb = int(ram_gb or 0)
    cpu_cores = max(1, int(cpu_cores or 1))
    if ram_gb <= 0:
        rut = 2
    elif ram_gb <= 6:
        rut = 1
    elif ram_gb <= 10:
        rut = 2
    elif ram_gb <= 16:
        rut = 4
    elif ram_gb <= 32:
        rut = 8
    else:
        rut = 16
    return max(1, min(rut, cpu_cores * 2))


def effective_rut_hard_cap() -> int:
    """Hard ceiling for concurrent RUT workers on this host.

    - Default: RAM-safe tier (not the old blind default of 50).
    - ``RUT_MAX_CONCURRENCY`` is clamped to the RAM-safe tier unless
      ``KREXION_ALLOW_HIGH_CONCURRENCY=1`` (power-user unlock).
    """
    auto = recommended_rut_concurrency()
    env = (os.environ.get("RUT_MAX_CONCURRENCY") or "").strip()
    env_n = int(env) if env.isdigit() else None
    allow_high = (os.environ.get("KREXION_ALLOW_HIGH_CONCURRENCY") or "").strip().lower() in (
        "1", "true", "yes",
    )
    if env_n is not None:
        if allow_high:
            return max(1, env_n)
        return max(1, min(env_n, auto))
    return max(1, auto)


def lightweight_reporting_enabled() -> bool:
    """Lighter screenshots (jpeg / skip long landing waits / viewport-only).

    ON when RAM-safe concurrency <= 2 (MICRO/LOW), or ``KREXION_LIGHTWEIGHT=1``.
    Does NOT change click/fill/deal automation logic.
    """
    if (os.environ.get("KREXION_LIGHTWEIGHT") or "").strip().lower() in ("1", "true", "yes"):
        return True
    if (os.environ.get("KREXION_FORCE_HEAVY_REPORTING") or "").strip().lower() in (
        "1", "true", "yes",
    ):
        return False
    return recommended_rut_concurrency() <= 2


def want_headless_shell() -> bool:
    """True when operator asked for light browser (weaker stealth, less RAM)."""
    if (os.environ.get("KREXION_FORCE_FULL_CHROMIUM") or "").strip().lower() in (
        "1", "true", "yes",
    ):
        return False
    if (os.environ.get("KREXION_FORCE_HEADLESS_SHELL") or "").strip().lower() in (
        "1", "true", "yes",
    ):
        return True
    if (os.environ.get("KREXION_LIGHTWEIGHT") or "").strip().lower() in ("1", "true", "yes"):
        return True
    return False


def want_live_step_frames_env() -> bool:
    """Operator force-on for per-step live JPEGs even when Visual Grid is closed."""
    return (os.environ.get("RUT_LIVE_FRAMES") or "").strip().lower() in ("1", "true", "yes")


def downscale_live_jpeg(
    jpeg_bytes: bytes,
    *,
    max_width: int = 800,
    quality: int = 45,
) -> bytes:
    """Shrink live-preview JPEG width — full page still readable, far lighter.

    Preview only. Does not affect automation or ZIP evidence quality.
    """
    if not jpeg_bytes or max_width <= 0:
        return jpeg_bytes
    try:
        import io as _io
        from PIL import Image as _Image
        img = _Image.open(_io.BytesIO(jpeg_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")
        if img.width > max_width:
            new_h = max(1, int(round(img.height * (max_width / float(img.width)))))
            img = img.resize((max_width, new_h), _Image.BILINEAR)
        out = _io.BytesIO()
        img.save(out, format="JPEG", quality=max(20, min(int(quality), 85)), optimize=True)
        return out.getvalue()
    except Exception:
        return jpeg_bytes
