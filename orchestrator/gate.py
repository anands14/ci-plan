"""Deterministic local gate runner."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any

from .config import ProjectConfig
from .integration import daily_branch_name
from .ledger import RunLedgerEntry, update_run_entry


GATE_ORDER = ("format", "lint", "test")
PROTECTED_PATH_PREFIXES = (".github/",)
PROTECTED_PATHS = (
    "docs/CONSTITUTION.md",
    ".no-mistakes.yaml",
    "AGENTS.md",
    "CLAUDE.md",
    "melos.yaml",
    "pubspec.yaml",
)


@dataclass(frozen=True)
class GateCommandResult:
    name: str
    command: str
    returncode: int
    log_path: Path


@dataclass(frozen=True)
class GateRunResult:
    passed: bool
    summary: str
    commands: list[GateCommandResult]


def run_gate(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    runner: Any = subprocess.run,
) -> GateRunResult:
    gate_config = config.raw.get("gate", {})
    if not isinstance(gate_config, dict):
        raise RuntimeError("missing gate config")
    ci_autofix = gate_config.get("ci_autofix", "")
    if ci_autofix is not False and str(ci_autofix).lower() != "off":
        raise RuntimeError("gate.ci_autofix must be off for orchestrator-owned fix loop")

    commands_config = gate_config.get("commands", {})
    if not isinstance(commands_config, dict) or not commands_config:
        raise RuntimeError("missing gate.commands")

    lease_path = Path(entry.lease_path)
    log_dir = config.root / ".orchestrator" / "logs" / config.name / f"issue-{entry.issue_number}" / "gate"
    log_dir.mkdir(parents=True, exist_ok=True)

    protected = protected_path_changes(lease_path, base_ref=_base_ref(config, entry))
    if protected:
        summary = "protected-path edit blocked before gate: " + ", ".join(protected)
        update_run_entry(
            config,
            entry,
            current_step="stuck",
            gate_status="blocked",
            gate_summary=summary,
            last_summary=summary,
        )
        return GateRunResult(False, summary, [])

    results: list[GateCommandResult] = []
    for name in GATE_ORDER:
        command = commands_config.get(name)
        if not command:
            continue
        log_path = log_dir / f"{name}.log"
        result = runner(
            ["/bin/zsh", "-lc", str(command)],
            cwd=lease_path,
            capture_output=True,
            text=True,
            env=gate_env(),
        )
        log_path.write_text(
            result.stdout
            + ("\n--- stderr ---\n" + result.stderr if result.stderr else ""),
            encoding="utf-8",
        )
        command_result = GateCommandResult(name, str(command), result.returncode, log_path)
        results.append(command_result)
        if result.returncode != 0:
            summary = f"{name} failed with exit {result.returncode}; see {log_path}"
            update_run_entry(
                config,
                entry,
                current_step="gate-failed",
                gate_status="failed",
                gate_summary=summary,
                last_summary=summary,
            )
            return GateRunResult(False, summary, results)

    summary = f"gate passed: {', '.join(result.name for result in results)}"
    update_run_entry(
        config,
        entry,
        current_step="gate-passed",
        gate_status="passed",
        gate_summary=summary,
        last_summary=summary,
    )
    return GateRunResult(True, summary, results)


def gate_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    for key in list(env):
        upper = key.upper()
        if (
            upper == "SSH_AUTH_SOCK"
            or upper.startswith("GH_")
            or upper.startswith("GITHUB_")
            or "TOKEN" in upper
            or "SECRET" in upper
        ):
            env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def protected_path_changes(path: Path, base_ref: str = "origin/main") -> list[str]:
    changed: set[str] = set()
    commands = (
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        ["git", "diff", "--name-only"],
        ["git", "diff", "--name-only", "--cached"],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        changed.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(file for file in changed if _protected(file))


def _protected(path: str) -> bool:
    return path in PROTECTED_PATHS or any(path.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES)


def _base_ref(config: ProjectConfig, entry: RunLedgerEntry) -> str:
    if entry.integration_branch:
        return f"origin/{entry.integration_branch}"
    integration = config.raw.get("integration", {})
    if isinstance(integration, dict) and integration.get("daily_branch_prefix"):
        return f"origin/{daily_branch_name(config)}"
    return f"origin/{config.default_branch}"
