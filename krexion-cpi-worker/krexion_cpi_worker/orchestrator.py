"""Orchestrator — top-level loop that:
  • Discovers connected Android + iOS devices on startup and on each cycle
  • Registers them with the Krexion backend
  • Sends heartbeats
  • Polls for queued install attempts and dispatches to the right engine
  • Reports results back

Designed to be safe to restart anytime — fully stateless.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .adb import ADB
from .android_engine import AndroidEngine
from .api_client import APIClient
from .config import Config
from .ios_engine import IOSEngine
from .ios_tools import IOSTools

logger = logging.getLogger("cpi.orchestrator")


class DeviceSlot:
    """Tracks one physical device and its currently-running install task."""
    def __init__(self, info: Dict[str, str], engine_kind: str):
        self.info = info
        self.engine_kind = engine_kind          # "android" | "ios"
        self.busy = False
        self.last_install_at: Optional[float] = None
        self.task: Optional[asyncio.Task] = None
        # Backend's device row id (from /devices/register response)
        self.backend_id: Optional[str] = None

    @property
    def serial(self) -> str:
        return self.info["serial"]

    @property
    def device_type(self) -> str:
        return self.info["device_type"]


class Orchestrator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api = APIClient(cfg.api.base_url, cfg.api.token)
        self.adb = ADB(cfg.android.adb_path)
        self.ios_tools = IOSTools(cfg.ios.libimobiledevice_path, cfg.ios.tidevice_path)
        self.android_engine = AndroidEngine(self.adb, cfg.android, cfg.workflow)
        self.ios_engine = IOSEngine(self.ios_tools, cfg.ios, cfg.workflow)
        self.slots: Dict[str, DeviceSlot] = {}
        self._stop = asyncio.Event()

    async def run(self):
        logger.info(f"Krexion CPI Worker starting → backend={self.cfg.api.base_url}")
        try:
            me = await self.api.auth_check()
            logger.info(f"Auth OK as user: {me.get('email')} (status={me.get('status')})")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Auth failed: {e}. Check api.token in config.yaml")
            return

        await self._discover_and_register()
        if not self.slots and getattr(self.cfg.android, "auto_runtime", True):
            logger.info("No devices — starting Krexion Android Engine (silent auto-runtime)")
            await self._ensure_krexion_android()
            await self._discover_and_register()
        if not self.slots:
            logger.warning(
                "Krexion Android not ready yet. Worker will keep retrying auto-runtime."
            )

        # Main loops
        await asyncio.gather(
            self._heartbeat_loop(),
            self._discovery_loop(),
            self._dispatch_loop(),
            self._commands_loop(),
        )

    async def _ensure_krexion_android(self, instances: int = 1) -> None:
        try:
            from .krexion_android_runtime import ensure_krexion_android

            want = max(1, min(8, int(instances or getattr(self.cfg.android, "farm_instances", 1) or 1)))
            result = await ensure_krexion_android(
                adb_path=self.cfg.android.adb_path,
                instances=want,
            )
            logger.info(
                f"Krexion Android Engine: {result.get('status')} — {result.get('message')} "
                f"(instances={result.get('instances') or want})"
            )
            await self._sync_cloud_adb_endpoints()
            if hasattr(self.android_engine, "ensure_emulator_connections"):
                await self.android_engine.ensure_emulator_connections()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Krexion Android Engine failed: {e}")

    async def _sync_cloud_adb_endpoints(self) -> None:
        """Pull adb_endpoint from backend cloud devices into worker config."""
        try:
            devices = await self.api.list_devices()
            if not isinstance(devices, list):
                return
            eps: List[str] = []
            for d in devices:
                if not isinstance(d, dict):
                    continue
                ep = str(d.get("adb_endpoint") or "").strip()
                dtype = str(d.get("device_type") or "")
                if ep and ":" in ep and (dtype.startswith("android_") or d.get("device_id", "").startswith("cloud:")):
                    if ep not in eps:
                        eps.append(ep)
            if not eps:
                return
            existing = list(self.cfg.android.cloud_adb_endpoints or [])
            merged = existing[:]
            for ep in eps:
                if ep not in merged:
                    merged.append(ep)
            self.cfg.android.cloud_adb_endpoints = merged
            logger.info(f"Synced {len(eps)} Krexion Cloud Android ADB endpoint(s)")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"cloud ADB sync skipped: {e}")

    async def _commands_loop(self):
        """Poll backend for one-click Enable Krexion Android / force recreate."""
        while not self._stop.is_set():
            try:
                await self._sync_cloud_adb_endpoints()
                cmds = await self.api.worker_commands()
                for cmd in cmds.get("commands") or []:
                    ctype = str((cmd or {}).get("type") or "")
                    cid = str((cmd or {}).get("id") or "")
                    # Honor per-command cloud ADB endpoint (from provision)
                    ep = str((cmd or {}).get("adb_endpoint") or "").strip()
                    if ep and ":" in ep:
                        cloud = list(self.cfg.android.cloud_adb_endpoints or [])
                        if ep not in cloud:
                            cloud.append(ep)
                            self.cfg.android.cloud_adb_endpoints = cloud
                        if hasattr(self.android_engine, "ensure_emulator_connections"):
                            await self.android_engine.ensure_emulator_connections()
                    if ctype in ("ensure_android", "enable_krexion_android"):
                        inst = int((cmd or {}).get("instances") or 1)
                        await self._ensure_krexion_android(instances=inst)
                        await self._discover_and_register()
                        if cid:
                            from .krexion_android_runtime import read_status
                            await self.api.ack_worker_command(
                                cid, ok=True, result=read_status()
                            )
                    elif ctype == "connect_cloud_adb":
                        if hasattr(self.android_engine, "ensure_emulator_connections"):
                            await self.android_engine.ensure_emulator_connections()
                        await self._discover_and_register()
                        if cid:
                            await self.api.ack_worker_command(cid, ok=True)
                    elif ctype == "runtime_status":
                        from .krexion_android_runtime import read_status
                        if cid:
                            await self.api.ack_worker_command(
                                cid, ok=True, result=read_status()
                            )
            except Exception as e:  # noqa: BLE001
                logger.debug(f"commands loop: {e}")
            await asyncio.sleep(max(8, int(self.cfg.api.poll_interval_seconds)))

    # ── Discovery & registration ───────────────────────────
    async def _discover_and_register(self):
        if self.cfg.android.enabled:
            try:
                for d in await self.android_engine.discover():
                    await self._register_slot(d, "android")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Android discovery failed (continuing): {e}")
        if self.cfg.ios.enabled:
            try:
                for d in await self.ios_engine.discover():
                    await self._register_slot(d, "ios")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"iOS discovery failed (continuing without iOS): {e}")

    async def _register_slot(self, info: Dict[str, str], engine_kind: str):
        if info["serial"] in self.slots:
            return
        try:
            row = await self.api.register_device(
                device_id=info["device_id"],
                device_type=info["device_type"],
                label=info.get("model"),
                model=info.get("model"),
                os_version=info.get("os_version"),
            )
            slot = DeviceSlot(info, engine_kind)
            slot.backend_id = row.get("id")
            self.slots[info["serial"]] = slot
            logger.info(f"Registered {engine_kind} device {info['serial']} ({info.get('model')})")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"register_device failed for {info['serial']}: {e}")

    async def _discovery_loop(self):
        while not self._stop.is_set():
            try:
                await self._discover_and_register()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"discovery loop: {e}")
            await asyncio.sleep(60)

    # ── Heartbeats ─────────────────────────────────────────
    async def _heartbeat_loop(self):
        while not self._stop.is_set():
            for slot in list(self.slots.values()):
                status = "busy" if slot.busy else "online"
                if not slot.backend_id:
                    continue
                resp = await self.api.heartbeat(slot.backend_id, status=status)
                pending = (resp or {}).get("needs_action")
                if pending and not slot.busy:
                    await self._handle_needs_action(slot, pending)
            await asyncio.sleep(self.cfg.api.heartbeat_interval_seconds)

    async def _handle_needs_action(self, slot: DeviceSlot, action: Any) -> None:
        """Execute queued open_url / install_apk from Browser Profiles / CPI UI."""
        if isinstance(action, str):
            # Legacy string flags (2fa_pending etc.) — not executable
            logger.info(f"needs_action flag on {slot.serial}: {action}")
            return
        if not isinstance(action, dict):
            return
        atype = str(action.get("type") or "").strip().lower()
        if atype not in ("open_url", "install_apk", "install"):
            logger.info(f"Ignoring needs_action type={atype} on {slot.serial}")
            return
        slot.busy = True
        try:
            if slot.engine_kind != "android":
                logger.warning(f"needs_action {atype} not supported on iOS yet")
                return
            result = await self.android_engine.execute_action(slot.serial, action)
            logger.info(f"needs_action {atype} on {slot.serial}: {result}")
            # ACK so backend clears the queue
            if slot.backend_id:
                await self.api.heartbeat(
                    slot.backend_id,
                    status="online",
                    clear_needs_action=True,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"needs_action failed on {slot.serial}: {e}")
        finally:
            slot.busy = False

    # ── Job dispatch ───────────────────────────────────────
    async def _dispatch_loop(self):
        while not self._stop.is_set():
            try:
                # v2.7.21 — claim work for EVERY idle slot (parallel farm)
                idle = [s for s in self.slots.values() if not s.busy]
                if not idle:
                    await asyncio.sleep(self.cfg.api.poll_interval_seconds)
                    continue

                claimed_any = False
                for slot in idle:
                    if slot.busy:
                        continue
                    dtype = slot.device_type
                    types = [dtype]
                    if dtype.startswith("android_"):
                        types = list({
                            dtype,
                            "android_real",
                            "android_genymotion",
                            "android_emulator",
                            "android_ldplayer",
                            "android_bluestacks",
                            "android_cloud",
                            "android_krexion",
                        })
                    payload = await self.api.poll(
                        device_types=types,
                        device_id=slot.backend_id,
                    )
                    if not payload.get("has_work"):
                        continue

                    claimed_any = True
                    attempt = payload["attempt"]
                    job = payload["job"]
                    offer = payload["offer"]
                    slot.busy = True
                    slot.task = asyncio.create_task(
                        self._execute_one(slot, attempt, job, offer),
                        name=f"install-{attempt['id']}",
                    )

                if not claimed_any:
                    await asyncio.sleep(self.cfg.api.poll_interval_seconds)
                else:
                    # Brief yield so heartbeats can run while tasks execute
                    await asyncio.sleep(0.5)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"dispatch loop: {e}")
                await asyncio.sleep(self.cfg.api.poll_interval_seconds)

    async def _execute_one(self, slot: DeviceSlot, attempt: Dict[str, Any],
                           job: Dict[str, Any], offer: Dict[str, Any]):
        attempt_id = attempt["id"]
        timeout = self.cfg.workflow.install_timeout_seconds
        try:
            if slot.engine_kind == "android":
                coro = self.android_engine.execute_install(slot.serial, attempt, job, offer)
            else:
                coro = self.ios_engine.execute_install(slot.serial, attempt, job, offer)
            success, reason, steps, dur = await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            success, reason, steps, dur = False, "timeout", [{"name": "timeout"}], float(timeout)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"execute_one error: {e}")
            success, reason, steps, dur = False, f"unhandled: {str(e)[:120]}", [], 0.0

        # Report result
        try:
            await self.api.report_result(
                attempt_id=attempt_id,
                success=success,
                failure_reason=reason,
                duration_seconds=dur,
                steps=steps,
                click_id=attempt.get("_click_id"),
                device_id=slot.serial,
                device_label=slot.info.get("model") or slot.serial[:12],
            )
            logger.info(
                f"Attempt {attempt_id[:10]} on {slot.serial}: "
                f"{'OK' if success else 'FAIL'} ({reason or 'completed'}) in {dur:.1f}s"
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"report_result failed: {e}")
        finally:
            slot.busy = False
            slot.last_install_at = time.time()


# ────────────────────────────────────────────────────────────
# Doctor — health check
# ────────────────────────────────────────────────────────────
async def run_doctor(cfg: Config) -> int:
    print("Krexion CPI Worker — Doctor\n" + "─" * 40)
    api = APIClient(cfg.api.base_url, cfg.api.token)
    try:
        me = await api.auth_check()
        print(f"  ✓ Backend reachable, auth OK ({me.get('email')})")
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ Backend / auth: {e}")
        await api.close()
        return 1

    if cfg.android.enabled:
        adb = ADB(cfg.android.adb_path)
        try:
            from .android_engine import AndroidEngine
            eng = AndroidEngine(cfg.android)
            await eng.ensure_emulator_connections()
        except Exception:
            pass
        devs = await adb.devices()
        print(f"  • Android devices via adb: {len(devs)}")
        for d in devs:
            print(f"      {d.get('serial')} ({d.get('model') or d.get('state')}) state={d.get('state')}")
        cloud = list(cfg.android.cloud_adb_endpoints or [])
        print(f"  • Cloud ADB endpoints configured: {len(cloud)}")
    else:
        print("  • Android engine disabled in config")

    if cfg.ios.enabled:
        ios = IOSTools(cfg.ios.libimobiledevice_path, cfg.ios.tidevice_path)
        try:
            udids = await ios.list_udids()
        except Exception as e:  # noqa: BLE001
            udids = []
            print(f"  ! iOS tools error: {e}")
        print(f"  • iOS devices: {len(udids)}")
        for u in udids:
            print(f"      {u}")
    else:
        print("  • iOS engine disabled in config")

    await api.close()
    print("\nDoctor finished. If devices are missing, see CPI-FAQ-URDU.md.")
    return 0
