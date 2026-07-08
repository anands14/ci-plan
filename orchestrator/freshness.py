"""Base freshness checks and clean refresh handling."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
from typing import Any

from .config import ProjectConfig
from .gate import GateRunResult, run_gate
from .integration import daily_branch_name
from .ledger import RunLedgerEntry, update_run_entry


@dataclass(frozen=True)
class BaseFreshnessResult:
    status: str
    summary: str
    head_before: str | None
    head_after: str | None
    diff_changed: bool
    review_action: str
    gate_result: GateRunResult | None = None


def run_base_refresh(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    runner: Any = subprocess.run,
    gate_func: Any = run_gate,
) -> BaseFreshnessResult:
    lease_path = Path(entry.lease_path)
    log_path = (
        config.root
        / ".orchestrator"
        / "logs"
        / config.name
        / f"issue-{entry.issue_number}"
        / "base-refresh.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    base_branch = _base_branch(config, entry)
    fetch = _git(config, lease_path, ["fetch", "origin", base_branch], runner)
    log_path.write_text(_combined(fetch), encoding="utf-8")
    if fetch.returncode != 0:
        summary = f"base fetch failed with exit {fetch.returncode}; see {log_path}"
        update_run_entry(
            config,
            entry,
            current_step="base-refresh-failed",
            base_status="failed",
            base_summary=summary,
            last_summary=summary,
        )
        return BaseFreshnessResult("failed", summary, None, None, False, "none")

    base_ref = f"origin/{base_branch}"
    head_before = _git_text(config, lease_path, ["rev-parse", "HEAD"], runner)
    base_head = _git_text(config, lease_path, ["rev-parse", base_ref], runner)
    merge_base = _git_text(config, lease_path, ["merge-base", "HEAD", base_ref], runner)
    if base_head and merge_base and base_head == merge_base:
        summary = f"branch is current with {base_ref}"
        update_run_entry(
            config,
            entry,
            current_step="base-current",
            base_status="current",
            base_summary=summary,
            last_summary=summary,
        )
        return BaseFreshnessResult("current", summary, head_before, head_before, False, "none")

    diff_before = _diff_signature(config, lease_path, base_ref, runner)
    rebase = _git(config, lease_path, ["rebase", base_ref], runner)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n--- rebase ---\n")
        f.write(_combined(rebase))
    if rebase.returncode != 0:
        abort = _git(config, lease_path, ["rebase", "--abort"], runner)
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n--- rebase abort ---\n")
            f.write(_combined(abort))
        summary = f"base refresh needs Codex conflict resolution; see {log_path}"
        update_run_entry(
            config,
            entry,
            current_step="base-refresh-conflict",
            base_status="conflict",
            base_summary=summary,
            last_summary=summary,
        )
        return BaseFreshnessResult("conflict", summary, head_before, head_before, False, "wake-codex")

    head_after = _git_text(config, lease_path, ["rev-parse", "HEAD"], runner)
    diff_after = _diff_signature(config, lease_path, base_ref, runner)
    diff_changed = diff_after != diff_before
    gate_result = gate_func(config, entry)
    if not gate_result.passed:
        summary = f"base refresh succeeded but gate failed after refresh: {gate_result.summary}"
        update_run_entry(
            config,
            entry,
            current_step="base-refreshed-gate-failed",
            base_status="gate-failed",
            base_summary=summary,
            final_head_sha=head_after,
            last_summary=summary,
        )
        return BaseFreshnessResult("gate-failed", summary, head_before, head_after, diff_changed, "none", gate_result)

    review_action = "none"
    if entry.review_status:
        review_action = "rerun-claude" if diff_changed else "carry-forward-review"
    current_step = "review-rerun-required" if review_action == "rerun-claude" else "base-refreshed"
    summary = (
        f"base refreshed onto {base_ref}; diff_changed={str(diff_changed).lower()}; "
        f"review_action={review_action}"
    )
    update_run_entry(
        config,
        entry,
        current_step=current_step,
        base_status="refreshed",
        base_summary=summary,
        final_head_sha=head_after,
        last_summary=summary,
    )
    return BaseFreshnessResult("refreshed", summary, head_before, head_after, diff_changed, review_action, gate_result)


def _git(
    config: ProjectConfig,
    cwd: Path,
    args: list[str],
    runner: Any,
) -> subprocess.CompletedProcess:
    return runner(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_token_free_env(),
    )


def _git_text(config: ProjectConfig, cwd: Path, args: list[str], runner: Any) -> str | None:
    result = _git(config, cwd, args, runner)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _diff_signature(config: ProjectConfig, cwd: Path, base_ref: str, runner: Any) -> str:
    result = _git(config, cwd, ["diff", "--find-renames", "--stat", f"{base_ref}...HEAD"], runner)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _token_free_env() -> dict[str, str]:
    env = dict(os.environ)
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


def _combined(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "") + (("\n--- stderr ---\n" + result.stderr) if result.stderr else "")


def _base_branch(config: ProjectConfig, entry: RunLedgerEntry) -> str:
    if entry.integration_branch:
        return entry.integration_branch
    integration = config.raw.get("integration", {})
    if isinstance(integration, dict) and integration.get("daily_branch_prefix"):
        return daily_branch_name(config)
    return config.default_branch
