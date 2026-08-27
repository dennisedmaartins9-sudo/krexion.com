"""Configuration loader (YAML + env overrides)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


def _resolve_env(value: Any) -> Any:
    """If value is 'ENV:VAR_NAME' string, resolve from env."""
    if isinstance(value, str) and value.startswith("ENV:"):
        return os.environ.get(value[4:], "")
    return value


@dataclass
class APIConfig:
    base_url: str
    token: str
    poll_interval_seconds: int = 5
    heartbeat_interval_seconds: int = 30


@dataclass
class AndroidConfig:
    enabled: bool = True
    adb_path: str = "adb"
    auto_discover: bool = True
    serial_allowlist: List[str] = field(default_factory=list)
    use_magisk_props: bool = True
    use_frida: bool = True
    frida_server_path: str = ""
    # v2.7.18 — no physical phone: auto adb connect to local emulators / cloud ADB
    prefer_emulator: bool = True
    emulator_endpoints: List[str] = field(default_factory=lambda: [
        "127.0.0.1:5555",
        "127.0.0.1:5557",
        "127.0.0.1:5559",
        "127.0.0.1:5561",
        "127.0.0.1:5563",
        "127.0.0.1:5565",
        "127.0.0.1:5567",
        "127.0.0.1:5569",
    ])
    # Remote Krexion Cloud Android ADB tunnels (host:port) — synced from backend devices
    cloud_adb_endpoints: List[str] = field(default_factory=list)
    # v2.7.19 — silent Krexion Android Engine (customer never installs 3rd-party emulators)
    auto_runtime: bool = True
    runtime_brand: str = "Krexion Android"
    # v2.7.21 — default farm size when auto-provisioning
    farm_instances: int = 1


@dataclass
class IOSConfig:
    enabled: bool = True
    libimobiledevice_path: str = ""
    tidevice_path: str = "tidevice3"
    wda_bundle_id: str = "com.facebook.WebDriverAgentRunner.xctrunner"
    apple_ids: List[Dict[str, Any]] = field(default_factory=list)
    auto_discover: bool = True
    serial_allowlist: List[str] = field(default_factory=list)


@dataclass
class WorkflowConfig:
    default_settle_seconds: int = 45
    behavior_min_seconds: int = 60
    behavior_max_seconds: int = 180
    pre_install_min_seconds: int = 10
    pre_install_max_seconds: int = 45
    install_timeout_seconds: int = 600
    max_retries: int = 1


@dataclass
class Config:
    api: APIConfig
    android: AndroidConfig
    ios: IOSConfig
    workflow: WorkflowConfig
    logging_level: str = "INFO"
    logging_file: str = "worker.log"
    logging_json: bool = False


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Config file not found: {p}. "
            f"Copy config.example.yaml to {p.name} and edit it."
        )
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))

    api = raw.get("api", {})
    android = raw.get("android", {})
    ios = raw.get("ios", {})
    wf = raw.get("workflow", {})
    log = raw.get("logging", {})

    if not api.get("token") or "PASTE" in api.get("token", ""):
        raise ValueError("api.token is not set in config.yaml — paste your Krexion JWT")

    # Resolve env-vars in apple_ids passwords
    for aid in ios.get("apple_ids", []) or []:
        if "password" in aid:
            aid["password"] = _resolve_env(aid["password"])

    return Config(
        api=APIConfig(
            base_url=api["base_url"].rstrip("/"),
            token=api["token"],
            poll_interval_seconds=int(api.get("poll_interval_seconds", 5)),
            heartbeat_interval_seconds=int(api.get("heartbeat_interval_seconds", 30)),
        ),
        android=AndroidConfig(**{k: v for k, v in android.items() if k in AndroidConfig.__dataclass_fields__}),
        ios=IOSConfig(**{k: v for k, v in ios.items() if k in IOSConfig.__dataclass_fields__}),
        workflow=WorkflowConfig(**{k: v for k, v in wf.items() if k in WorkflowConfig.__dataclass_fields__}),
        logging_level=log.get("level", "INFO"),
        logging_file=log.get("file", "worker.log"),
        logging_json=bool(log.get("json_logs", False)),
    )
