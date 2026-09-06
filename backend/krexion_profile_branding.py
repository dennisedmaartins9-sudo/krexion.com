"""
Krexion Profile Branding (v2.7.129) — AdsPower-parity identity layer
====================================================================
AdsPower profile UX surfaces we match without a Chromium source rebuild:

1. Product engines (like SunBrowser / FlowerBrowser):
   - Krexion Browser  → Chromium / Cloak / Patchright path
   - Krexion Safari   → WebKit / MiniBrowser path (iOS-shaped)

2. Taskbar / window identity (Global Settings → Custom Icon):
   - profile_no | name | notes | custom_no | default
   - Title format: ``Krexion Browser — {identity}``

3. AppUserModelID: ``Krexion.BrowserProfile.{N}`` (taskbar grouping)

4. User-facing copy: never say Chromium / Playwright / WebKit / chrome.exe
   in toasts, cards, or launch messages (logs may stay technical).

True Chromium window-class / chrome.dll ProductName rewrite needs a
forked kernel — tracked as a later major step.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# AdsPower: SunBrowser (Chrome) / FlowerBrowser (Firefox)
# Krexion:  Krexion Browser (Chrome-shaped) / Krexion Safari (WebKit iOS)
PRODUCT_BROWSER = "Krexion Browser"
PRODUCT_SAFARI = "Krexion Safari"
PRODUCT_PHONE = "Krexion Phone"

ICON_MODES = ("profile_no", "name", "notes", "custom_no", "default")

# Customer-visible vendor leaks → Krexion product wording
_USER_FACING_REPLACEMENTS = (
    (re.compile(r"\bPlaywright\s+WebKit(?:\s+MiniBrowser)?\b", re.I), PRODUCT_SAFARI),
    (re.compile(r"\bPlaywright/Cloak\s+Chromium\b", re.I), f"{PRODUCT_BROWSER} Stealth"),
    (re.compile(r"\bPlaywright\b", re.I), "Krexion Browser engine"),
    (re.compile(r"\bMiniBrowser\b", re.I), PRODUCT_SAFARI),
    (re.compile(r"\bWebKit\b", re.I), PRODUCT_SAFARI),
    (re.compile(r"\bChromium\b", re.I), PRODUCT_BROWSER),
    (re.compile(r"\bchrome\.exe\b", re.I), "krexion-browser.exe"),
    (re.compile(r"\bGoogle Chrome\b", re.I), PRODUCT_BROWSER),
    (re.compile(r"\bCloakBrowser\b", re.I), f"{PRODUCT_BROWSER} Stealth"),
    (re.compile(r"\bPatchright\b", re.I), f"{PRODUCT_BROWSER} Hardened"),
)


def resolve_icon_mode(anti: Optional[Dict[str, Any]] = None, profile: Optional[Dict[str, Any]] = None) -> str:
    anti = anti or {}
    profile = profile or {}
    raw = (
        anti.get("taskbar_icon_mode")
        or anti.get("custom_icon_mode")
        or profile.get("taskbar_icon_mode")
        or profile.get("custom_icon_mode")
        or "profile_no"
    )
    mode = str(raw or "profile_no").strip().lower()
    return mode if mode in ICON_MODES else "profile_no"


def profile_identity_text(
    *,
    slot: int = 1,
    name: str = "",
    notes: str = "",
    custom_no: str = "",
    icon_mode: str = "profile_no",
) -> str:
    """AdsPower Custom Icon text shown on taskbar / next to product name."""
    mode = icon_mode if icon_mode in ICON_MODES else "profile_no"
    nm = (name or "").strip() or f"Profile {int(slot or 1)}"
    nt = (notes or "").strip()
    cn = (custom_no or "").strip()
    if mode == "name":
        return nm[:48]
    if mode == "notes":
        return (nt or nm)[:48]
    if mode == "custom_no":
        # AdsPower: last 4 digits of custom NO on taskbar icon
        digits = re.sub(r"\D+", "", cn) or str(int(slot or 1))
        return digits[-4:] if digits else str(int(slot or 1))
    if mode == "default":
        return PRODUCT_BROWSER
    # profile_no (default AdsPower-like)
    return str(int(slot or 1))


def build_window_title(
    *,
    slot: int = 1,
    name: str = "",
    notes: str = "",
    custom_no: str = "",
    icon_mode: str = "profile_no",
    webkit: bool = False,
    phone: bool = False,
) -> str:
    """Durable window / taskbar title — AdsPower: SunBrowser + identity."""
    product = PRODUCT_PHONE if phone else (PRODUCT_SAFARI if webkit else PRODUCT_BROWSER)
    identity = profile_identity_text(
        slot=slot,
        name=name,
        notes=notes,
        custom_no=custom_no,
        icon_mode=icon_mode,
    )
    # Keep name visible when icon mode is number-only (AdsPower shows both)
    nm = (name or "").strip()
    if icon_mode in ("profile_no", "custom_no") and nm and nm.lower() not in identity.lower():
        return f"{product} — {identity} · {nm[:32]}"
    return f"{product} — {identity}"


def app_user_model_id(slot: int = 1, *, phone: bool = False) -> str:
    n = max(1, int(slot or 1))
    if phone:
        return f"Krexion.PhoneChrome.{n}"
    return f"Krexion.BrowserProfile.{n}"


def chromium_app_user_model_arg(slot: int = 1) -> str:
    """Chromium CLI flag (best-effort; HWND props still set via Win32)."""
    return f"--app-user-model-id={app_user_model_id(slot)}"


def sanitize_user_facing(text: str) -> str:
    """Strip vendor names from customer-visible strings."""
    out = str(text or "")
    # Longer phrases first
    for pat, repl in _USER_FACING_REPLACEMENTS:
        out = pat.sub(repl, out)
    # Collapse accidental double product names from stacked replacements
    out = re.sub(
        rf"(?:{re.escape(PRODUCT_SAFARI)}\s*){{2,}}",
        PRODUCT_SAFARI + " ",
        out,
    )
    out = re.sub(
        rf"(?:{re.escape(PRODUCT_BROWSER)}\s*){{2,}}",
        PRODUCT_BROWSER + " ",
        out,
    )
    return out.strip()


def public_engine_label(kernel_label: str = "", *, webkit: bool = False) -> str:
    raw = str(kernel_label or "").lower()
    if webkit or "webkit" in raw or "safari" in raw or "minibrowser" in raw:
        return PRODUCT_SAFARI
    if "stealth" in raw or "cloak" in raw:
        return f"{PRODUCT_BROWSER} Stealth"
    if "hardened" in raw or "patchright" in raw:
        return f"{PRODUCT_BROWSER} Hardened"
    if "firefox" in raw:
        return "Krexion Firefox"
    return PRODUCT_BROWSER


def branding_info_dict(profile: Optional[Dict[str, Any]] = None, anti: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    profile = profile or {}
    anti = anti or {}
    slot = int(profile.get("taskbar_slot") or profile.get("slot") or 1)
    mode = resolve_icon_mode(anti, profile)
    webkit = str(profile.get("engine") or anti.get("engine") or "").lower() in (
        "webkit",
        "safari",
        "ios",
    )
    title = build_window_title(
        slot=slot,
        name=str(profile.get("name") or ""),
        notes=str(profile.get("notes") or ""),
        custom_no=str(profile.get("custom_no") or profile.get("serial_number") or ""),
        icon_mode=mode,
        webkit=webkit,
        phone=bool(profile.get("is_mobile") or anti.get("mobile_shell")),
    )
    return {
        "product_browser": PRODUCT_BROWSER,
        "product_safari": PRODUCT_SAFARI,
        "icon_mode": mode,
        "window_title": title,
        "app_user_model_id": app_user_model_id(
            slot, phone=bool(profile.get("is_mobile") or anti.get("mobile_shell"))
        ),
        "identity": profile_identity_text(
            slot=slot,
            name=str(profile.get("name") or ""),
            notes=str(profile.get("notes") or ""),
            custom_no=str(profile.get("custom_no") or profile.get("serial_number") or ""),
            icon_mode=mode,
        ),
    }
