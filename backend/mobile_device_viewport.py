"""Resolve real mobile device viewport (CSS + physical px) from profile or catalog."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Import catalog helpers from browser profiles (single source of truth).
from browser_profile_module import _DEVICE_CATALOG, _find_device


def list_mobile_devices(platform: str = "") -> List[Dict[str, Any]]:
    """Return catalog entries, optionally filtered by ios/android."""
    plat = (platform or "").strip().lower()
    if not plat:
        return [d for d in _DEVICE_CATALOG if d.get("platform") in ("ios", "android")]
    if plat in ("ios", "ipados"):
        return [d for d in _DEVICE_CATALOG if d.get("platform") == "ios"]
    return [d for d in _DEVICE_CATALOG if d.get("platform") == plat]


def _match_device_by_label(label: str) -> Optional[Dict[str, Any]]:
    key = (label or "").strip().lower()
    if not key:
        return None
    for d in _DEVICE_CATALOG:
        if str(d.get("label") or "").lower() == key:
            return d
        if str(d.get("slug") or "").lower().replace("-", "") == key.replace(" ", ""):
            return d
    # fuzzy: "iphone 15 pro max" in label
    for d in _DEVICE_CATALOG:
        dl = str(d.get("label") or "").lower()
        if key in dl or dl in key:
            return d
    return None


def resolve_device_spec(
    *,
    device_id: str = "",
    device_label: str = "",
    viewport: Optional[Dict[str, Any]] = None,
    device_scale_factor: float = 0,
) -> Dict[str, Any]:
    """
    Return canonical viewport for shell + Playwright.

    Advertiser-facing CSS viewport comes from the device catalog when known;
    profile viewport is used only as fallback.
    """
    device = _find_device(device_id) if device_id else None
    if not device and device_label:
        device = _match_device_by_label(device_label)

    vp = dict(viewport or {})
    if device:
        dvp = dict(device.get("viewport") or {})
        w = int(dvp.get("width") or vp.get("width") or 393)
        h = int(dvp.get("height") or vp.get("height") or 852)
        dpr = float(device_scale_factor or device.get("dpr") or 3.0)
        return {
            "width": w,
            "height": h,
            "device_scale_factor": dpr,
            "physical_width": int(round(w * dpr)),
            "physical_height": int(round(h * dpr)),
            "device_id": str(device.get("id") or ""),
            "device_label": str(device.get("label") or device_label or ""),
            "platform": str(device.get("platform") or ""),
            "from_catalog": True,
        }

    w = int(vp.get("width") or 393)
    h = int(vp.get("height") or 852)
    dpr = float(device_scale_factor or 3.0)
    return {
        "width": w,
        "height": h,
        "device_scale_factor": dpr,
        "physical_width": int(round(w * dpr)),
        "physical_height": int(round(h * dpr)),
        "device_id": str(device_id or ""),
        "device_label": str(device_label or ""),
        "platform": "",
        "from_catalog": False,
    }


def resolve_profile_device_viewport(profile_config: Dict[str, Any]) -> Dict[str, Any]:
    """Map stored browser profile → real device viewport."""
    cfg = profile_config or {}
    return resolve_device_spec(
        device_id=str(cfg.get("device_catalog_id") or cfg.get("device_id") or ""),
        device_label=str(cfg.get("device_label") or cfg.get("device_model") or ""),
        viewport=cfg.get("viewport") if isinstance(cfg.get("viewport"), dict) else None,
        device_scale_factor=float(cfg.get("device_scale_factor") or 0),
    )
