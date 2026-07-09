"""Serialized daily-branch integration lane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from . import github
from .config import ProjectConfig
from .ledger import RunLedgerEntry, update_run_entry
from .queueing import LIFECYCLE_LABELS


PR_REQUIRED_CONTEXTS = ("gate", "test-discipline", "sim-validation", "review")
POST_MERGE_REQUIRED_CONTEXTS = ("gate", "test-discipline")
FINAL_REQUIRED_CONTEXTS = ("gate", "test-discipline", "daily-integration")
DAILY_STATUS_CONTEXT = "daily-integration"


@dataclass(frozen=True)
class BranchCheckResult:
    status: str
    checks: dict[str, str]
    reasons: list[str]
    attempts: int


@dataclass(frozen=True)
class RevertResult:
    status: str
    summary: str
    head_sha: str | None
    log_path: Path
    returncode: int


@dataclass(frozen=True)
class IntegrationResult:
    pr_number: int
    issue_number: int
    daily_branch: str
    status: str
    summary: str
    merged: bool
    reverted: bool
    branch_checks: BranchCheckResult | None
    revert_result: RevertResult | None


@dataclass(frozen=True)
class DailyBranchResult:
    daily_branch: str
    status: str
    summary: str
    commands: list[list[str]]


@dataclass(frozen=True)
class DailyPrResult:
    daily_branch: str
    pr_number: int | None
    pr_url: str | None
    body_path: Path
    status: str
    summary: str
    post_status_command: list[str] | None


def daily_branch_name(config: ProjectConfig, today: date | None = None) -> str:
    integration = _integration_config(config)
    prefix = str(integration.get("daily_branch_prefix", "day")).strip().strip("/")
    today = today or date.today()
    return f"{prefix}/{today.isoformat()}"


def ensure_daily_branch(
    config: ProjectConfig,
    *,
    branch: str | None = None,
    dry_run: bool = False,
    runner: Any = subprocess.run,
) -> DailyBranchResult:
    branch = branch or daily_branch_name(config)
    commands = [
        ["git", "-C", str(config.local_path), "fetch", "origin", config.default_branch],
        ["git", "-C", str(config.local_path), "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"],
    ]
    if dry_run:
        return DailyBranchResult(branch, "planned", f"would ensure daily branch {branch}", commands)

    executed: list[list[str]] = []
    fetch = runner(commands[0], capture_output=True, text=True)
    executed.append(commands[0])
    if fetch.returncode != 0:
        return DailyBranchResult(branch, "failed", _command_summary("fetch default branch", fetch), executed)

    exists = runner(commands[1], capture_output=True, text=True)
    executed.append(commands[1])
    if exists.returncode == 0:
        return DailyBranchResult(branch, "exists", f"daily branch already exists: {branch}", executed)

    create = [
        "git",
        "-C",
        str(config.local_path),
        "push",
        "origin",
        f"refs/remotes/origin/{config.default_branch}:refs/heads/{branch}",
    ]
    result = runner(create, capture_output=True, text=True)
    executed.append(create)
    if result.returncode != 0:
        return DailyBranchResult(branch, "failed", _command_summary("create daily branch", result), executed)
    return DailyBranchResult(branch, "created", f"created daily branch {branch}", executed)


def integrate_next_approved(
    config: ProjectConfig,
    *,
    branch: str | None = None,
    dry_run: bool = False,
    runner: Any = subprocess.run,
    github_client: Any = github,
    sleeper: Any = time.sleep,
) -> IntegrationResult | None:
    branch = branch or daily_branch_name(config)
    prs = github_client.approved_prs(config.repo, branch)
    for pr in prs:
        pr_number = int(pr["number"])
        entry = _entry_for_pr(config, pr_number)
        if entry is None:
            continue
        return integrate_pr(
            config,
            entry,
            pr_number=pr_number,
            branch=branch,
            dry_run=dry_run,
            runner=runner,
            github_client=github_client,
            sleeper=sleeper,
        )
    return None


def integrate_pr(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    pr_number: int | None = None,
    branch: str | None = None,
    dry_run: bool = False,
    runner: Any = subprocess.run,
    github_client: Any = github,
    sleeper: Any = time.sleep,
) -> IntegrationResult:
    pr_number = pr_number or entry.pr_number
    if not pr_number:
        raise RuntimeError("integration needs a PR number")
    branch = branch or daily_branch_name(config)
    pr = github_client.pr_details(config.repo, pr_number)
    eligibility = integration_eligibility(config, pr, branch, github_client=github_client)
    if eligibility.status != "pass":
        return IntegrationResult(
            pr_number,
            entry.issue_number,
            branch,
            eligibility.status,
            "; ".join(eligibility.reasons),
            False,
            False,
            eligibility,
            None,
        )

    head_before = str(pr.get("headRefOid") or github_client.pr_head(config.repo, pr_number))
    head_after = github_client.pr_head(config.repo, pr_number)
    if head_before != head_after:
        summary = f"PR head changed while checking ({head_before} -> {head_after}); retry integration"
        return IntegrationResult(pr_number, entry.issue_number, branch, "failed", summary, False, False, None, None)

    if dry_run:
        summary = f"would squash-merge PR #{pr_number} into {branch} and run post-merge checks"
        return IntegrationResult(pr_number, entry.issue_number, branch, "planned", summary, False, False, None, None)

    if pr.get("state") == "MERGED":
        checks = wait_for_branch_checks(
            config,
            branch,
            github_client=github_client,
            sleeper=sleeper,
        )
        if checks.status == "pass":
            summary = f"integrated PR #{pr_number} into {branch}; post-merge checks passed; closed issue #{entry.issue_number}"
            _set_pr_label(github_client, config, pr_number, "integrated", remove=["integrating", "integration-failed"])
            _set_issue_state(github_client, config, entry.issue_number, "integrated")
            if hasattr(github_client, "close_issue"):
                github_client.close_issue(config.repo, entry.issue_number, reason="completed")
            update_run_entry(
                config,
                entry,
                current_step="integrated",
                integration_branch=branch,
                integration_status="passed",
                integration_summary=summary,
                last_summary=summary,
            )
            return IntegrationResult(pr_number, entry.issue_number, branch, "passed", summary, True, False, checks, None)
        summary = f"already-merged PR #{pr_number} left {branch} checks {checks.status}: {', '.join(checks.reasons)}"
        return IntegrationResult(pr_number, entry.issue_number, branch, "failed", summary, True, False, checks, None)

    _set_pr_label(github_client, config, pr_number, "integrating", remove=["integration-failed", "integrated"])
    update_run_entry(
        config,
        entry,
        current_step="integrating",
        integration_branch=branch,
        integration_status="merging",
        integration_summary=f"merging PR #{pr_number} into {branch}",
        last_summary=f"merging PR #{pr_number} into {branch}",
    )

    merge = runner(
        ["gh", "pr", "merge", str(pr_number), "-R", config.repo, "--squash"],
        capture_output=True,
        text=True,
    )
    if merge.returncode != 0:
        summary = _command_summary(f"merge PR #{pr_number}", merge)
        _set_pr_label(github_client, config, pr_number, "integration-failed", remove=["integrating", "integrated"])
        update_run_entry(
            config,
            entry,
            current_step="integration-failed",
            integration_branch=branch,
            integration_status="merge-failed",
            integration_summary=summary,
            last_summary=summary,
        )
        return IntegrationResult(pr_number, entry.issue_number, branch, "failed", summary, False, False, None, None)

    checks = wait_for_branch_checks(
        config,
        branch,
        github_client=github_client,
        sleeper=sleeper,
    )
    if checks.status == "pass":
        summary = f"integrated PR #{pr_number} into {branch}; post-merge checks passed; closed issue #{entry.issue_number}"
        _set_pr_label(github_client, config, pr_number, "integrated", remove=["integrating", "integration-failed"])
        _set_issue_state(github_client, config, entry.issue_number, "integrated")
        _close_issue(github_client, config, entry.issue_number)
        update_run_entry(
            config,
            entry,
            current_step="integrated",
            integration_branch=branch,
            integration_status="passed",
            integration_summary=summary,
            integration_head_sha=github_client.branch_head(config.repo, branch),
            last_summary=summary,
        )
        return IntegrationResult(pr_number, entry.issue_number, branch, "passed", summary, True, False, checks, None)

    reason = "; ".join(checks.reasons) or "post-merge checks failed"
    revert_result = revert_daily_head(
        config,
        branch,
        pr_number=pr_number,
        reason=reason,
        runner=runner,
    )
    reverted = revert_result.status == "reverted"
    status = "reverted" if reverted else "revert-failed"
    summary = (
        f"PR #{pr_number} broke {branch}: {reason}; {revert_result.summary}"
        if reverted
        else f"PR #{pr_number} broke {branch}: {reason}; revert failed: {revert_result.summary}"
    )
    _set_pr_label(github_client, config, pr_number, "integration-failed", remove=["integrating", "integrated"])
    _set_issue_state(github_client, config, entry.issue_number, "integration-failed")
    _notify_integration_failure(github_client, config, entry, pr_number, branch, reason, revert_result)
    update_run_entry(
        config,
        entry,
        current_step="integration-failed",
        integration_branch=branch,
        integration_status=status,
        integration_summary=summary,
        integration_revert_sha=revert_result.head_sha,
        last_summary=summary,
    )
    return IntegrationResult(pr_number, entry.issue_number, branch, status, summary, True, reverted, checks, revert_result)


def integration_eligibility(
    config: ProjectConfig,
    pr: dict[str, Any],
    branch: str,
    *,
    github_client: Any = github,
) -> BranchCheckResult:
    reasons: list[str] = []
    pr_number = int(pr["number"])
    labels = _label_names(pr.get("labels", []))
    if pr.get("isDraft"):
        reasons.append("PR is still a draft")
    if pr.get("baseRefName") != branch:
        reasons.append(f"PR base is {pr.get('baseRefName') or 'unknown'}, expected {branch}")
    if "approved" not in labels:
        reasons.append("PR is missing approved label")
    if "clean" not in labels and "flagged" not in labels:
        reasons.append("PR is missing clean/flagged routing")
    structural_reasons = list(reasons)
    checks, _green = github_client.pr_checks(config.repo, pr_number)
    check_decision = check_decision_for(required_pr_contexts(config), checks)
    reasons.extend(check_decision.reasons)
    status = "failed" if structural_reasons else check_decision.status
    if not reasons and check_decision.status == "pass":
        status = "pass"
    return BranchCheckResult(status, checks, reasons, 1)


def wait_for_branch_checks(
    config: ProjectConfig,
    branch: str,
    *,
    github_client: Any = github,
    sleeper: Any = time.sleep,
) -> BranchCheckResult:
    integration = _integration_config(config)
    attempts = int(integration.get("post_merge_poll_attempts", 60))
    interval = float(integration.get("post_merge_poll_seconds", 30))
    required = post_merge_required_contexts(config)
    last = BranchCheckResult("pending", {}, ["checks have not run yet"], 0)
    for attempt in range(attempts + 1):
        checks, _green = github_client.branch_checks(config.repo, branch)
        decision = check_decision_for(required, checks)
        last = BranchCheckResult(decision.status, checks, decision.reasons, attempt + 1)
        if decision.status in {"pass", "failed"}:
            return last
        if attempt < attempts:
            sleeper(interval)
    return BranchCheckResult("failed", last.checks, last.reasons or ["timed out waiting for branch checks"], last.attempts)


def check_decision_for(required: tuple[str, ...], checks: dict[str, str]) -> BranchCheckResult:
    missing: list[str] = []
    pending: list[str] = []
    failing: list[str] = []

    for name in required:
        state = _normalize_check_state(checks.get(name))
        if state == "missing":
            missing.append(name)
        elif state in {"pending", "queued"}:
            pending.append(name)
        elif state != "pass":
            failing.append(name)

    for name, value in checks.items():
        if name in required:
            continue
        state = _normalize_check_state(value)
        if state in {"pending", "queued"}:
            pending.append(name)
        elif state not in {"pass", "skipping"}:
            failing.append(name)

    if failing:
        return BranchCheckResult("failed", checks, [f"check failed: {name}" for name in sorted(set(failing))], 1)
    if missing or pending:
        reasons = [f"required check missing: {name}" for name in missing]
        reasons.extend(f"check pending: {name}" for name in sorted(set(pending)))
        return BranchCheckResult("pending", checks, reasons, 1)
    return BranchCheckResult("pass", checks, [], 1)


def revert_daily_head(
    config: ProjectConfig,
    branch: str,
    *,
    pr_number: int,
    reason: str,
    runner: Any = subprocess.run,
) -> RevertResult:
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-")
    worktree = config.root / ".orchestrator" / "integration-worktrees" / config.name / f"{safe_branch}-pr-{pr_number}"
    log_path = config.root / ".orchestrator" / "logs" / config.name / f"integration-pr-{pr_number}.log"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    commands = [
        ["git", "-C", str(config.local_path), "fetch", "origin", branch],
        ["git", "-C", str(config.local_path), "worktree", "add", "--force", "--detach", str(worktree), f"origin/{branch}"],
        ["git", "revert", "--no-edit", "HEAD"],
        ["git", "rev-parse", "HEAD"],
        ["git", "push", "origin", f"HEAD:refs/heads/{branch}"],
    ]
    log_path.write_text(f"reverting PR #{pr_number} from {branch}\nreason: {reason}\n", encoding="utf-8")
    head_sha: str | None = None
    try:
        for command in commands:
            cwd = worktree if command[0] == "git" and "-C" not in command else None
            result = runner(command, cwd=cwd, capture_output=True, text=True)
            _append_command_log(log_path, command, result)
            if result.returncode != 0:
                return RevertResult("failed", _command_summary("revert daily branch", result), head_sha, log_path, result.returncode)
            if command[:3] == ["git", "rev-parse", "HEAD"]:
                head_sha = result.stdout.strip() or None
        return RevertResult("reverted", f"reverted PR #{pr_number} from {branch}", head_sha, log_path, 0)
    finally:
        cleanup = ["git", "-C", str(config.local_path), "worktree", "remove", "--force", str(worktree)]
        cleanup_result = runner(cleanup, capture_output=True, text=True)
        _append_command_log(log_path, cleanup, cleanup_result)


def open_daily_pr(
    config: ProjectConfig,
    *,
    branch: str | None = None,
    post: bool = False,
    dry_run: bool = False,
    runner: Any = subprocess.run,
    github_client: Any = github,
) -> DailyPrResult:
    branch = branch or daily_branch_name(config)
    entries = _entries_for_branch(config, branch)
    if not entries:
        raise RuntimeError(f"no integrated entries found for {branch}")
    body = build_daily_pr_body(config, branch, entries)
    body_path = config.root / ".orchestrator" / "daily-prs" / f"{config.name}-{_branch_slug(branch)}.md"
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_text(body, encoding="utf-8")
    title = f"Daily integration {branch.rsplit('/', 1)[-1]}"

    if dry_run:
        return DailyPrResult(branch, None, None, body_path, "planned", f"would open daily PR from {branch}", None)

    existing = github_client.find_pr(config.repo, base=config.default_branch, head=branch)
    if existing:
        pr_number = int(existing["number"])
        github_client.update_pr_body(config.repo, pr_number, body)
        pr_url = existing.get("url")
        status = "updated"
    else:
        created = github_client.create_pr(
            config.repo,
            base=config.default_branch,
            head=branch,
            title=title,
            body_path=body_path,
        )
        pr_number = int(created["number"])
        pr_url = created.get("url")
        status = "created"

    post_command = None
    if post:
        head_sha = github_client.branch_head(config.repo, branch)
        post_command = [
            str(config.root / "bin" / "post-status"),
            "--sha",
            head_sha,
            "--context",
            DAILY_STATUS_CONTEXT,
            "--state",
            "success",
            "--description",
            f"{len(entries)} PR(s) integrated through serialized day branch",
            "--repo",
            config.repo,
        ]
        result = runner(post_command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(_command_summary("post daily integration status", result))

    summary = f"{status} daily PR #{pr_number} from {branch} to {config.default_branch}"
    return DailyPrResult(branch, pr_number, pr_url, body_path, status, summary, post_command)


def build_daily_pr_body(config: ProjectConfig, branch: str, entries: list[RunLedgerEntry]) -> str:
    integrated = [entry for entry in entries if entry.integration_status == "passed"]
    held = [entry for entry in entries if entry.integration_status and entry.integration_status != "passed"]
    flagged = [entry for entry in integrated if entry.review_routing == "flagged"]
    lines = [
        "## Summary",
        "",
        f"Daily integration branch `{branch}` into `{config.default_branch}`.",
        "",
        "## Included Agent PRs",
        "",
    ]
    if integrated:
        for entry in integrated:
            pr = f"PR #{entry.pr_number}" if entry.pr_number else "PR n/a"
            routing = entry.review_routing or "n/a"
            lines.append(f"- {pr} - issue #{entry.issue_number} - {routing} - {entry.issue_title}")
    else:
        lines.append("- none")
    lines.extend(["", "## Needs Human Attention", ""])
    if flagged:
        for entry in flagged:
            lines.append(f"- PR #{entry.pr_number} - issue #{entry.issue_number} - {entry.review_summary or 'flagged'}")
    else:
        lines.append("- none")
    lines.extend(["", "## Reverted Or Held Back", ""])
    if held:
        for entry in held:
            lines.append(f"- PR #{entry.pr_number} - issue #{entry.issue_number} - {entry.integration_summary or entry.current_step}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Final Merge Gate",
            "",
            "- [ ] GitHub CI on this PR is green.",
            "- [ ] `daily-integration` status is green.",
            "- [ ] Human approves the final PR to main.",
            "",
            "## Integrated Issues",
            "",
        ]
    )
    if integrated:
        for entry in integrated:
            lines.append(f"- issue #{entry.issue_number} - closed after daily-branch integration")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def required_pr_contexts(config: ProjectConfig) -> tuple[str, ...]:
    return _contexts(config, "required_pr_contexts", PR_REQUIRED_CONTEXTS)


def post_merge_required_contexts(config: ProjectConfig) -> tuple[str, ...]:
    return _contexts(config, "post_merge_required_contexts", POST_MERGE_REQUIRED_CONTEXTS)


def final_required_contexts(config: ProjectConfig) -> tuple[str, ...]:
    return _contexts(config, "final_required_contexts", FINAL_REQUIRED_CONTEXTS)


def _integration_config(config: ProjectConfig) -> dict[str, Any]:
    value = config.raw.get("integration", {})
    return value if isinstance(value, dict) else {}


def _contexts(config: ProjectConfig, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = _integration_config(config).get(key)
    if not value:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise RuntimeError(f"integration.{key} must be a non-empty list of strings")
    return tuple(item.strip() for item in value)


def _normalize_check_state(value: str | None) -> str:
    if not value:
        return "missing"
    normalized = value.strip().lower()
    if normalized in {"pass", "passed", "success", "successful"}:
        return "pass"
    if normalized in {"skipping", "skipped", "neutral"}:
        return "skipping"
    if normalized in {"pending", "queued", "in_progress", "in-progress", "waiting", "requested"}:
        return "pending"
    return "fail"


def _label_names(labels: list[Any]) -> set[str]:
    names: set[str] = set()
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and label.get("name"):
            names.add(str(label["name"]))
    return names


def _set_pr_label(github_client: Any, config: ProjectConfig, pr_number: int, label: str, *, remove: list[str]) -> None:
    if hasattr(github_client, "set_pr_labels"):
        github_client.set_pr_labels(config.repo, pr_number, label, remove=remove)


def _set_issue_state(github_client: Any, config: ProjectConfig, issue_number: int, label: str) -> None:
    if hasattr(github_client, "set_state"):
        github_client.set_state(
            config.repo,
            issue_number,
            label,
            remove=[item for item in LIFECYCLE_LABELS if item != label],
        )


def _close_issue(github_client: Any, config: ProjectConfig, issue_number: int) -> None:
    if hasattr(github_client, "close_issue"):
        github_client.close_issue(config.repo, issue_number, reason="completed")


def _notify_integration_failure(
    github_client: Any,
    config: ProjectConfig,
    entry: RunLedgerEntry,
    pr_number: int,
    branch: str,
    reason: str,
    revert_result: RevertResult,
) -> None:
    body = "\n".join(
        [
            f"Integration into `{branch}` failed after PR #{pr_number} was merged.",
            "",
            f"Breaking cause: {reason}",
            f"Revert status: {revert_result.status}",
            f"Revert log: `{revert_result.log_path}`",
            "",
            "Please fix the issue and raise a replacement PR against the daily branch.",
        ]
    )
    if hasattr(github_client, "comment_pr"):
        github_client.comment_pr(config.repo, pr_number, body)
    if hasattr(github_client, "comment_issue"):
        github_client.comment_issue(config.repo, entry.issue_number, body)


def _entry_for_pr(config: ProjectConfig, pr_number: int) -> RunLedgerEntry | None:
    runs_dir = config.root / ".orchestrator" / "runs"
    if not runs_dir.is_dir():
        return None
    for path in sorted(runs_dir.glob(f"{config.name}-issue-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = RunLedgerEntry(**data)
        if entry.pr_number == pr_number:
            return entry
    return None


def _entries_for_branch(config: ProjectConfig, branch: str) -> list[RunLedgerEntry]:
    runs_dir = config.root / ".orchestrator" / "runs"
    if not runs_dir.is_dir():
        return []
    entries: list[RunLedgerEntry] = []
    for path in sorted(runs_dir.glob(f"{config.name}-issue-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = RunLedgerEntry(**data)
        if entry.integration_branch == branch:
            entries.append(entry)
    return entries


def _branch_slug(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", branch).strip("-")


def _append_command_log(path: Path, command: list[str], result: subprocess.CompletedProcess) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("\n$ " + " ".join(command) + "\n")
        if result.stdout:
            f.write(result.stdout)
        if result.stderr:
            f.write("\n--- stderr ---\n")
            f.write(result.stderr)
        f.write(f"\n(exit {result.returncode})\n")


def _command_summary(action: str, result: subprocess.CompletedProcess) -> str:
    output = " ".join(((result.stderr or "") + " " + (result.stdout or "")).split())
    if len(output) > 180:
        output = output[:179] + "..."
    return f"{action} failed with exit {result.returncode}" + (f": {output}" if output else "")
