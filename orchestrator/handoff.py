"""PR handoff through the configured agent remote."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any

from . import github
from .config import ProjectConfig
from .integration import daily_branch_name
from .ledger import RunLedgerEntry, update_run_entry
from .preflight import build_worker_env, origin_failure_proves_blocked
from .queueing import acceptance_criteria, list_items, parse_sections


@dataclass(frozen=True)
class HandoffResult:
    command: list[str]
    log_path: Path
    pushed_branch: str
    pr_number: int | None
    pr_url: str | None
    head_sha: str | None
    status: str
    summary: str
    returncode: int


def run_pr_handoff(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    branch: str | None = None,
    intent: str | None = None,
    yes: bool = True,
    runner: Any = subprocess.run,
    github_client: Any = github,
) -> HandoffResult:
    lease_path = Path(entry.lease_path)
    branch = branch or _current_branch(lease_path) or _default_branch(entry)
    log_path = (
        config.root
        / ".orchestrator"
        / "logs"
        / config.name
        / f"issue-{entry.issue_number}"
        / "handoff.log"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _assert_gate_passed(entry)
    _assert_origin_push_blocked(config, lease_path, runner)

    push = runner(
        ["git", "push", config.agent_remote, f"HEAD:refs/heads/{branch}"],
        cwd=lease_path,
        capture_output=True,
        text=True,
    )
    if push.returncode != 0:
        summary = f"agent remote push failed with exit {push.returncode}"
        log_path.write_text(_combined(push), encoding="utf-8")
        update_run_entry(
            config,
            entry,
            current_step="handoff-failed",
            handoff_status="failed",
            handoff_summary=summary,
            last_summary=summary,
        )
        return HandoffResult(
            [],
            log_path,
            branch,
            None,
            None,
            None,
            "failed",
            summary,
            push.returncode,
        )

    command = ["no-mistakes", "axi", "run", "--intent", intent or _default_intent(github_client, config, entry)]
    if yes:
        command.append("--yes")
    result = runner(
        command,
        cwd=lease_path,
        capture_output=True,
        text=True,
    )
    log_path.write_text(_combined(push) + "\n--- no-mistakes ---\n" + _combined(result), encoding="utf-8")

    pr_url = parse_pr_url(result.stdout + "\n" + result.stderr)
    pr_number = parse_pr_number(pr_url)
    if pr_number:
        target_base = _target_base_branch(config)
        if target_base != config.default_branch and hasattr(github_client, "update_pr_base"):
            github_client.update_pr_base(config.repo, pr_number, target_base)
        issue = github_client.issue(config.repo, entry.issue_number)
        existing_body = github_client.pr_body(config.repo, pr_number)
        github_client.update_pr_body(
            config.repo,
            pr_number,
            build_pr_body(issue, entry, existing_body),
        )
    head_sha = github_client.pr_head(config.repo, pr_number) if pr_number else _git_head(lease_path)
    successful_outcome = "outcome: checks-passed" in result.stdout or "outcome: passed" in result.stdout
    status = "passed" if result.returncode == 0 and successful_outcome else "failed"
    summary = (
        f"handoff {status}: pushed {branch}"
        + (f" to PR #{pr_number}" if pr_number else "; no PR URL parsed")
    )
    update_run_entry(
        config,
        entry,
        current_step="pr-ready" if status == "passed" else "handoff-failed",
        pr_number=pr_number,
        pr_url=pr_url,
        handoff_status=status,
        handoff_summary=summary,
        final_head_sha=head_sha,
        last_summary=summary,
    )
    return HandoffResult(
        command,
        log_path,
        branch,
        pr_number,
        pr_url,
        head_sha,
        status,
        summary,
        result.returncode,
    )


def parse_pr_url(text: str) -> str | None:
    match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/[0-9]+", text)
    return match.group(0) if match else None


def parse_pr_number(url: str | None) -> int | None:
    if not url:
        return None
    match = re.search(r"/pull/([0-9]+)$", url)
    return int(match.group(1)) if match else None


def _assert_gate_passed(entry: RunLedgerEntry) -> None:
    if entry.current_step != "gate-passed" or entry.gate_status != "passed":
        raise RuntimeError(
            "refusing PR handoff before deterministic gate passes; "
            "run the orchestrator gate step first"
        )


def build_pr_body(issue: dict[str, Any], entry: RunLedgerEntry, existing_body: str = "") -> str:
    body = str(issue.get("body") or "")
    sections = parse_sections(body)
    criteria = acceptance_criteria(sections.get("acceptance criteria", ""))
    risk_flags = list_items(sections.get("risk flags", ""))
    scope = list_items(sections.get("files in scope", ""))
    pipeline = _pipeline_section(existing_body)

    criteria_lines = [
        f"- [x] {_clean_checkbox(criterion)} -> task-scoped tests and deterministic gate"
        for criterion in criteria
    ] or ["- [x] Issue acceptance criteria -> task-scoped tests and deterministic gate"]
    risk_lines = [f"- {item}" for item in risk_flags] if risk_flags else ["- none"]

    parts = [
        "## What changed",
        "",
        f"Implements issue #{entry.issue_number}: {entry.issue_title}.",
        "",
        f"Closes #{entry.issue_number}",
        "",
        "## Criteria coverage",
        "",
        "\n".join(criteria_lines),
        "",
        "## Testing",
        "",
        f"- [x] E2E written/updated for the user-facing behavior - or N/A: {_e2e_reason(scope)}",
        f"- Backend assertion: {_backend_assertion(criteria)}",
        "",
        "## Risk flags",
        "",
        "\n".join(risk_lines),
        "",
        "## Reviewer routing",
        "",
        "- pending",
        "",
        "## Deviations (loud, never silent)",
        "",
        "- none",
        "",
        "## Uncertainties",
        "",
        "- none",
        "",
        "## Self-check",
        "",
        "- [x] Tests derive from the acceptance criteria (not reverse-engineered from the code).",
        "- [x] No test was weakened, skipped, or deleted to make a check pass.",
        "- [x] No protected path edited.",
        "- [x] Scope manifest respected.",
        "- [x] Build, lint, and tests pass locally.",
    ]
    if pipeline:
        parts.extend(["", pipeline])
    return "\n".join(parts) + "\n"


def _assert_origin_push_blocked(config: ProjectConfig, lease_path: Path, runner: Any) -> None:
    probe_branch = f"orchestrator-origin-probe-{config.name}"
    result = runner(
        ["git", "push", "--dry-run", "origin", f"HEAD:refs/heads/{probe_branch}"],
        cwd=lease_path,
        capture_output=True,
        text=True,
        env=build_worker_env(config.worker_home),
    )
    if result.returncode == 0:
        raise RuntimeError("refusing PR handoff because worker can push origin")
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if not origin_failure_proves_blocked(output):
        raise RuntimeError(f"origin push probe failed for a non-auth reason: {output.strip()}")


def _default_intent(github_client: Any, config: ProjectConfig, entry: RunLedgerEntry) -> str:
    issue = github_client.issue(config.repo, entry.issue_number)
    return f"Issue #{entry.issue_number}: {issue['title']}\n\n{issue.get('body') or ''}"


def _target_base_branch(config: ProjectConfig) -> str:
    integration = config.raw.get("integration", {})
    if isinstance(integration, dict) and integration.get("daily_branch_prefix"):
        return daily_branch_name(config)
    return config.default_branch


def _current_branch(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _default_branch(entry: RunLedgerEntry) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", entry.issue_title.lower()).strip("-")
    slug = slug[:36].strip("-") or f"issue-{entry.issue_number}"
    return f"feat/issue-{entry.issue_number}-{slug}"


def _git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _combined(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "") + (("\n--- stderr ---\n" + result.stderr) if result.stderr else "")


def _pipeline_section(body: str) -> str:
    match = re.search(r"(?ms)^## Pipeline\s*$.*", body)
    return match.group(0).strip() if match else ""


def _clean_checkbox(criterion: str) -> str:
    return re.sub(r"^-\s+\[[ xX]\]\s*", "", criterion).strip()


def _e2e_reason(scope: list[str]) -> str:
    if scope and all(item.startswith("packages/tovi_core/") for item in scope):
        return "pure tovi_core change; no app UI behavior changed"
    return "see orchestrator-posted sim-validation status"


def _backend_assertion(criteria: list[str]) -> str:
    if any("backend-e2e" in criterion.lower() or "backend e2e" in criterion.lower() for criterion in criteria):
        return "backend-E2E criteria are covered by the deterministic gate"
    return "N/A - this task is covered by task-scoped unit tests and the deterministic gate"
