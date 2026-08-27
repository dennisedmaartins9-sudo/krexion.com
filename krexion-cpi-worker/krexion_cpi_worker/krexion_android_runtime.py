"""
Krexion Android Engine (silent runtime)
======================================
Auto-provisions a local Android environment for CPI without asking the
customer to install any third-party phone apps.

Customer-facing name: always "Krexion Android".
Underlying tooling stays invisible in the product UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("krexion.android_engine")

AVD_NAME = "KrexionPhone"
RUNTIME_DIR_NAME = "AndroidRuntime"
STATUS_FILE = "runtime_status.json"

# Official Google packages — never shown in customer UI
_CMDLINE_TOOLS_URL = (
    "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
)
_SYSTEM_IMAGE = "system-images;android-34;google_apis;x86_64"
_PLATFORM = "platforms;android-34"


def runtime_root() -> Path:
    override = (os.environ.get("KREXION_ANDROID_RUNTIME_DIR") or "").strip()
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or "."
    return Path(local) / "Krexion" / RUNTIME_DIR_NAME


def status_path() -> Path:
    return runtime_root() / STATUS_FILE


def write_status(status: str, progress: int = 0, message: str = "", **extra: Any) -> Dict[str, Any]:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    doc = {
        "brand": "Krexion Android",
        "status": status,  # idle|downloading|installing|starting|ready|error
        "progress": max(0, min(100, int(progress))),
        "message": (message or "")[:240],
        **extra,
    }
    try:
        status_path().write_text(json.dumps(doc), encoding="utf-8")
    except Exception as e:
        logger.debug(f"status write skipped: {e}")
    return doc


def read_status() -> Dict[str, Any]:
    try:
        p = status_path()
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"brand": "Krexion Android", "status": "idle", "progress": 0, "message": ""}


async def _run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600,
               env: Optional[Dict[str, str]] = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "", "timeout"
    return (
        proc.returncode or 0,
        out.decode("utf-8", "replace"),
        err.decode("utf-8", "replace"),
    )


async def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Prefer httpx if available; else PowerShell
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=600.0) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 256):
                        f.write(chunk)
        return
    except Exception as e:
        logger.debug(f"httpx download fallback: {e}")
    ps = (
        f"$ProgressPreference='SilentlyContinue'; "
        f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest}' -UseBasicParsing"
    )
    rc, _, err = await _run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        timeout=900,
    )
    if rc != 0 or not dest.is_file():
        raise RuntimeError(f"Download failed: {err[:200]}")


def _android_env(root: Path) -> Dict[str, str]:
    env = dict(os.environ)
    sdk = root / "sdk"
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["ANDROID_HOME"] = str(sdk)
    pt = sdk / "platform-tools"
    emu = sdk / "emulator"
    path_bits = [str(pt), str(emu), str(sdk / "cmdline-tools" / "latest" / "bin"), env.get("PATH", "")]
    env["PATH"] = os.pathsep.join(path_bits)
    return env


async def _ensure_java() -> bool:
    rc, out, _ = await _run(["java", "-version"], timeout=20)
    # java -version prints to stderr often; rc 0 is enough
    if rc == 0:
        return True
    # Try winget silent OpenJDK (Krexion needs it for Android Engine)
    write_status("installing", 8, "Preparing Krexion Android Engine…")
    for cmd in (
        ["winget", "install", "-e", "--id", "Microsoft.OpenJDK.17", "--accept-package-agreements",
         "--accept-source-agreements", "-h"],
        ["winget", "install", "-e", "--id", "Microsoft.OpenJDK.21", "--accept-package-agreements",
         "--accept-source-agreements", "-h"],
    ):
        try:
            rc, _, _ = await _run(cmd, timeout=600)
            if rc == 0:
                return True
        except Exception:
            continue
    return False


async def _ensure_cmdline_tools(root: Path) -> Path:
    sdk = root / "sdk"
    tools_bin = sdk / "cmdline-tools" / "latest" / "bin"
    sdkmanager = tools_bin / ("sdkmanager.bat" if os.name == "nt" else "sdkmanager")
    if sdkmanager.is_file():
        return sdkmanager
    write_status("downloading", 15, "Downloading Krexion Android Engine…")
    zpath = root / "_cmdline_tools.zip"
    await _download(_CMDLINE_TOOLS_URL, zpath)
    write_status("installing", 30, "Installing Krexion Android Engine…")
    extract = root / "_cmdline_extract"
    if extract.exists():
        shutil.rmtree(extract, ignore_errors=True)
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "r") as zf:
        zf.extractall(extract)
    # Zip contains cmdline-tools/ — move to sdk/cmdline-tools/latest
    dest = sdk / "cmdline-tools" / "latest"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    # Find nested cmdline-tools folder
    nested = extract / "cmdline-tools"
    if nested.is_dir():
        shutil.move(str(nested), str(dest))
    else:
        # some zips extract flat
        shutil.move(str(extract), str(dest))
    try:
        zpath.unlink(missing_ok=True)
        shutil.rmtree(extract, ignore_errors=True)
    except Exception:
        pass
    if not sdkmanager.is_file():
        raise RuntimeError("Krexion Android Engine tools missing after install")
    return sdkmanager


async def _sdkmanager_install(sdkmanager: Path, root: Path, packages: List[str]) -> None:
    env = _android_env(root)
    # Accept licenses
    write_status("installing", 40, "Configuring Krexion Android Engine…")
    lic = await asyncio.create_subprocess_exec(
        str(sdkmanager), "--licenses",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        yes = ("y\n" * 40).encode()
        await asyncio.wait_for(lic.communicate(input=yes), timeout=300)
    except Exception:
        try:
            lic.kill()
        except Exception:
            pass
    write_status("installing", 55, "Installing Krexion Android system image…")
    rc, out, err = await _run(
        [str(sdkmanager), "--install", *packages],
        timeout=1800,
        env=env,
    )
    if rc != 0:
        # Some packages may already exist
        text = (out + err).lower()
        if "already installed" not in text and "done" not in text:
            logger.warning(f"sdkmanager rc={rc}: {(err or out)[:300]}")


async def _ensure_avd(root: Path, name: str = AVD_NAME) -> None:
    env = _android_env(root)
    avdmanager = root / "sdk" / "cmdline-tools" / "latest" / "bin" / (
        "avdmanager.bat" if os.name == "nt" else "avdmanager"
    )
    rc, out, _ = await _run([str(avdmanager), "list", "avd"], env=env, timeout=60)
    if name in (out or ""):
        return
    write_status("installing", 70, f"Creating {name}…")
    proc = await asyncio.create_subprocess_exec(
        str(avdmanager),
        "create", "avd",
        "-n", name,
        "-k", _SYSTEM_IMAGE,
        "--force",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        await asyncio.wait_for(proc.communicate(input=b"no\n"), timeout=120)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _avd_name(index: int) -> str:
    """KrexionPhone, KrexionPhone-2, …"""
    i = max(1, int(index))
    return AVD_NAME if i == 1 else f"{AVD_NAME}-{i}"


def _console_port(index: int) -> int:
    """Emulator console ports: 5554, 5556, 5558, …"""
    return 5554 + 2 * (max(1, int(index)) - 1)


def _adb_endpoint(index: int) -> str:
    """ADB TCP endpoints paired with console: 5555, 5557, …"""
    return f"127.0.0.1:{_console_port(index) + 1}"


async def _list_running_emulator_serials(adb_path: str = "adb") -> List[str]:
    proc = await asyncio.create_subprocess_exec(
        adb_path, "devices",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", "replace")
    serials: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


async def _start_emulator(root: Path, *, index: int = 1, name: Optional[str] = None) -> str:
    env = _android_env(root)
    emulator = root / "sdk" / "emulator" / ("emulator.exe" if os.name == "nt" else "emulator")
    if not emulator.is_file():
        alt = root / "sdk" / "emulator" / "emulator"
        if alt.is_file():
            emulator = alt
        else:
            raise RuntimeError("Krexion Android emulator binary missing")
    avd = name or _avd_name(index)
    port = _console_port(index)
    write_status("starting", 85, f"Starting {avd}…", avd=avd, port=port)
    args = [
        str(emulator),
        "-avd", avd,
        "-port", str(port),
        "-no-audio",
        "-no-boot-anim",
        "-gpu", "auto",
        "-netdelay", "none",
        "-netspeed", "full",
    ]
    await asyncio.create_subprocess_exec(
        *args,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return _adb_endpoint(index)


async def wait_for_adb_device(adb_path: str = "adb", timeout_sec: int = 180) -> Optional[str]:
    """Return serial when an emulator device comes online."""
    import time

    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        for serial in await _list_running_emulator_serials(adb_path):
            if "emulator" in serial or serial.startswith("127.0.0.1:"):
                write_status("ready", 100, "Krexion Android ready", serial=serial)
                return serial
            write_status("ready", 100, "Krexion Android ready", serial=serial)
            return serial
        await asyncio.sleep(3)
    return None


async def wait_for_n_devices(
    adb_path: str = "adb",
    *,
    count: int = 1,
    timeout_sec: int = 240,
) -> List[str]:
    """Wait until at least `count` ADB devices are online."""
    import time

    need = max(1, int(count))
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        serials = await _list_running_emulator_serials(adb_path)
        if len(serials) >= need:
            write_status(
                "ready", 100,
                f"Krexion Android farm ready ({len(serials)} phones)",
                serials=serials[:12],
                instances=len(serials),
            )
            return serials
        write_status(
            "starting",
            min(99, 70 + len(serials) * 5),
            f"Waiting for Krexion Android… ({len(serials)}/{need})",
            instances=len(serials),
        )
        await asyncio.sleep(3)
    return await _list_running_emulator_serials(adb_path)


async def ensure_krexion_android(
    *,
    adb_path: str = "adb",
    force_recreate: bool = False,
    instances: int = 1,
) -> Dict[str, Any]:
    """
    Full auto path: download/install/start Krexion Android Engine.
    instances>1 starts a silent multi-phone farm (KrexionPhone, KrexionPhone-2, …).
    """
    custom_url = (os.environ.get("KREXION_ANDROID_RUNTIME_URL") or "").strip()
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    want = max(1, min(8, int(instances or 1)))

    try:
        existing = await _list_running_emulator_serials(adb_path)
        if len(existing) >= want and not force_recreate:
            return write_status(
                "ready", 100,
                f"Krexion Android ready ({len(existing)} phones)",
                serial=existing[0],
                serials=existing[:12],
                instances=len(existing),
            )

        write_status("downloading", 5, "Starting Krexion Android setup…", instances=want)

        if custom_url:
            write_status("downloading", 20, "Downloading Krexion Android Engine…")
            zpath = root / "_runtime.zip"
            await _download(custom_url, zpath)
            write_status("installing", 50, "Unpacking Krexion Android Engine…")
            with zipfile.ZipFile(zpath, "r") as zf:
                zf.extractall(root / "portable")
            starter = root / "portable" / "start.bat"
            if starter.is_file():
                await asyncio.create_subprocess_exec(
                    "cmd", "/c", str(starter),
                    cwd=str(starter.parent),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            serials = await wait_for_n_devices(adb_path, count=want, timeout_sec=180)
            if serials:
                return write_status(
                    "ready", 100,
                    f"Krexion Android ready ({len(serials)} phones)",
                    serial=serials[0],
                    serials=serials[:12],
                    instances=len(serials),
                )
            return write_status("error", 0, "Krexion Android did not come online")

        if not await _ensure_java():
            return write_status(
                "error", 0,
                "Krexion Android needs Java — install failed. Retry Enable Krexion Android.",
            )

        sdkmanager = await _ensure_cmdline_tools(root)
        await _sdkmanager_install(
            sdkmanager,
            root,
            ["platform-tools", "emulator", _PLATFORM, _SYSTEM_IMAGE],
        )

        # Create + start missing instances
        running = set(await _list_running_emulator_serials(adb_path))
        for i in range(1, want + 1):
            name = _avd_name(i)
            await _ensure_avd(root, name)
            ep = _adb_endpoint(i)
            # Skip start if this ADB endpoint already online
            if ep in running or any(ep in s for s in running):
                continue
            # Also skip if emulator-{console} style already present for this port
            emu_serial = f"emulator-{_console_port(i)}"
            if emu_serial in running:
                continue
            await _start_emulator(root, index=i, name=name)
            await asyncio.sleep(1.5)

        serials = await wait_for_n_devices(adb_path, count=want, timeout_sec=300)
        if serials:
            return write_status(
                "ready", 100,
                f"Krexion Android farm ready ({len(serials)} phones)",
                serial=serials[0],
                serials=serials[:12],
                instances=len(serials),
                endpoints=[_adb_endpoint(i) for i in range(1, want + 1)],
            )
        return write_status("error", 0, "Krexion Android started but ADB wait timed out")
    except Exception as e:
        logger.exception("ensure_krexion_android failed")
        return write_status("error", 0, f"Krexion Android setup failed: {str(e)[:160]}")
