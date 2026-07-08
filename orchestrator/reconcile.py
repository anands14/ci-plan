"""Wakeup recording and daemon reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from . import github
from .config import ProjectConfig
from .ledger import RunLedgerEntry


@dataclass(frozen=True)
class ReconcileItem:
    issue_number: int
    pr_number: int | None
    current_step: str
    lease_exists: bool
    pid_alive: bool | None
    labels: list[str]
    checks: dict[str, str]
    actions: list[str]


@dataclass(frozen=True)
class ReconcileReport:
    items: list[ReconcileItem]
    polling_seconds: int


def record_wakeup(
    config: ProjectConfig,
    *,
    event: str,
    issue_number: int | None = None,
    payload: dict[str, Any] | None = None,
) -> Path:
    wake_dir = config.root / ".orchestrator" / "wakeups"
    wake_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = wake_dir / f"{config.name}-{stamp}.json"
    document = {
        "project": config.name,
        "event": event,
        "issue_number": issue_number,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def reconcile(
    config: ProjectConfig,
    *,
    github_client: Any = github,
) -> ReconcileReport:
    entries = _read_entries(config)
    polling_seconds = int(config.raw.get("triggers", {}).get("poll_interval_seconds", 300))
    return ReconcileReport(
        items=[_reconcile_entry(config, entry, github_client) for entry in entries],
        polling_seconds=polling_seconds,
    )


def _reconcile_entry(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    github_client: Any,
) -> ReconcileItem:
    lease_exists = Path(entry.lease_path).is_dir()
    pid_alive = _pid_alive(entry.worker_pid) if entry.worker_pid else None
    labels = _safe_labels(config, entry, github_client)
    checks: dict[str, str] = {}
    if entry.pr_number:
        checks = _safe_checks(config, entry, github_client)

    actions: list[str] = []
    if _active_step(entry.current_step) and not lease_exists:
        actions.append("recover-or-release-missing-lease")
    if entry.worker_pid and pid_alive is False and _active_step(entry.current_step):
        actions.append("recover-dead-worker")
    if "ready" in labels and entry.current_step != "claimed":
        actions.append("label-drift-ready-on-active-ledger")
    if entry.current_step == "pr-ready" and _deterministic_green(checks):
        actions.append("run-sim-validation")
    if entry.current_step == "sim-validation-passed" and _deterministic_green(checks):
        actions.append("run-review")
    if entry.current_step == "review-passed" and _merge_contexts_green(checks):
        actions.append("integrate-to-daily-branch")
    if entry.current_step == "integration-failed":
        actions.append("wake-codex-for-integration-fix")
    if entry.current_step == "base-refresh-conflict":
        actions.append("wake-codex-for-base-conflict")

    return ReconcileItem(
        issue_number=entry.issue_number,
        pr_number=entry.pr_number,
        current_step=entry.current_step,
        lease_exists=lease_exists,
        pid_alive=pid_alive,
        labels=labels,
        checks=checks,
        actions=actions,
    )


def _read_entries(config: ProjectConfig) -> list[RunLedgerEntry]:
    runs_dir = config.root / ".orchestrator" / "runs"
    if not runs_dir.is_dir():
        return []
    entries = []
    for path in sorted(runs_dir.glob(f"{config.name}-issue-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entries.append(RunLedgerEntry(**data))
    return entries


def _safe_labels(config: ProjectConfig, entry: RunLedgerEntry, github_client: Any) -> list[str]:
    try:
        return github_client.issue_labels(config.repo, entry.issue_number)
    except Exception:
        return []


def _safe_checks(config: ProjectConfig, entry: RunLedgerEntry, github_client: Any) -> dict[str, str]:
    try:
        checks, _green = github_client.pr_checks(config.repo, entry.pr_number)
        return checks
    except Exception:
        return {}


def _active_step(step: str) -> bool:
    return step not in {
        "approved",
        "integrated",
        "integration-failed",
        "review-passed",
        "stuck",
        "deferred",
        "closed",
        "merged",
    }


def _deterministic_green(checks: dict[str, str]) -> bool:
    return checks.get("gate") == "pass" and checks.get("test-discipline") == "pass"


def _merge_contexts_green(checks: dict[str, str]) -> bool:
    return all(
        checks.get(name) == "pass"
        for name in ("gate", "test-discipline", "sim-validation", "review")
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
