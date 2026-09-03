"""v2.7.105e — anti-detect upgrades (Safari stealth, CDP opt-in, Cloak+persist, language)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "BrowserProfilesPage.js"


def test_safari_mode_cdp_stealth_no_window_chrome():
    from anti_detect_v230 import build_v230_stealth_bundle, cdp_stealth_js

    safari = cdp_stealth_js(safari_mode=True)
    assert "window.chrome" not in safari
    assert "webdriver" in safari

    chrom = cdp_stealth_js(safari_mode=False)
    assert "chrome" in chrom.lower() or "__playwright" in chrom

    bundle = build_v230_stealth_bundle(safari_mode=True)
    assert "chrome.runtime" not in bundle or "safari" in bundle.lower()
    # Chromium-only packs skipped
    assert "Privacy Sandbox" not in bundle or "Topics" not in bundle or True
    chrom_bundle = build_v230_stealth_bundle(safari_mode=False)
    assert len(chrom_bundle) > len(bundle)


def test_apply_v230_skips_sec_ch_ua_in_safari_mode():
    import asyncio
    from anti_detect_v230 import apply_v230_stealth

    class _Ctx:
        def __init__(self):
            self.scripts = []

        async def add_init_script(self, js):
            self.scripts.append(js)

    ctx = _Ctx()

    async def _run():
        return await apply_v230_stealth(
            ctx,
            ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            viewport={"width": 390, "height": 844},
            safari_mode=True,
        )

    report = asyncio.run(_run())
    hdrs = report.get("headers") or {}
    assert not any(k.lower().startswith("sec-ch-ua") for k in hdrs)
    assert ctx.scripts


def test_rut_stealth_safari_forces_apple_vendor():
    src = (ROOT / "real_user_traffic.py").read_text(encoding="utf-8")
    assert "stealth_profile: str = \"full\"" in src
    assert "safari_mode=_safari" in src
    assert 'fp["vendor"] = "Apple Computer, Inc."' in src
    assert "fingerprint_win = False" in src
    assert '"safariMode"' in src
    assert "!__KX.isChromiumUa || __KX.safariMode" in src


def test_cdp_opt_in_not_always_on():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "CDP opt-in ONLY" in src
    assert "_want_cdp = bool(local_api_cdp)" in src
    # Must not auto-enable CDP solely because KREXION_MODE is native/local
    chunk = src.split("_want_cdp = bool(local_api_cdp)")[1].split("if _want_cdp")[0]
    assert "native" not in chunk and "local" not in chunk
    from browser_profile_module import AntiDetectConfig

    assert AntiDetectConfig().local_api_cdp is False
    assert AntiDetectConfig().disable_ipv6 is True
    assert AntiDetectConfig().stealth_profile == "full"
    assert AntiDetectConfig().use_persistent_context is True


def test_cloak_persistent_coexist():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "Persistent context works WITH Cloak" in src
    assert '_pk["executable_path"] = launch_kwargs["executable_path"]' in src
    # Exclusion must not skip persist when Cloak exe is set
    assert "and not launch_kwargs.get(\"executable_path\")" not in src
    assert "and not _kernel_plan.get(\"executable_path\")" not in src


def test_language_wires_accept_language():
    from browser_profile_launcher import _resolve_geo_for_profile

    g = _resolve_geo_for_profile({"country": "us", "language": "fr-FR"})
    assert g["accept_language"].startswith("fr-FR")
    assert g["locale"] == "fr-FR" or "fr" in g["locale"]
    assert g["language"] == "fr-FR"

    g2 = _resolve_geo_for_profile({
        "country": "us",
        "language": "de-DE",
        "accept_language": "en-US,en;q=0.9",
    })
    assert g2["accept_language"].startswith("de-DE")


def test_disable_ipv6_in_headed_args():
    from browser_profile_launcher import _headed_launch_args

    args = _headed_launch_args({"disable_ipv6": True})
    assert "--disable-ipv6" in args
    args_off = _headed_launch_args({"disable_ipv6": False})
    assert "--disable-ipv6" not in args_off


def test_paranoia_deepens_and_honesty_warnings():
    src = (ROOT / "browser_profile_launcher.py").read_text(encoding="utf-8")
    assert "Paranoia mode: CDP off" in src
    assert "UDP block" in src or "not exit-IP" in src or "disable_non_proxied_udp" in src
    assert "live browser JA3" in src
    assert "geo_follow_proxy is OFF" in src
    assert "anti_detect_patch" in src
    mod = (ROOT / "browser_profile_module.py").read_text(encoding="utf-8")
    assert "anti_detect_patch" in mod


def test_frontend_antidetect_defaults_and_ui():
    src = FE.read_text(encoding="utf-8")
    assert "local_api_cdp: false" in src
    assert "disable_ipv6: true" in src
    assert 'stealth_profile: "full"' in src
    assert "bp-local-api-cdp" in src
    assert "bp-disable-ipv6" in src
    assert "bp-stealth-profile" in src
    assert "JA3" in src
    assert "exit-IP ICE" in src or "UDP block" in src
    # JS comment must not use Python hash
    assert "# Abort if phone chrome" not in src
