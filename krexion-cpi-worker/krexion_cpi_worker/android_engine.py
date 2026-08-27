"""Android install engine — orchestrates one CPI install on one device."""
from __future__ import annotations

import asyncio
import logging
import random
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .adb import ADB
from .behavior import random_pre_install_delay, simulate_session
from .fingerprint import make_fingerprint
from .config import AndroidConfig, WorkflowConfig

logger = logging.getLogger("cpi.android")


def _classify_android_type(serial: str, model: str = "") -> str:
    """Map ADB serial → device_type (real / emulator flavors / cloud)."""
    s = (serial or "").strip().lower()
    m = (model or "").lower()
    # Network ADB (host:port)
    if s.count(":") == 1 and s.split(":")[-1].isdigit():
        host = s.split(":")[0]
        if host in ("127.0.0.1", "localhost", "0.0.0.0") or host.startswith("10.0.2."):
            if "ldplayer" in m or "leidian" in m:
                return "android_ldplayer"
            if "genymotion" in m or "vbox" in m:
                return "android_genymotion"
            if "bluestacks" in m:
                return "android_bluestacks"
            return "android_emulator"
        # Remote host:port → treat as cloud ARM / partner tunnel
        return "android_cloud"
    # Local emulator serials (emulator-5554)
    if s.startswith("emulator-"):
        return "android_emulator"
    if any(x in m for x in ("sdk_gphone", "google_sdk", "emulator", "android sdk")):
        return "android_emulator"
    if "ldplayer" in m or "leidian" in m:
        return "android_ldplayer"
    if "genymotion" in m:
        return "android_genymotion"
    return "android_real"


class AndroidEngine:
    def __init__(self, adb: ADB, cfg: AndroidConfig, wf: WorkflowConfig):
        self.adb = adb
        self.cfg = cfg
        self.wf = wf

    async def ensure_emulator_connections(self) -> None:
        """Auto-connect configured local emulator + cloud ADB endpoints."""
        endpoints: List[str] = []
        for ep in list(self.cfg.emulator_endpoints or []) + list(self.cfg.cloud_adb_endpoints or []):
            ep = str(ep or "").strip()
            if ep and ep not in endpoints:
                endpoints.append(ep)
        if not endpoints:
            return
        for ep in endpoints:
            try:
                ok = await self.adb.connect(ep)
                logger.info(f"adb connect {ep}: {'ok' if ok else 'fail'}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"adb connect {ep} error: {e}")

    # ── Discovery ──────────────────────────────────────────
    async def discover(self) -> List[Dict[str, str]]:
        if self.cfg.prefer_emulator or self.cfg.emulator_endpoints or self.cfg.cloud_adb_endpoints:
            await self.ensure_emulator_connections()
        devs = await self.adb.devices()
        result = []
        for d in devs:
            if d["state"] != "device":
                continue
            if self.cfg.serial_allowlist and d["serial"] not in self.cfg.serial_allowlist:
                continue
            info = await self.adb.get_device_info(d["serial"])
            model = info.get("ro.product.model") or d.get("model") or "Android"
            d_type = _classify_android_type(d["serial"], model)
            # v2.7.19 — white-label: customer only sees Krexion Android
            if d_type.startswith("android_") and d_type not in ("android_real",):
                if d_type != "android_cloud":
                    d_type = "android_krexion"
                    model = "Krexion Android"
                else:
                    model = "Krexion Cloud Android"
            result.append({
                "serial": d["serial"],
                "device_id": d["serial"],
                "device_type": d_type,
                "model": model,
                "os_version": f"Android {info.get('ro.build.version.release', '?')}",
            })
        return result

    async def execute_action(self, serial: str, action: Dict[str, Any]) -> Dict[str, Any]:
        """Handle queued needs_action from backend (open_url / install_apk)."""
        atype = str((action or {}).get("type") or "").strip().lower()
        if atype == "open_url":
            url = str(action.get("url") or "").strip()
            if not url.startswith("http"):
                return {"ok": False, "error": "invalid url"}
            ok = await self.adb.open_url(serial, url)
            return {"ok": bool(ok), "type": atype, "url": url}
        if atype in ("install_apk", "install"):
            apk_url = str(action.get("apk_url") or action.get("url") or "").strip()
            if not apk_url.startswith("http"):
                return {"ok": False, "error": "apk_url required"}
            ok, detail = await self.adb.install_remote_url(serial, apk_url)
            package = str(action.get("package_name") or "").strip()
            if ok and package:
                try:
                    await self.adb.start_app(serial, package)
                except Exception:
                    pass
            return {"ok": bool(ok), "type": atype, "detail": str(detail)[:200], "package": package}
        return {"ok": False, "error": f"unknown action type: {atype}"}

    # ── Per-install workflow ───────────────────────────────
    async def execute_install(
        self,
        serial: str,
        attempt: Dict[str, Any],
        job: Dict[str, Any],
        offer: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], List[Dict[str, Any]], float]:
        steps: List[Dict[str, Any]] = []
        t0 = time.time()
        click_id = f"rf_{int(t0)}_{random.randint(1000,9999)}"
        attempt["_click_id"] = click_id

        def step(name: str, ok: bool = True, **kw):
            steps.append({"name": name, "ok": ok, "ts": time.time() - t0, **kw})

        proxy = attempt.get("proxy_used")
        ua = attempt.get("ua_used") or ""
        package = offer.get("package_name") or ""
        apk_url = offer.get("apk_url") or ""
        tracker_url = offer.get("tracker_url") or ""
        geo = (offer.get("geo") or "").split(",")[0].strip() or "US"

        try:
            # 1) Reset state — AGGRESSIVE fresh-install (porana app khatam, GAID reset)
            #    Even if `package` is empty in offer, kill browsers so click step
            #    does not leave Chrome foreground stealing later behavior.
            await self.adb.kill_browsers(serial)
            if package:
                await self.adb.force_stop(serial, package)
                await self.adb.clear_app_data(serial, package)
                await self.adb.uninstall(serial, package)
                # Verify uninstall — if app remains, retry with -k flag removed
                try:
                    rc, out = await self.adb.shell(serial, f"pm list packages {package}")
                    if package in out:
                        await self.adb.shell(serial, f"pm uninstall --user 0 {package}")
                except Exception:  # noqa: BLE001
                    pass
            # Reset advertising id (fresh GAID for every attempt)
            try:
                await self.adb.shell(serial, "settings delete secure advertising_id")
            except Exception:  # noqa: BLE001
                pass
            # Snapshot installed packages — used to auto-detect package after install
            pre_install_pkgs = set()
            try:
                pre_install_pkgs = await self.adb.list_user_packages(serial)
            except Exception:  # noqa: BLE001
                pass
            step("reset_state")

            # 2) Apply fingerprint
            fp = make_fingerprint(geo)
            await self._apply_fingerprint(serial, fp)
            step("fingerprint", model=fp["model"], locale=fp["locale"])

            # 3) Set proxy via PC-side bridge (auth-strip workaround).
            # USB reverse port-forward eliminates WiFi/router dependency.
            # Phone's localhost:8788 -> PC's localhost:8788 over USB cable.
            if proxy:
                from .proxy_bridge import get_bridge
                bridge = await get_bridge()
                bridge.set_upstream(proxy)
                # Set up reverse forwarding via USB
                try:
                    await self.adb._run([
                        "-s", serial, "reverse", f"tcp:{bridge.listen_port}",
                        f"tcp:{bridge.listen_port}",
                    ])
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"adb reverse failed: {e}")
                # Phone connects to its OWN localhost (which is PC bridge via USB)
                phone_proxy = f"127.0.0.1:{bridge.listen_port}"
                await self.adb.set_proxy(serial, phone_proxy)
                step(
                    "proxy_set",
                    upstream=proxy.split("@")[0],
                    phone_uses=phone_proxy,
                    method="usb_reverse",
                )

            # 4) CLICK MUST REGISTER. Server-side via proxy first, then device.
            click_url = self._inject_click_id(tracker_url, click_id)
            click_status = 0
            try:
                ok, final_url, status = await asyncio.wait_for(
                    self._fire_click_serverside(click_url, ua, proxy),
                    timeout=45.0,
                )
                click_status = status
                step("click_tracker_serverside", ok=ok, status=status, final_url=final_url[:120])
                if not ok:
                    return False, f"click_failed_http_{status}", steps, time.time() - t0
            except asyncio.TimeoutError:
                step("click_tracker_serverside", ok=False, msg="proxy_timeout_45s")
                return False, "click_timeout", steps, time.time() - t0
            except Exception as e:  # noqa: BLE001
                step("click_tracker_serverside", ok=False, msg=str(e)[:120])
                return False, f"click_error: {str(e)[:80]}", steps, time.time() - t0
            # Also open device Chrome (SDK fingerprint match — fire-and-forget)
            try:
                await asyncio.wait_for(
                    self.adb.open_url(serial, click_url), timeout=15.0
                )
            except Exception:  # noqa: BLE001
                pass
            step("click_tracker", url=click_url[:120], final_status=click_status)

            # Realistic wait between click and install (CPI fraud detectors flag instant installs)
            await random_pre_install_delay(
                self.wf.pre_install_min_seconds,
                self.wf.pre_install_max_seconds,
            )

            # Browser KILL after click — we don't want Chrome foreground when
            # we install + run TikTok behavior later (otherwise 5-min behavior
            # will execute on Chrome instead of TikTok).
            await self.adb.kill_browsers(serial)
            await self.adb.shell(serial, "input keyevent KEYCODE_HOME")

            # 5) Resolve final APK URL.
            #    If offer ships a direct APK, use it. Otherwise resolve the tracker
            #    chain ourselves (over the proxy) and look for a Play Store URL —
            #    in that case we fall back to a known APK mirror or fail.
            if apk_url:
                final_apk = apk_url
                step("apk_resolved", source="offer.apk_url")
            else:
                final_apk = await self._resolve_apk_via_chain(click_url, ua, proxy)
                step("apk_resolved", source="redirect_chain", url=(final_apk or "")[:120])
            if not final_apk:
                return False, "no_apk_resolved", steps, time.time() - t0

            # 6) Install APK (max 5 min for big bundle)
            try:
                ok, msg = await asyncio.wait_for(
                    self.adb.install_remote_url(serial, final_apk),
                    timeout=300.0,
                )
            except asyncio.TimeoutError:
                step("install", ok=False, msg="adb_install_timeout_300s")
                return False, "install_timeout", steps, time.time() - t0
            if not ok:
                step("install", ok=False, msg=msg[-200:])
                return False, f"install_failed: {msg[-120:]}", steps, time.time() - t0
            step("install")

            # AUTO-DETECT package name if offer didn't supply one — diff
            # installed packages before vs after install. Without this, all
            # downstream steps (start_app, install_referrer, behavior) skip
            # silently and behavior happens on Chrome instead of the new app.
            if not package:
                try:
                    post_pkgs = await self.adb.list_user_packages(serial)
                    new_pkgs = post_pkgs - pre_install_pkgs
                    # Filter out our own helper packages
                    new_pkgs = {p for p in new_pkgs if not p.startswith("com.android.")}
                    if new_pkgs:
                        package = sorted(new_pkgs)[0]
                        logger.info(f"auto-detected installed package: {package}")
                        step("package_autodetected", package=package)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"package auto-detect failed: {e}")

            # 7) Broadcast INSTALL_REFERRER (so AppsFlyer/Adjust SDK reads our click_id)
            if package:
                await self.adb.broadcast_install_referrer(serial, package, click_id)
                step("install_referrer_broadcast")

            # 8) Open app, wait for SDK init
            if package:
                # Make sure no browser is foreground
                await self.adb.kill_browsers(serial)
                await self.adb.shell(serial, "input keyevent KEYCODE_HOME")
                await asyncio.sleep(1.0)
                await self.adb.start_app(serial, package)
                step("app_opened")
                await asyncio.sleep(random.uniform(8, 18))

                # Verify foreground = our app, retry once if not
                try:
                    fg = await self.adb.get_foreground_app(serial)
                    if fg and fg != package:
                        logger.warning(f"after start_app foreground={fg}, retrying launch")
                        await self.adb.kill_browsers(serial)
                        await self.adb.start_app(serial, package)
                        await asyncio.sleep(5)
                except Exception:  # noqa: BLE001
                    pass

                # 8a) AUTO-DISMISS onboarding popups (Agree/Continue/Allow/Skip)
                #     Loops up to 10 iterations, taps any matching button.
                from .ui_nav import auto_dismiss_popups
                tapped = 0
                try:
                    tapped = await asyncio.wait_for(
                        auto_dismiss_popups(self.adb, serial, max_iters=12, pause_seconds=1.8),
                        timeout=60.0,
                    )
                except asyncio.TimeoutError:
                    pass
                step("auto_dismiss_popups", buttons_tapped=tapped)

                # 8b) Permission grants (camera, mic, storage, location) via pm grant
                for perm in [
                    "android.permission.CAMERA",
                    "android.permission.RECORD_AUDIO",
                    "android.permission.ACCESS_FINE_LOCATION",
                    "android.permission.ACCESS_COARSE_LOCATION",
                    "android.permission.READ_EXTERNAL_STORAGE",
                    "android.permission.WRITE_EXTERNAL_STORAGE",
                    "android.permission.POST_NOTIFICATIONS",
                ]:
                    await self.adb.shell(serial, f"pm grant {package} {perm}")
                step("permissions_granted")

                # 8c) Run popup dismiss again (some prompts appear after permissions)
                try:
                    tapped2 = await asyncio.wait_for(
                        auto_dismiss_popups(self.adb, serial, max_iters=6, pause_seconds=1.5),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    tapped2 = 0
                if tapped2:
                    step("auto_dismiss_popups_pass2", buttons_tapped=tapped2)

            # 9) Behavior simulation (5+ minutes for conversion fire) — runs INSIDE the target app
            beh_dur = random.randint(self.wf.behavior_min_seconds, self.wf.behavior_max_seconds)
            actions = await simulate_session(self.adb, serial, beh_dur, target_package=package or None)
            step("behavior_sim", actions=actions, duration=beh_dur, target=package or "any")

            # 10) Settle wait — let SDK fire conversion event before we mark "likely"
            settle = job.get("settle_seconds", self.wf.default_settle_seconds)
            await asyncio.sleep(settle)
            step("settle", seconds=settle)

            # 11) Aggressive cleanup — every state reset for next install
            if package:
                # Stop app
                await self.adb.force_stop(serial, package)
                # Clear app data (in case uninstall is blocked)
                await self.adb.clear_app_data(serial, package)
                # Uninstall
                await self.adb.uninstall(serial, package)
            # Remove proxy
            await self.adb.set_proxy(serial, None)
            # Reset GAID for next attempt (new advertising id)
            try:
                await self.adb.shell(serial, "settings delete secure advertising_id")
            except Exception:  # noqa: BLE001
                pass
            # Wipe Play Store cache (so next install doesn't get cached data)
            try:
                await self.adb.shell(serial, "pm clear com.android.vending")
            except Exception:  # noqa: BLE001
                pass
            # Clear Chrome cache (cookies, history)
            try:
                await self.adb.shell(serial, "pm clear com.android.chrome")
            except Exception:  # noqa: BLE001
                pass
            # Go back to home screen
            try:
                await self.adb.shell(serial, "input keyevent KEYCODE_HOME")
            except Exception:  # noqa: BLE001
                pass
            step("cleanup_aggressive")

            return True, None, steps, time.time() - t0

        except Exception as e:  # noqa: BLE001
            logger.exception(f"install error on {serial}: {e}")
            step("exception", ok=False, error=str(e)[:200])
            try:
                await self.adb.set_proxy(serial, None)
            except Exception:  # noqa: BLE001
                pass
            return False, f"exception: {str(e)[:120]}", steps, time.time() - t0

    # ── Helpers ────────────────────────────────────────────
    @staticmethod
    def _inject_click_id(url: str, click_id: str) -> str:
        if not url:
            return ""
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}click_id={click_id}&aff_sub5={click_id}"

    async def _fire_click_serverside(self, click_url: str, ua: str, proxy: Optional[str]) -> Tuple[bool, str, int]:
        """Fire the tracker click via httpx through the proxy.

        Returns (ok, final_url, status_code). Network MUST see the click for
        conversion to fire — we treat any non-2xx/3xx as failure so the worker
        can rotate proxies / retry instead of pressing on with a dead click."""
        proxy_url = None
        if proxy:
            if "@" in proxy:
                creds, hp = proxy.split("@", 1)
                proxy_url = f"http://{creds}@{hp}"
            else:
                proxy_url = f"http://{proxy}"
        headers = {
            "User-Agent": ua or "Mozilla/5.0 (Linux; Android 13)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Sec-Ch-Ua-Mobile": "?1",
            "Sec-Ch-Ua-Platform": '"Android"',
            "Upgrade-Insecure-Requests": "1",
        }
        async with httpx.AsyncClient(
            proxy=proxy_url, follow_redirects=True, timeout=30.0, headers=headers, verify=False
        ) as c:
            r = await c.get(click_url)
            final_url = str(r.url)
            ok = 200 <= r.status_code < 400
            logger.info(f"click fired: HTTP {r.status_code} -> {final_url[:160]}")
            return ok, final_url, r.status_code

    async def _resolve_apk_via_chain(self, click_url: str, ua: str, proxy: Optional[str]) -> Optional[str]:
        """Follow the tracker redirect chain server-side via the proxy and look
        for an APK URL. If we end at a Play Store link we return None — caller
        should provide an offer.apk_url for direct install."""
        try:
            proxies = None
            if proxy:
                # proxy = "host:port" or "host:port@user:pass"
                if "@" in proxy:
                    creds, hp = proxy.split("@", 1)
                    proxy_url = f"http://{creds}@{hp}"
                else:
                    proxy_url = f"http://{proxy}"
                proxies = proxy_url
            headers = {"User-Agent": ua or "Mozilla/5.0 (Linux; Android 13)"}
            async with httpx.AsyncClient(proxy=proxies, follow_redirects=True,
                                          timeout=30.0, headers=headers) as c:
                r = await c.get(click_url)
                final = str(r.url)
                if final.endswith(".apk") or "/download" in final.lower():
                    return final
                if "play.google.com" in final:
                    # Tracker landed on Play Store. We cannot install from Play
                    # without a Google account + interactive download. Caller
                    # must supply offer.apk_url.
                    return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"redirect resolve failed: {e}")
        return None

    async def _apply_fingerprint(self, serial: str, fp: Dict[str, str]) -> None:
        """Apply randomized fingerprint via adb settings + Magisk Props
        (when root). Best-effort — silently skips ops that need higher
        privileges than the device grants."""
        # Always-available settings
        await self.adb.settings_put(serial, "secure", "advertising_id", fp["gaid"])
        await self.adb.settings_put(serial, "secure", "android_id", fp["android_id"])
        await self.adb.settings_put(serial, "system", "system_locales", fp["locale"])
        await self.adb.settings_put(serial, "global", "auto_time_zone", "0")
        await self.adb.shell(serial, f"setprop persist.sys.timezone '{fp['timezone']}'")
        await self.adb.shell(serial, f"service call alarm 3 s16 '{fp['timezone']}'")

        # Strict country lock — locale + country code (so apps that read
        # persist.sys.country / persist.sys.locale see the proxy geo not PK).
        country = fp.get("country", "").upper()
        lang = (fp.get("locale", "en-US").split("-") + [""])[0]
        if country:
            try:
                await self.adb.shell(serial, f"setprop persist.sys.country '{country}'")
                await self.adb.shell(serial, f"setprop persist.sys.locale '{fp['locale']}'")
                await self.adb.shell(serial, f"setprop persist.sys.language '{lang}'")
            except Exception:  # noqa: BLE001
                pass

        # DNS lock to country-resilient resolvers (Cloudflare/Google) so DNS
        # leak doesn't reveal real PK ISP. Requires root or "private DNS"
        # API on Android 9+. Best-effort.
        try:
            await self.adb.shell(serial, "settings put global private_dns_mode hostname")
            await self.adb.shell(serial, "settings put global private_dns_specifier one.one.one.one")
        except Exception:  # noqa: BLE001
            pass

        # Mock GPS location matching geo (so apps see Tokyo coords for JP proxy etc.)
        try:
            lat = fp.get("lat")
            lng = fp.get("lng")
            if lat and lng:
                # Enable mock locations
                await self.adb.shell(serial, "settings put secure mock_location 1")
                # Use appops to allow shell as mock location provider
                await self.adb.shell(serial, "appops set com.android.shell android:mock_location allow")
                # Use telephony emulator command to set location (works on most devices)
                await self.adb.shell(
                    serial,
                    f"am broadcast -a android.intent.action.MOCK_LOCATION --ef latitude {lat} --ef longitude {lng}",
                )
        except Exception:  # noqa: BLE001
            pass

        # Root-only operations (no-op without root)
        if self.cfg.use_magisk_props and await self.adb.is_root(serial):
            for key, val in [
                ("ro.product.model", fp["model"]),
                ("ro.product.brand", fp["brand"]),
                ("ro.product.manufacturer", fp["manufacturer"]),
                ("ro.product.name", fp["product"]),
                ("ro.product.device", fp["device"]),
                ("ro.build.fingerprint", fp["fingerprint"]),
                ("ro.build.id", fp["build_id"]),
                ("ro.serialno", fp["serial"]),
            ]:
                # Magisk Props Config command (preferred) else setprop
                await self.adb.shell(serial, f"resetprop -n '{key}' '{val}'")
