"""Import browser profiles from AdsPower / GoLogin / Dolphin / generic JSON (v2.7.76)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _pick(d: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _normalize_proxy(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"enabled": False}
    ptype = str(_pick(raw, "proxy_type", "type", "mode", default="")).lower()
    host = _pick(raw, "host", "proxy_host", "server_host", default="")
    port = _pick(raw, "port", "proxy_port", default="")
    user = _pick(raw, "username", "user", "proxy_user", default="")
    pwd = _pick(raw, "password", "pass", "proxy_password", default="")
    server = _pick(raw, "server", "proxy", "proxy_url", default="")
    if not server and host and port:
        scheme = ptype if ptype in ("http", "https", "socks5", "socks4") else "http"
        server = f"{scheme}://{host}:{port}"
    if not server and not user:
        return {"enabled": False}
    return {
        "enabled": True,
        "server": str(server),
        "username": str(user or ""),
        "password": str(pwd or ""),
        "proxyjet_country": str(_pick(raw, "country", "proxy_country", default="US")).upper()[:2],
        "proxyjet_state": str(_pick(raw, "state", "region", default="")).upper()[:8],
    }


def _base_krexion_profile(raw: Dict[str, Any], *, vendor: str) -> Dict[str, Any]:
    name = str(_pick(raw, "name", "profile_name", "title", default="Imported Profile"))[:120]
    ua = str(_pick(raw, "user_agent", "ua", "userAgent", default=""))
    notes = str(_pick(raw, "remark", "notes", "comment", "description", default=""))[:2000]
    if vendor:
        notes = (notes + f"\n[import:{vendor}]").strip()[:2000]
    w = int(_pick(raw, "screen_width", "viewport_width", "width", default=0) or 0)
    h = int(_pick(raw, "screen_height", "viewport_height", "height", default=0) or 0)
    if not w or not h:
        vp = raw.get("viewport") or raw.get("resolution") or {}
        if isinstance(vp, dict):
            w = int(vp.get("width") or w or 1920)
            h = int(vp.get("height") or h or 1080)
        else:
            w, h = 1920, 1080
    is_mobile = bool(
        _pick(raw, "is_mobile", "mobile", default=False)
        or str(_pick(raw, "platform", "os", default="")).lower() in ("ios", "android", "mobile")
    )
    return {
        "name": name or "Imported Profile",
        "notes": notes,
        "country": str(_pick(raw, "country", "country_code", default="us")).lower()[:8],
        "user_agent": ua,
        "viewport": {"width": w, "height": h},
        "is_mobile": is_mobile,
        "has_touch": is_mobile,
        "device_type": "mobile" if is_mobile else "desktop",
        "start_url": str(_pick(raw, "start_url", "url", "homepage", default="https://www.google.com/"))[:512],
        "proxy": _normalize_proxy(raw.get("proxy") or raw.get("user_proxy_config") or raw),
        "tags": [],
        "folder": str(_pick(raw, "group_name", "folder", "group", default=""))[:80],
    }


def parse_adspower_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    prof = _base_krexion_profile(raw, vendor="adspower")
    prof["tags"] = ["import-adspower"]
    cookies = raw.get("cookie") or raw.get("cookies")
    ss = None
    if isinstance(cookies, list) and cookies:
        ss = {"cookies": cookies, "origins": []}
    elif isinstance(cookies, str) and cookies.strip().startswith("["):
        try:
            import json

            ss = {"cookies": json.loads(cookies), "origins": []}
        except Exception:
            ss = None
    if ss:
        prof["storage_state"] = ss
    return prof


def parse_gologin_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    prof = _base_krexion_profile(raw, vendor="gologin")
    prof["tags"] = ["import-gologin"]
    if raw.get("navigator"):
        nav = raw["navigator"]
        if isinstance(nav, dict) and nav.get("userAgent"):
            prof["user_agent"] = str(nav["userAgent"])
    ss = raw.get("storage") or raw.get("storage_state")
    if isinstance(ss, dict):
        prof["storage_state"] = ss
    return prof


def parse_dolphin_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    prof = _base_krexion_profile(raw, vendor="dolphin")
    prof["tags"] = ["import-dolphin"]
    return prof


def detect_vendor_and_parse(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    keys = set(str(k).lower() for k in raw.keys())
    if "serial_number" in keys or "user_proxy_config" in keys or raw.get("domain_name"):
        return parse_adspower_profile(raw)
    if "navigator" in keys and ("os" in keys or "webgl" in keys):
        return parse_gologin_profile(raw)
    if "platformName" in keys or raw.get("mainWebsite"):
        return parse_dolphin_profile(raw)
    if raw.get("user_agent") or raw.get("name"):
        return _base_krexion_profile(raw, vendor="generic")
    return None


def parse_vendor_import_payload(data: Any) -> List[Dict[str, Any]]:
    """Accept array, {profiles:[]}, AdsPower {data:{list:[]}}, GoLogin list, etc."""
    candidates: List[Dict[str, Any]] = []
    if isinstance(data, list):
        candidates = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        if isinstance(data.get("profiles"), list):
            candidates = [x for x in data["profiles"] if isinstance(x, dict)]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("list"), list):
            candidates = [x for x in data["data"]["list"] if isinstance(x, dict)]
        elif isinstance(data.get("list"), list):
            candidates = [x for x in data["list"] if isinstance(x, dict)]
        else:
            candidates = [data]
    out: List[Dict[str, Any]] = []
    for raw in candidates:
        parsed = detect_vendor_and_parse(raw)
        if parsed:
            out.append(parsed)
    return out
