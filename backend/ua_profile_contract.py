"""Shared user-agent profile, validation, and client-hint coherence contract.

The contract describes what a UA claims to be.  It does not add headers to
requests and it deliberately distinguishes browser engines from native
network stacks such as Cronet and CFNetwork.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional


# Curated compatibility pools.  These are cold-start/reference values, not a
# claim that any value is live or latest.  server.py may refresh supported
# pools from documented upstream sources at runtime.
APP_VERSION_POOLS = {
    "instagram": ["425.0.0", "422.0.0", "420.0.0.35.87", "418.0.0", "415.0.0.36.111", "412.0.0.35.87", "410.0.0.36.111"],
    "facebook": ["557.0", "555.0", "553.0", "551.0", "550.0.0.45.102", "549.0", "547.0"],
    "tiktok": ["44.7.0", "44.3.0", "43.9.0", "43.5.0", "43.1.0", "42.7.0", "42.3.0"],
    "pinterest": ["14.14", "14.10", "14.5", "14.1", "13.8", "13.5", "13.2"],
    "snapchat": ["13.88.0.56", "13.85.0.51", "13.80.0.48", "13.75.0.45", "13.70.0.41", "13.65.0.38", "13.60.0.35"],
    "youtube": ["20.15.3", "20.14.2", "20.13.0", "20.12.3", "20.11.4", "20.10.2", "20.09.3"],
    "whatsapp": ["25.4.82", "25.4.78", "25.3.75", "25.3.70", "25.2.73", "25.2.68", "25.1.72"],
    "linkedin": ["9.32.512", "9.31.482", "9.30.451", "9.29.421", "9.28.395"],
    "twitter": ["10.98.0", "10.97.0", "10.96.0", "10.95.0", "10.94.0"],
    "reddit": ["2024.28.0", "2024.27.1", "2024.26.0", "2024.25.0", "2024.24.1"],
    "telegram": ["11.12.0", "11.11.0", "11.10.0", "11.9.0", "11.8.0"],
    "gsearch": ["332.0.755318947", "331.0.754842390", "330.0.752551382", "329.0.750019021", "328.0.747855320", "327.0.745210445", "326.0.742180108"],
    "gchrome": ["147.0.7727.102", "146.0.7680.177", "145.0.7600.130", "144.0.7559.63", "143.0.7637.60", "142.0.7835.13", "141.0.7390.72"],
}

APP_DISPLAY_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
    "pinterest": "Pinterest",
    "snapchat": "Snapchat",
    "youtube": "YouTube",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "gsearch": "Google Search",
    "gchrome": "Google Chrome (iOS)",
    "twitter": "Twitter/X",
    "linkedin": "LinkedIn",
    "reddit": "Reddit",
}


def detect_app(ua: str) -> Dict[str, Any]:
    """Return normalized app metadata for known browser/native UA markers."""
    text = ua or ""
    low = text.lower()
    if any(token in low for token in ("musical_ly", "trill_", "fban/tiktokandroid", "tiktok/")):
        version_match = re.search(
            r"(?:app_version|tiktok)/([\d.]+)",
            text,
            re.IGNORECASE,
        )
        if not version_match and "fban/tiktokandroid" in low:
            version_match = re.search(r"fbav/([\d.]+)", text, re.IGNORECASE)
        return {
            "app": "tiktok",
            "app_name": "TikTok",
            "app_version": version_match.group(1) if version_match else None,
            "is_inapp": True,
        }
    patterns = (
        ("instagram", r"instagram[ /]([\d.]+)"),
        ("facebook", r"fbav/([\d.]+)"),
        ("pinterest", r"pinterest/([\d.]+)"),
        ("snapchat", r"snapchat/([\d.]+)"),
        ("youtube", r"com\.google\.(?:ios|android)\.youtube/([\d.]+)"),
        ("whatsapp", r"whatsapp/([\d.]+)"),
        ("telegram", r"telegram(?:android|ios)?/([\d.]+)"),
        ("gsearch", r"gsa/([\d.]+)"),
        ("gchrome", r"crios/([\d.]+)"),
        ("twitter", r"(?:twitterandroid|twitterios|twitter for iphone)/([\d.]+)"),
        ("linkedin", r"(?:linkedinapp|com\.linkedin\.android)/([\d.]+)"),
        ("reddit", r"reddit/version\s+([\d.]+)"),
    )
    for app, pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return {
                "app": app,
                "app_name": APP_DISPLAY_NAMES[app],
                "app_version": match.group(1),
                "is_inapp": app not in {"gchrome"},
            }
    if "fb_iab" in low or "fban/fbios" in low:
        return {"app": "facebook", "app_name": "Facebook", "app_version": None, "is_inapp": True}
    return {"app": None, "app_name": "Browser", "app_version": None, "is_inapp": False}


def _platform(ua: str) -> str:
    low = (ua or "").lower()
    if any(token in low for token in ("iphone", "ipad", "cpu ios", "cfnetwork", "darwin/")):
        return "iOS"
    if "android" in low:
        return "Android"
    if "windows" in low:
        return "Windows"
    if "macintosh" in low or "mac os x" in low:
        return "macOS"
    if "linux" in low:
        return "Linux"
    return "Unknown"


def classify_user_agent(ua: str) -> Dict[str, Any]:
    """Classify UA engine/profile without conflating Cronet and WebView."""
    text = (ua or "").strip()
    low = text.lower()
    app = detect_app(text)
    platform = _platform(text)

    if "cronet/" in low:
        engine, profile_type = "cronet", "native_network"
    elif "cfnetwork/" in low or low.startswith("com.google.") or "telegramnetwork/" in low:
        engine, profile_type = "native_network", "native_network"
    elif platform == "Android" and (
        "; wv)" in low
        or "version/4.0" in low
        or (
            app["app"] in {
                "facebook", "instagram", "tiktok", "pinterest", "snapchat",
                "whatsapp", "linkedin", "twitter", "reddit", "telegram",
            }
            and "chrome/" in low
        )
    ):
        engine, profile_type = "android_webview", "android_webview"
    elif platform == "iOS" and "applewebkit/" in low:
        if "safari/" in low and not app["is_inapp"]:
            engine, profile_type = "webkit", "browser"
        else:
            engine, profile_type = "wkwebview", "ios_wkwebview"
    elif "firefox/" in low:
        engine, profile_type = "gecko", "browser"
    elif any(token in low for token in ("chrome/", "crios/", "chromium/")):
        engine, profile_type = "chromium", "browser"
    elif "safari/" in low:
        engine, profile_type = "webkit", "browser"
    else:
        engine, profile_type = "unknown", "unknown"

    runtime_compatible = profile_type in {"browser", "android_webview", "ios_wkwebview"}
    runtime = "browser_page" if runtime_compatible else "native_network"
    return {
        "platform": platform,
        "app": app["app"] or "browser",
        "app_name": app["app_name"],
        "app_version": app["app_version"],
        "engine": engine,
        "profile_type": profile_type,
        "runtime": runtime,
        "runtime_compatible": runtime_compatible,
    }


def validate_user_agent(ua: str, expected_app: Optional[str] = None) -> Dict[str, Any]:
    """Validate structural consistency for the classified engine/profile."""
    text = (ua or "").strip()
    low = text.lower()
    profile = classify_user_agent(text)
    issues = []
    warnings = []

    if not text:
        issues.append("Empty user agent.")
    elif len(text) < 25:
        issues.append("User agent is too short to identify a coherent client.")

    engine = profile["engine"]
    platform = profile["platform"]
    app = profile["app"]

    if expected_app and expected_app not in {"chrome", "browser"} and app != expected_app:
        issues.append(f"UA does not contain a recognizable {expected_app} identity marker.")

    if engine == "cronet":
        if platform != "Android":
            issues.append("Cronet identity is missing an Android platform token.")
        if "chrome/" in low or "mobile safari/" in low:
            issues.append("Cronet/native identity is mixed with Chrome WebView tokens.")
        if app == "tiktok":
            for token in ("jssdk/", "channel/", "app_version/"):
                if token not in low:
                    issues.append(f"TikTok Cronet identity is missing `{token}`.")
    elif engine == "android_webview":
        required = ("; wv)", "applewebkit/537.36", "version/4.0", "chrome/", "mobile safari/537.36")
        for token in required:
            if token not in low:
                issues.append(f"Android WebView identity is missing `{token}`.")
    elif engine == "chromium":
        if "chrome/" in low and "applewebkit/537.36" not in low:
            issues.append("Chromium identity is missing its AppleWebKit/537.36 compatibility token.")
    elif engine in {"webkit", "wkwebview"}:
        if "applewebkit/605.1.15" not in low:
            issues.append("WebKit identity is missing AppleWebKit/605.1.15.")
    elif engine == "unknown":
        issues.append("Unable to identify a coherent browser or native network engine.")

    if not profile["runtime_compatible"]:
        warnings.append(
            f"{engine} identity is a native network/API client, not an offer-page "
            "browser navigation identity."
        )

    # Region/locale coherence when both are explicitly encoded.
    region_match = re.search(r"\bRegion/([A-Z]{2})\b", text)
    locale_regions = re.findall(
        r"\b(?:ByteFullLocale|ByteLocale)/[A-Za-z]{2}[-_]([A-Z]{2})\b",
        text,
    )
    if region_match and any(region_match.group(1) != value for value in locale_regions):
        issues.append("Encoded locale region does not match the Region token.")

    return {**profile, "issues": issues, "warnings": warnings, "valid": not issues}


def client_hint_headers_for_ua(ua: str) -> Dict[str, str]:
    """Build coherent low-entropy Chromium hints; return none otherwise."""
    profile = classify_user_agent(ua)
    if profile["engine"] not in {"chromium", "android_webview"}:
        return {}
    match = re.search(r"(?:Chrome|Chromium)/(\d+)", ua or "", re.IGNORECASE)
    if not match:
        return {}
    major = match.group(1)
    platform = profile["platform"]
    mobile = "?1" if platform in {"Android", "iOS"} else "?0"
    return {
        "sec-ch-ua": f'"Chromium";v="{major}", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": mobile,
        "sec-ch-ua-platform": f'"{platform}"',
    }


def validate_header_coherence(ua: str, headers: Mapping[str, str]) -> list[str]:
    """Return contradictions between a UA profile and supplied client hints."""
    normalized = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    supplied = {k: v for k, v in normalized.items() if k.startswith("sec-ch-ua")}
    if not supplied:
        return []
    profile = classify_user_agent(ua)
    if profile["engine"] not in {"chromium", "android_webview"}:
        return [f"{profile['engine']} profiles must not receive Chrome sec-ch-ua client hints."]

    expected = client_hint_headers_for_ua(ua)
    issues = []
    for key in ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
        if key in supplied and expected.get(key) != supplied[key]:
            issues.append(f"{key} does not match the UA engine/version/platform.")
    return issues


__all__ = [
    "APP_VERSION_POOLS",
    "classify_user_agent",
    "client_hint_headers_for_ua",
    "detect_app",
    "validate_header_coherence",
    "validate_user_agent",
]
