"""Operating cadence: nightly E2E, daily report, and weekly metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from .config import ProjectConfig
from .reporting import evening_report


@dataclass(frozen=True)
class NightlyTarget:
    name: str
    command: str


@dataclass(frozen=True)
class NightlyTargetResult:
    name: str
    command: str
    attempts: int
    status: str


@dataclass(frozen=True)
class NightlyRun:
    dry_run: bool
    retries: int
    results: list[NightlyTargetResult]
    record_path: Path | None


def nightly_targets(config: ProjectConfig) -> list[NightlyTarget]:
    nightly = config.raw.get("tests", {}).get("nightly_e2e", {})
    targets: list[NightlyTarget] = []
    for platform, items in nightly.items():
        if not isinstance(items, list):
            continue
        for item in items:
            name = str(item)
            command = _nightly_command(config, platform, name)
            if command:
                targets.append(NightlyTarget(f"{platform}:{name}", command))
    return targets


def run_nightly_e2e(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    runner: Any = subprocess.run,
) -> NightlyRun:
    retries = int(config.raw.get("tests", {}).get("flake_firewall", {}).get("retries", 0))
    results: list[NightlyTargetResult] = []
    for target in nightly_targets(config):
        if dry_run:
            results.append(NightlyTargetResult(target.name, target.command, 0, "planned"))
            continue
        attempts = 0
        status = "failed"
        for attempt in range(retries + 1):
            attempts = attempt + 1
            result = runner(
                ["/bin/zsh", "-lc", target.command],
                cwd=config.local_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                status = "passed" if attempts == 1 else "flaky"
                break
        results.append(NightlyTargetResult(target.name, target.command, attempts, status))
    record_path = None if dry_run else _write_nightly_record(config, results)
    return NightlyRun(dry_run, retries, results, record_path)


def daily_report(config: ProjectConfig) -> str:
    return evening_report(config)


def weekly_retro(config: ProjectConfig) -> str:
    metrics = weekly_metrics(config)
    lines = ["# Weekly Retro Metrics", ""]
    for key in (
        "bounce_back_rate",
        "escalation_rate",
        "window_exhaustion_frequency",
        "flake_rate",
        "conformance_fail_rate",
        "reviewer_false_approvals",
    ):
        lines.append(f"- {key}: {metrics[key]}")
    return "\n".join(lines) + "\n"


def weekly_metrics(config: ProjectConfig) -> dict[str, str]:
    entries = _ledger_entries(config)
    total = len(entries) or 1
    gate_or_review_failures = sum(
        1
        for entry in entries
        if entry.get("gate_status") == "failed" or entry.get("review_status") in {"request-changes", "request_changes", "changes"}
    )
    stuck = sum(1 for entry in entries if entry.get("current_step") == "stuck")
    deferred = sum(1 for entry in entries if entry.get("current_step") == "deferred")
    conformance = sum(1 for entry in entries if "conformance" in str(entry.get("last_summary", "")).lower())
    nightly = _nightly_records(config)
    nightly_results = [result for record in nightly for result in record.get("results", [])]
    flaky = sum(1 for result in nightly_results if result.get("status") == "flaky")
    nightly_total = len(nightly_results) or 1
    false_approvals = _reviewer_false_approval_count(config)
    return {
        "bounce_back_rate": _rate(gate_or_review_failures, total),
        "escalation_rate": _rate(stuck, total),
        "window_exhaustion_frequency": str(deferred),
        "flake_rate": _rate(flaky, nightly_total),
        "conformance_fail_rate": _rate(conformance, total),
        "reviewer_false_approvals": str(false_approvals),
    }


def _nightly_command(config: ProjectConfig, platform: str, name: str) -> str | None:
    if name == "build-apk":
        command = config.raw.get("gate", {}).get("commands", {}).get("build")
        return str(command) if command else None
    if name in {"ios", "macos"}:
        return (
            f"{config.root / 'bin' / 'sim-validate'} --sha origin/{config.default_branch} "
            f"--platform {name} --repo {config.repo} --config {config.path}"
        )
    if name == "android":
        return "cd packages/tovi_app && fvm flutter test integration_test --tags e2e -d android"
    return None


def _write_nightly_record(config: ProjectConfig, results: list[NightlyTargetResult]) -> Path:
    directory = config.root / ".orchestrator" / "nightly"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{config.name}-{stamp}.json"
    document = {
        "project": config.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _ledger_entries(config: ProjectConfig) -> list[dict[str, Any]]:
    runs_dir = config.root / ".orchestrator" / "runs"
    if not runs_dir.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob(f"{config.name}-issue-*.json"))
    ]


def _nightly_records(config: ProjectConfig) -> list[dict[str, Any]]:
    directory = config.root / ".orchestrator" / "nightly"
    if not directory.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob(f"{config.name}-*.json"))
    ]


def _reviewer_false_approval_count(config: ProjectConfig) -> int:
    path = config.root / ".orchestrator" / "metrics" / "reviewer_false_approvals.json"
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return len(data)
    return int(data.get("count", 0))


def _rate(count: int, total: int) -> str:
    return f"{count}/{total}"
