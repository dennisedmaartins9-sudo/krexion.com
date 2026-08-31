"""Profile health score for Browser Profiles UI (v2.7.76)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


def compute_profile_health(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return health summary: level (good|warn|bad|unknown), score 0-100, issues[].
    Uses fields already on the profile document — no extra probes.
    """
    issues: List[str] = []
    score = 100
    status = str(doc.get("status") or "idle").lower()
    proxy = doc.get("proxy") or {}
    proxy_enabled = bool(
        proxy.get("enabled")
        or proxy.get("server")
        or proxy.get("provider_id")
        or proxy.get("use_proxyjet")
    )
    ss = doc.get("storage_state") or {}
    if not ss and doc.get("storage_state_stats"):
        ss = {
            "cookies": [{}] * int(doc["storage_state_stats"].get("cookie_count") or 0),
        }
    cookie_count = len(ss.get("cookies") or [])
    if doc.get("storage_state_stats"):
        cookie_count = max(
            cookie_count,
            int(doc["storage_state_stats"].get("cookie_count") or 0),
        )
    last_proxy = doc.get("last_proxy_check") or {}
    exit_ip = str(doc.get("exit_ip") or proxy.get("exit_ip") or "").strip()
    fp = str(doc.get("fingerprint_hash") or doc.get("fingerprint_short") or "").strip()
    tls_ok = doc.get("last_tls_prewarm_ok")

    if status == "error":
        score -= 40
        issues.append("last launch error")
    elif status in ("running", "launching", "queued", "stopping"):
        score -= 0  # active is fine

    if proxy_enabled:
        if last_proxy.get("ok") is False or last_proxy.get("error"):
            score -= 35
            issues.append("proxy check failed")
        elif not exit_ip and not (last_proxy.get("ip") or last_proxy.get("exit_ip")):
            score -= 15
            issues.append("proxy not verified")
    else:
        score -= 5
        issues.append("no proxy configured")

    if cookie_count <= 0:
        score -= 20
        issues.append("no cookies saved")
    elif cookie_count < 5:
        score -= 8
        issues.append("few cookies")

    if not fp:
        score -= 10
        issues.append("fingerprint not set")

    if tls_ok is False or tls_ok == "fail":
        score -= 12
        issues.append("TLS prewarm failed")

    fraud = last_proxy.get("fraud_score")
    if fraud is not None:
        try:
            fs = float(fraud)
            if fs >= 75:
                score -= 25
                issues.append(f"high fraud score ({int(fs)})")
            elif fs >= 50:
                score -= 10
                issues.append(f"elevated fraud score ({int(fs)})")
        except (TypeError, ValueError):
            pass

    score = max(0, min(100, score))
    if score >= 75:
        level = "good"
    elif score >= 45:
        level = "warn"
    elif issues:
        level = "bad"
    else:
        level = "unknown"

    return {
        "level": level,
        "score": score,
        "issues": issues[:6],
        "cookie_count": cookie_count,
        "proxy_ok": (
            None
            if not proxy_enabled
            else bool(last_proxy.get("ok") is not False and not last_proxy.get("error"))
        ),
    }


def format_last_used(iso: str) -> str:
    if not iso:
        return ""
    try:
        from datetime import datetime, timezone

        raw = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        sec = int((datetime.now(timezone.utc) - dt).total_seconds())
        if sec < 60:
            return "just now"
        if sec < 3600:
            return f"{sec // 60}m ago"
        if sec < 86400:
            return f"{sec // 3600}h ago"
        if sec < 604800:
            return f"{sec // 86400}d ago"
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(iso)[:16]
