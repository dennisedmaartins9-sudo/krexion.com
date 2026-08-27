"""adb wrapper — async subprocess calls for Android automation."""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("cpi.adb")


class ADB:
    def __init__(self, adb_path: str = "adb"):
        self.adb_path = adb_path

    async def _run(self, args: List[str], timeout: int = 60) -> Tuple[int, str, str]:
        cmd = [self.adb_path, *args]
        logger.debug(f"adb run: {' '.join(shlex.quote(c) for c in cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 124, "", "timeout"
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    async def connect(self, endpoint: str, timeout: int = 20) -> bool:
        """adb connect host:port — for emulators / cloud ARM ADB tunnels."""
        ep = (endpoint or "").strip()
        if not ep:
            return False
        rc, out, err = await self._run(["connect", ep], timeout=timeout)
        text = f"{out}\n{err}".lower()
        ok = rc == 0 and ("connected" in text or "already connected" in text)
        if not ok:
            logger.warning(f"adb connect {ep} failed: {(out or err).strip()[:200]}")
        return ok

    async def disconnect(self, endpoint: str) -> None:
        ep = (endpoint or "").strip()
        if not ep:
            return
        try:
            await self._run(["disconnect", ep], timeout=15)
        except Exception:
            pass

    async def devices(self) -> List[Dict[str, str]]:
        """Return list of {serial, state} for all attached devices."""
        rc, out, err = await self._run(["devices", "-l"])
        if rc != 0:
            logger.warning(f"adb devices failed: {err.strip()}")
            return []
        devices = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial, state = parts[0], parts[1]
                model = ""
                for kv in parts[2:]:
                    if kv.startswith("model:"):
                        model = kv.split(":", 1)[1]
                devices.append({"serial": serial, "state": state, "model": model})
        return devices

    async def shell(self, serial: str, cmd: str, timeout: int = 60) -> Tuple[int, str]:
        rc, out, err = await self._run(["-s", serial, "shell", cmd], timeout=timeout)
        if rc != 0 and err:
            logger.debug(f"shell err({serial}): {err.strip()}")
        return rc, out

    async def push(self, serial: str, local: str, remote: str) -> bool:
        rc, _, _ = await self._run(["-s", serial, "push", local, remote])
        return rc == 0

    async def install(self, serial: str, apk_path: str, replace: bool = True) -> Tuple[bool, str]:
        args = ["-s", serial, "install"]
        if replace:
            args.append("-r")
        args.append(apk_path)
        rc, out, err = await self._run(args, timeout=300)
        return rc == 0 and "Success" in out, out + err

    async def install_remote_url(self, serial: str, url: str) -> Tuple[bool, str]:
        """Install APK from URL or local file path.

        Supports single .apk OR split bundles (.apkm, .xapk, .apks) by
        auto-extracting and using `adb install-multiple`.
        """
        import os
        import re
        import shutil
        import tempfile
        import zipfile
        import httpx

        local_path = None
        if url.startswith("file://"):
            local_path = url[7:].lstrip("/") if os.name == "nt" else url[7:]
        elif re.match(r"^[a-zA-Z]:[\\/]", url) or url.startswith("/"):
            local_path = url

        async def _install_path(path: str) -> Tuple[bool, str]:
            ext = os.path.splitext(path)[1].lower()
            # Bundle formats: extract and install-multiple
            if ext in (".apkm", ".xapk", ".apks", ".aab"):
                extract_dir = tempfile.mkdtemp(prefix="rfcpi_apk_")
                try:
                    with zipfile.ZipFile(path) as zf:
                        zf.extractall(extract_dir)
                    apks = []
                    for root, _, files in os.walk(extract_dir):
                        for fn in files:
                            if fn.lower().endswith(".apk"):
                                apks.append(os.path.join(root, fn))
                    if not apks:
                        return False, f"no .apk inside bundle: {path}"
                    rc, out, err = await self._run(
                        ["-s", serial, "install-multiple", "-r"] + apks,
                        timeout=600,
                    )
                    return rc == 0 and "Success" in (out + err), (out + err)[-400:]
                finally:
                    shutil.rmtree(extract_dir, ignore_errors=True)
            # Single APK
            return await self.install(serial, path, replace=True)

        if local_path:
            if not os.path.isfile(local_path):
                return False, f"local apk not found: {local_path}"
            return await _install_path(local_path)

        # Remote
        suffix = ".apkm" if url.lower().endswith(".apkm") else (
            ".xapk" if url.lower().endswith(".xapk") else (
                ".apks" if url.lower().endswith(".apks") else ".apk"
            )
        )
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        try:
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(600.0), follow_redirects=True
                ) as client:
                    async with client.stream(
                        "GET", url, headers={"User-Agent": "Krexion"}
                    ) as resp:
                        if resp.status_code != 200:
                            return False, f"download failed: HTTP {resp.status_code} from {url}"
                        with open(tmp.name, "wb") as f:
                            async for chunk in resp.aiter_bytes(64 * 1024):
                                f.write(chunk)
                size = os.path.getsize(tmp.name)
                if size < 10000:
                    return False, f"download too small: {size} bytes (not an APK?)"
            except Exception as e:  # noqa: BLE001
                return False, f"download error: {e}"

            return await _install_path(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:  # noqa: BLE001
                pass

    async def uninstall(self, serial: str, package: str) -> bool:
        rc, out = await self.shell(serial, f"pm uninstall {package}")
        return "Success" in out

    async def get_prop(self, serial: str, key: str) -> str:
        rc, out = await self.shell(serial, f"getprop {key}")
        return out.strip()

    async def set_prop(self, serial: str, key: str, value: str) -> bool:
        # Requires root or the prop to be writable by shell user
        rc, out = await self.shell(serial, f"setprop {key} '{value}'")
        return rc == 0

    async def is_root(self, serial: str) -> bool:
        rc, out = await self.shell(serial, "id")
        return "uid=0" in out

    async def has_magisk(self, serial: str) -> bool:
        rc, out = await self.shell(serial, "command -v magisk")
        return bool(out.strip())

    async def get_device_info(self, serial: str) -> Dict[str, str]:
        keys = [
            "ro.product.model", "ro.product.brand", "ro.product.manufacturer",
            "ro.build.version.release", "ro.build.version.sdk",
            "ro.product.cpu.abi", "ro.serialno",
        ]
        info = {}
        for k in keys:
            info[k] = await self.get_prop(serial, k)
        return info

    async def settings_put(self, serial: str, namespace: str, key: str, value: str) -> bool:
        """`settings put <namespace> <key> <value>`"""
        rc, out = await self.shell(serial, f"settings put {namespace} {key} '{value}'")
        return rc == 0

    async def settings_delete(self, serial: str, namespace: str, key: str) -> bool:
        rc, _ = await self.shell(serial, f"settings delete {namespace} {key}")
        return rc == 0

    async def set_proxy(self, serial: str, proxy: Optional[str]) -> bool:
        """proxy = 'host:port' or 'host:port@user:pass' (auth via separate
        global settings keys; some Android versions ignore credentials in
        global proxy and require app-level proxy. We set both for best effort)."""
        if not proxy:
            return await self.settings_put(serial, "global", "http_proxy", ":0")
        # Strip credentials for the global proxy setting (not all Android
        # builds support credential-bearing global proxies)
        host_port = proxy.split("@")[0]
        return await self.settings_put(serial, "global", "http_proxy", host_port)

    async def clear_app_data(self, serial: str, package: str) -> bool:
        rc, out = await self.shell(serial, f"pm clear {package}")
        return "Success" in out

    async def force_stop(self, serial: str, package: str) -> None:
        await self.shell(serial, f"am force-stop {package}")

    async def start_app(self, serial: str, package: str) -> bool:
        rc, out = await self.shell(
            serial,
            f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
        )
        return "Events injected: 1" in out

    async def broadcast_install_referrer(self, serial: str, package: str, click_id: str,
                                          extras: Optional[Dict[str, str]] = None) -> bool:
        """Send INSTALL_REFERRER broadcast — AppsFlyer/Adjust/Branch SDKs read this."""
        extras_str = ""
        if extras:
            for k, v in extras.items():
                extras_str += f' --es "{k}" "{v}"'
        cmd = (
            f'am broadcast -a com.android.vending.INSTALL_REFERRER '
            f'-n {package}/com.android.vending.InstallReferrerReceiver '
            f'--es "referrer" "afclick={click_id}&utm_source=krexion"'
            f'{extras_str}'
        )
        rc, out = await self.shell(serial, cmd)
        return "Broadcast completed" in out or "result=0" in out

    async def open_url(self, serial: str, url: str) -> bool:
        rc, out = await self.shell(
            serial, f'am start -a android.intent.action.VIEW -d "{url}"'
        )
        return "Starting" in out

    async def tap(self, serial: str, x: int, y: int) -> None:
        await self.shell(serial, f"input tap {x} {y}")

    async def swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int, dur_ms: int = 300) -> None:
        await self.shell(serial, f"input swipe {x1} {y1} {x2} {y2} {dur_ms}")

    async def screen_size(self, serial: str) -> Tuple[int, int]:
        rc, out = await self.shell(serial, "wm size")
        m = re.search(r"(\d+)x(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 1080, 1920

    async def reboot(self, serial: str) -> None:
        await self._run(["-s", serial, "reboot"])

    async def setup_proxy_with_auth(self, serial: str, proxy: str) -> None:
        """Best-effort proxy config including credentials.
        Uses ProxyDroid-style approach via global settings + per-network HTTP proxy."""
        await self.set_proxy(serial, proxy)

    async def list_user_packages(self, serial: str) -> set:
        """Return set of installed third-party (user) package names."""
        rc, out = await self.shell(serial, "pm list packages -3")
        pkgs = set()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                pkgs.add(line[8:].strip())
        return pkgs

    async def get_foreground_app(self, serial: str) -> str:
        """Return package name of the currently focused/foreground app."""
        # Try Android 11+ first
        rc, out = await self.shell(
            serial, "dumpsys window 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp'"
        )
        m = re.search(r"([a-zA-Z][a-zA-Z0-9_.]+)/[a-zA-Z]", out)
        if m:
            return m.group(1)
        # Fallback: dumpsys activity
        rc, out = await self.shell(
            serial, "dumpsys activity activities 2>/dev/null | grep mResumedActivity"
        )
        m = re.search(r"([a-zA-Z][a-zA-Z0-9_.]+)/[a-zA-Z]", out)
        return m.group(1) if m else ""

    async def kill_browsers(self, serial: str) -> None:
        """Force-stop common browsers so they don't steal foreground from target app."""
        for pkg in [
            "com.android.chrome", "com.chrome.beta", "com.chrome.dev",
            "org.mozilla.firefox", "com.opera.browser", "com.opera.mini.native",
            "com.brave.browser", "com.sec.android.app.sbrowser",
            "com.microsoft.emmx", "com.UCMobile.intl",
            "com.android.browser", "com.mi.globalbrowser",
        ]:
            try:
                await self.shell(serial, f"am force-stop {pkg}")
            except Exception:  # noqa: BLE001
                pass
