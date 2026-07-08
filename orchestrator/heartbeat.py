"""Heartbeat and stale-daemon alerting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .config import ProjectConfig


@dataclass(frozen=True)
class HeartbeatStatus:
    ok: bool
    alert_path: Path | None
    reason: str


def write_heartbeat(config: ProjectConfig, *, pid: int | None = None) -> Path:
    path = heartbeat_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "project": config.name,
        "pid": pid or os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def check_heartbeat(config: ProjectConfig, *, max_age_seconds: int | None = None) -> HeartbeatStatus:
    path = heartbeat_path(config)
    if max_age_seconds is None:
        max_age_seconds = int(config.raw.get("triggers", {}).get("poll_interval_seconds", 300)) * 2
    if not path.is_file():
        return _alert(config, "heartbeat missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(str(data["updated_at"]))
        pid = int(data["pid"])
    except Exception:
        return _alert(config, "heartbeat unreadable")

    age = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if age > max_age_seconds:
        return _alert(config, f"heartbeat stale: {int(age)}s old")
    if not _pid_alive(pid):
        return _alert(config, f"heartbeat pid not alive: {pid}")
    return HeartbeatStatus(True, None, "heartbeat ok")


def heartbeat_path(config: ProjectConfig) -> Path:
    return config.root / ".orchestrator" / "heartbeat" / f"{config.name}.json"


def _alert(config: ProjectConfig, reason: str) -> HeartbeatStatus:
    alert_dir = config.root / ".orchestrator" / "alerts"
    alert_dir.mkdir(parents=True, exist_ok=True)
    path = alert_dir / f"{config.name}-heartbeat.json"
    document = {
        "project": config.name,
        "reason": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return HeartbeatStatus(False, path, reason)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
