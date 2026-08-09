"""Shared user-agent profile, validation, and client-hint coherence contract.

The contract describes what a UA claims to be.  It does not add headers to
requests and it deliberately distinguishes browser engines from native
network stacks such as Cronet and CFNetwork.
"""
from __future__ import annotations

import re
from threading import RLock
from typing import Any, Dict, Mapping, Optional


# Audited release records.  A record is intentionally more precise than a
# version pool: build/package values are only present when they were observed
# with that exact version.  This is a compatibility contract, not a claim that
# any release is current or that a syntactically valid UA is genuine.
APP_RELEASES_BY_PLATFORM = {
    "instagram": {
        "android": [{"version": "437.0.0.33.78", "version_code": "1011909233"}],
        "ios": [{"version": value} for value in ("425.0.0", "422.0.0", "418.0.0")],
    },
    "facebook": {
        "android": [{"version": "556.0.0.59.68", "build": "681204512"}],
        "ios": [{"version": value} for value in ("557.0", "555.0", "553.0")],
    },
    "tiktok": {
        "android": [
            {"version": "46.4.1", "version_code": "2024604010"},
            {"version": "46.3.3", "version_code": "2024603030"},
            {"version": "45.8.2", "version_code": "2024508020"},
        ],
        "ios": [{"version": value} for value in ("44.7.0", "44.3.0", "43.9.0")],
    },
    "pinterest": {
        "android": [{"version": value} for value in ("14.14", "14.10", "14.5")],
        "ios": [{"version": value} for value in ("14.14", "14.10", "14.5")],
    },
    "snapchat": {
        "android": [{"version": value} for value in ("13.88.0.56", "13.85.0.51")],
        "ios": [{"version": value} for value in ("13.88.0.56", "13.85.0.51")],
    },
    "youtube": {
        "android": [{"version": "20.15.3"}],
        "ios": [{"version": "20.15.3"}],
    },
    "whatsapp": {
        "android": [{"version": "2.26.5.10"}],
        "ios": [{"version": value} for value in ("25.4.82", "25.4.78")],
    },
    "linkedin": {
        "android": [{"version": "2.286.33", "package_build": "212600"}],
        "ios": [{"version": value} for value in ("9.32.512", "9.31.482")],
    },
    "twitter": {
        "android": [{"version": "11.95.1"}],
        "ios": [{"version": value} for value in ("10.98.0", "10.97.0")],
    },
    "reddit": {
        "android": [{"version": "2026.18.0", "build": "2618090"}],
        "ios": [{"version": value} for value in ("2024.28.0", "2024.27.1")],
    },
    "telegram": {
        "android": [{"version": "12.9.2"}],
        "ios": [{"version": value} for value in ("11.12.0", "11.11.0")],
    },
    "gsearch": {
        "android": [{"version": "17.36.15"}],
        "ios": [{"version": "332.0.755318947"}],
    },
    "gchrome": {
        "android": [{"version": "147.0.7727.102"}],
        "ios": [{"version": "147.0.7727.102"}],
    },
}

# Browser-wrapper evidence was not established for these combinations.  They
# remain usable as explicit generic-browser fallbacks, but must not be
# represented as verified app identities.
APP_SUPPORT_MATRIX = {
    app: {
        platform: "supported"
        for platform in ("android", "ios")
    }
    for app in APP_RELEASES_BY_PLATFORM
}
APP_SUPPORT_MATRIX["youtube"] = {"android": "fallback", "ios": "fallback"}
APP_SUPPORT_MATRIX["whatsapp"]["ios"] = "fallback"
APP_SUPPORT_MATRIX["reddit"]["ios"] = "fallback"
APP_SUPPORT_MATRIX["telegram"]["ios"] = "fallback"
APP_SUPPORT_MATRIX["gchrome"]["android"] = "fallback"


# Capture-backed Android firmware identities.  Exact model/OS/build tuples are
# the only Android firmware combinations this contract verifies.  Hardware
# fields are intentionally absent where a capture did not establish them.
ANDROID_DEVICE_SNAPSHOTS = (
    {"brand": "Google", "model": "Pixel 7", "and_ver": "13", "sdk": "33",
     "build": "TQ3A.230805.001", "vendor": "google", "chipset": "tensor",
     "soc": "panther", "res": "1080x2400", "dpi": "420dpi"},
    {"brand": "Google", "model": "Pixel 8", "and_ver": "14", "sdk": "34",
     "build": "AP1A.240505.005", "vendor": "google", "chipset": "tensor",
     "soc": "shiba", "res": "1080x2400", "dpi": "420dpi"},
    {"brand": "Google", "model": "Pixel 8", "and_ver": "16", "sdk": "36",
     "build": "CP1A.260505.005", "vendor": "google", "chipset": "tensor",
     "soc": "shiba", "res": "1080x2400", "dpi": "420dpi"},
    {"brand": "Google", "model": "Pixel 9", "and_ver": "15", "sdk": "35",
     "build": "AP3A.240905.015", "vendor": "google", "chipset": "tensor",
     "soc": "tokay", "res": "1080x2424", "dpi": "422dpi"},
    {"brand": "Google", "model": "Pixel 9", "and_ver": "16", "sdk": "36",
     "build": "CP1A.260505.005", "vendor": "google", "chipset": "tensor",
     "soc": "tokay", "res": "1080x2424", "dpi": "422dpi"},
    {"brand": "Xiaomi", "model": "2510ERA8BG", "and_ver": "16", "sdk": "36",
     "build": "BP2A.250605.031.A3", "vendor": "Xiaomi"},
)

_RELEASE_CONTRACT_LOCK = RLock()


def replace_verified_app_releases(
    app: str,
    platform: str,
    records: list[Mapping[str, Any]],
) -> None:
    """Atomically replace trusted in-process release records.

    Callers must only pass records fetched directly from a trusted release
    provider. Persisted snapshots are not verification authorities.
    """
    normalized = [
        {str(key): str(value) for key, value in record.items()}
        for record in records
        if record.get("version")
    ]
    if app not in APP_RELEASES_BY_PLATFORM or platform not in {"android", "ios"}:
        raise ValueError("Unknown app release contract target.")
    with _RELEASE_CONTRACT_LOCK:
        APP_RELEASES_BY_PLATFORM[app][platform] = normalized
        APP_VERSION_POOLS[app] = _compatibility_versions(app)


def _compatibility_versions(app: str) -> list[str]:
    """Flatten platform records for legacy callers without losing ordering."""
    versions = []
    for platform in ("android", "ios"):
        for record in APP_RELEASES_BY_PLATFORM[app][platform]:
            if record["version"] not in versions:
                versions.append(record["version"])
    return versions


# Backwards-compatible shape used by server.py and older integrations.
APP_VERSION_POOLS = {
    app: _compatibility_versions(app)
    for app in APP_RELEASES_BY_PLATFORM
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


def _collect_app_identities(ua: str) -> list[Dict[str, Any]]:
    """Collect every distinct app identity, preserving its first UA position."""
    text = ua or ""
    evidence: Dict[str, Dict[str, Any]] = {}

    def add(app: str, marker: str, match: re.Match[str], version: Optional[str] = None) -> None:
        item = evidence.setdefault(
            app,
            {"app": app, "version": None, "position": match.start(), "markers": []},
        )
        item["position"] = min(item["position"], match.start())
        item["markers"].append({"type": marker, "value": match.group(0), "position": match.start()})
        if version and not item["version"]:
            item["version"] = version

    # TikTok's FB_IAB trailer is part of TikTok, not a Facebook identity.
    for marker, pattern in (
        ("tiktok", r"\bTikTok/([\d.]+)"),
        ("app_version", r"\bapp_version/([\d.]+)"),
        ("musical_ly", r"\b(?:musical_ly|trill)_([\d.]+)"),
        ("tiktok_fban", r"\bFBAN/TikTokAndroid\b"),
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            version = match.group(1) if match.lastindex else None
            if marker == "musical_ly" and version and "." not in version:
                version = None
            add("tiktok", marker, match, version)

    for match in re.finditer(r"\[(?:FB_IAB|FBAN)/[^\]]+\]", text, re.IGNORECASE):
        block = match.group(0)
        if re.search(r"(?:FB4A|FBIOS|MESSENGER)", block, re.IGNORECASE):
            version = re.search(r"\bFBAV/([\d.]+)", block, re.IGNORECASE)
            add("facebook", "facebook_block", match, version.group(1) if version else None)

    patterns = (
        ("instagram", "instagram", r"\bInstagram[ /]([\d.]+)"),
        ("pinterest", "pinterest_version", r"\bPinterest/([\d.]+)"),
        ("pinterest", "pinterest_bracket", r"\[Pinterest/(?:Android|iOS)\]"),
        ("snapchat", "snapchat", r"\bSnapchat/([\d.]+)"),
        ("youtube", "youtube", r"\bcom\.google\.(?:ios|android)\.youtube/([\d.]+)"),
        ("whatsapp", "whatsapp", r"\bWhatsApp/([\d.]+)"),
        ("telegram", "telegram", r"\bTelegram(?:-Android|Android|-iOS|IOS)?/([\d.]+)"),
        ("gsearch", "gsa", r"\bGSA/([\d.]+)"),
        ("gsearch", "google_app", r"\bGoogleApp/([\d.]+)"),
        ("gchrome", "crios", r"\bCriOS/([\d.]+)"),
        ("twitter", "twitter", r"\b(?:TwitterAndroid|TwitterIOS|Twitter for iPhone)/([\d.]+)"),
        ("linkedin", "linkedin_app", r"(?:\[LinkedInApp\]|LinkedInApp)/([\d.]+)"),
        ("linkedin", "linkedin_package", r"\bcom\.linkedin\.android/(\d+)"),
        ("reddit", "reddit", r"\bReddit/Version\s+([\d.]+)"),
    )
    for app, marker, pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            add(app, marker, match, match.group(1) if match.lastindex else None)

    return sorted(evidence.values(), key=lambda item: item["position"])


def detect_app(ua: str) -> Dict[str, Any]:
    """Return primary metadata plus all identities found in the UA."""
    found = _collect_app_identities(ua)
    identities = [item["app"] for item in found]
    if not found:
        return {
            "app": None,
            "app_name": "Browser",
            "app_version": None,
            "is_inapp": False,
            "identities": [],
            "identity_details": [],
        }
    primary = found[0]
    app = primary["app"]
    return {
        "app": app,
        "app_name": APP_DISPLAY_NAMES[app],
        "app_version": primary["version"],
        "is_inapp": app != "gchrome",
        "identities": identities,
        "identity_details": found,
    }


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


def _support_state(app: Optional[str], platform: str) -> str:
    if not app or app == "browser":
        return "generic"
    return APP_SUPPORT_MATRIX.get(app, {}).get(platform.lower(), "unknown")


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
        "identities": app["identities"],
        "identity_details": app["identity_details"],
        "support_state": _support_state(app["app"], platform),
        "identity_supported": _support_state(app["app"], platform) == "supported",
        "engine": engine,
        "profile_type": profile_type,
        "runtime": runtime,
        "runtime_compatible": runtime_compatible,
    }


def validate_user_agent(
    ua: str,
    expected_app: Optional[str] = None,
    require_verified_device: bool = False,
) -> Dict[str, Any]:
    """Validate engine structure, marker uniqueness, and release semantics."""
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
    expected = (expected_app or "").lower() or None
    if expected == "chrome":
        expected = "browser"
    expected_support = _support_state(expected, platform)
    if expected and expected != "browser" and app != expected:
        if app == "browser" and expected_support == "fallback":
            warnings.append(
                f"{APP_DISPLAY_NAMES.get(expected, expected)} {platform} has no verified "
                "browser-UA identity; accepting the generic browser fallback."
            )
        else:
            issues.append(f"UA does not contain a recognizable {expected} identity marker.")
    elif expected == "browser" and app not in {"browser", "gchrome"}:
        issues.append("UA contains an app identity where a generic browser was expected.")

    identities = profile["identities"]
    if len(identities) > 1:
        issues.append(
            "UA contains multiple foreign app identities: " + ", ".join(identities) + "."
        )
    for detail in profile["identity_details"]:
        marker_types = [marker["type"] for marker in detail["markers"]]
        duplicates = sorted({marker for marker in marker_types if marker_types.count(marker) > 1})
        if duplicates:
            issues.append(
                f"UA contains duplicate {detail['app']} marker blocks: "
                + ", ".join(duplicates) + "."
            )

    if re.search(r"\biPhone\b", text, re.IGNORECASE) and re.search(
        r"\biPad\b", text, re.IGNORECASE
    ):
        issues.append("UA contains incompatible iPhone and iPad device claims.")
    if re.search(r"\(iPad;\s*CPU iPhone OS\b", text, re.IGNORECASE) or re.search(
        r"\(iPhone;\s*CPU iPad OS\b", text, re.IGNORECASE
    ):
        issues.append("UA device token and CPU OS family are incompatible.")

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

    # Verify OEM firmware only against exact capture-backed tuples. Generic
    # AOSP prefix rules produce false failures for valid OEM firmware.
    android_os_match = re.search(r"\bAndroid\s+(\d+)", text, re.IGNORECASE)
    android_build_match = re.search(
        r"\bBuild/([A-Za-z0-9._-]+)",
        text,
        re.IGNORECASE,
    )
    if android_os_match and android_build_match:
        os_major = android_os_match.group(1)
        build = android_build_match.group(1)
        between = text[android_os_match.end():android_build_match.start()]
        model_parts = [
            part.strip(" ();")
            for part in between.split(";")
            if part.strip(" ();")
        ]
        model = next(
            (
                part for part in reversed(model_parts)
                if not re.fullmatch(r"[A-Za-z]{1,3}[_-][A-Za-z]{2}", part)
                and part.lower() not in {"u", "wv"}
            ),
            "",
        )
        known_for_model = [
            snapshot for snapshot in ANDROID_DEVICE_SNAPSHOTS
            if snapshot["model"].lower() == model.lower()
        ]
        if known_for_model:
            if not any(
                snapshot["and_ver"] == os_major and snapshot["build"] == build
                for snapshot in known_for_model
            ):
                message = (
                    "Android model/OS/build tuple does not match a verified "
                    "device snapshot."
                )
                (issues if require_verified_device else warnings).append(message)
        else:
            warnings.append(
                "Android build could not be verified: device model is missing "
                "or is not in the capture-backed snapshot contract."
            )

    release_platform = platform.lower()
    releases = APP_RELEASES_BY_PLATFORM.get(app, {}).get(release_platform, [])
    support_state = _support_state(app, platform)
    if app != "browser" and support_state == "fallback":
        warnings.append(
            f"{profile['app_name']} {platform} browser identity is fallback-only; "
            "no verified browser-UA evidence is claimed."
        )
    elif app != "browser" and support_state == "supported" and releases:
        if app == "pinterest":
            expected_bracket = (
                r"\[Pinterest/Android\]"
                if platform == "Android"
                else r"\[Pinterest/iOS\]"
            )
            if not re.search(expected_bracket, text, re.IGNORECASE):
                issues.append(f"Pinterest {platform} requires its verified bracket marker.")
            if re.search(r"\bPinterest/[\d.]+", text, re.IGNORECASE):
                issues.append("Pinterest UA contains an unsupported app-version suffix.")
            release = releases[0]
        else:
            release = next(
                (record for record in releases if record["version"] == profile["app_version"]),
                None,
            )
        if release is None:
            issues.append(
                f"{profile['app_name']} {platform} version is not in the verified release contract."
            )
        elif app == "instagram" and platform == "Android":
            code = re.search(r";\s*(\d{8,12});\s*IABMV/", text, re.IGNORECASE)
            if not code or code.group(1) != release["version_code"]:
                issues.append("Instagram Android version_code does not match its release.")
        elif app == "facebook" and platform == "Android":
            blocks = re.findall(r"\[FB_IAB/FB4A;[^\]]+\]", text, re.IGNORECASE)
            if len(blocks) != 1:
                issues.append("Facebook Android requires exactly one FB4A bracket block.")
            else:
                versions = re.findall(r"\bFBAV/([\d.]+)", blocks[0], re.IGNORECASE)
                builds = re.findall(r"\bFBBV/(\d+)", blocks[0], re.IGNORECASE)
                if len(versions) != 1 or len(versions[0].split(".")) != 5:
                    issues.append("Facebook Android FBAV must be one full five-part version.")
                if builds != [release["build"]]:
                    issues.append("Facebook Android FBBV does not match its release.")
        elif app == "tiktok" and platform == "Android":
            if "fban/tiktokandroid" in low or re.search(
                r"\[FB_IAB/[^\]]*TikTokAndroid", text, re.IGNORECASE
            ):
                issues.append("TikTok Android must not contain a Facebook-shaped identity bracket.")
            human_versions = (
                re.findall(r"\bTikTok/([\d.]+)", text, re.IGNORECASE)
                + re.findall(r"\bapp_version/([\d.]+)", text, re.IGNORECASE)
            )
            tiktok_blocks = re.findall(
                r"\[(?:FB_IAB|FBAN)/[^\]]*FBAN/TikTokAndroid[^\]]*\]",
                text,
                re.IGNORECASE,
            )
            human_versions += [
                version
                for block in tiktok_blocks
                for version in re.findall(r"\bFBAV/([\d.]+)", block, re.IGNORECASE)
            ]
            build_values = (
                re.findall(r"\bmusical_ly_(\d+)", text, re.IGNORECASE)
                + re.findall(r"\bcom\.zhiliaoapp\.musically/(\d+)", text, re.IGNORECASE)
                + [
                    value
                    for block in tiktok_blocks
                    for value in re.findall(r"\bFBBV/(\d+)", block, re.IGNORECASE)
                ]
            )
            if not human_versions or any(value != release["version"] for value in human_versions):
                issues.append("TikTok human version fields conflict with the release.")
            if not build_values or any(value != release["version_code"] for value in build_values):
                issues.append("TikTok build/package fields conflict with the release.")
        elif app == "linkedin" and platform == "Android":
            marker = re.search(r"\[LinkedInApp\]/([\d.]+)", text, re.IGNORECASE)
            package = re.search(r"\bcom\.linkedin\.android/(\d+)", text, re.IGNORECASE)
            if not marker or marker.group(1) != release["version"]:
                issues.append("LinkedIn Android requires a valid [LinkedInApp]/version marker.")
            if not package or package.group(1) != release["package_build"]:
                issues.append("LinkedIn Android package build does not match its release.")
        elif app == "twitter":
            valid_twitter = (
                r"\bTwitterAndroid/[\d.]+\b"
                if platform == "Android"
                else r"\bTwitter for iPhone/[\d.]+\b"
            )
            if not re.search(valid_twitter, text, re.IGNORECASE):
                issues.append(f"Malformed Twitter {platform} identity format.")
        elif app == "reddit" and platform == "Android":
            reddit_build = re.search(r"/Build\s+(\d+)", text, re.IGNORECASE)
            if not reddit_build or reddit_build.group(1) != release["build"]:
                issues.append("Reddit Android build does not match its release.")
        elif app == "telegram" and platform == "Android":
            if not re.search(r"\bTelegram-Android/[\d.]+\b", text, re.IGNORECASE):
                issues.append("Telegram Android identity must use Telegram-Android/version.")

    if not profile["runtime_compatible"]:
        warnings.append(
            f"{engine} identity is a native network/API client, not an offer-page "
            "browser navigation identity."
        )

    # TikTok locale semantics: ByteLocale is the language token while
    # ByteFullLocale is a POSIX locale whose region must match Region.
    region_match = re.search(r"\bRegion/([A-Z]{2})\b", text)
    byte_locale = re.search(r"\bByteLocale/([A-Za-z]{2})(?:[-_][A-Z]{2})?\b", text)
    full_locale = re.search(r"\bByteFullLocale/([A-Za-z]{2})_([A-Z]{2})\b", text)
    if byte_locale and re.search(r"[-_]", byte_locale.group(0).split("/", 1)[1]):
        issues.append("ByteLocale must contain a language token, not a full locale.")
    if "bytefulllocale/" in low and not full_locale:
        issues.append("ByteFullLocale must use a full POSIX language_REGION locale.")
    if (
        region_match
        and full_locale
        and region_match.group(1) != full_locale.group(2)
    ):
        issues.append("Encoded locale region does not match the Region token.")

    result_support = expected_support if app == "browser" and expected_support == "fallback" else support_state
    return {
        **profile,
        "support_state": result_support,
        "identity_supported": result_support == "supported",
        "expected_support_state": expected_support if expected else None,
        "issues": issues,
        "warnings": warnings,
        "valid": not issues,
    }


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
    product = "Android WebView" if profile["engine"] == "android_webview" else "Google Chrome"
    return {
        "sec-ch-ua": (
            f'"{product}";v="{major}", "Chromium";v="{major}", '
            '"Not=A?Brand";v="24"'
        ),
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
        if key not in supplied:
            issues.append(f"{key} is required for this Chromium profile.")
        elif expected.get(key) != supplied[key]:
            issues.append(f"{key} does not match the UA engine/version/platform.")
    for key in sorted(set(supplied) - set(expected)):
        issues.append(f"{key} is not part of the profile-correct low-entropy hints.")
    return issues


__all__ = [
    "APP_RELEASES_BY_PLATFORM",
    "APP_SUPPORT_MATRIX",
    "APP_VERSION_POOLS",
    "ANDROID_DEVICE_SNAPSHOTS",
    "classify_user_agent",
    "client_hint_headers_for_ua",
    "detect_app",
    "replace_verified_app_releases",
    "validate_header_coherence",
    "validate_user_agent",
]
