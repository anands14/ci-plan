"""Orchestrator-owned validation lanes."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterator

from . import github
from .config import ProjectConfig
from .ledger import RunLedgerEntry, update_run_entry


DETERMINISTIC_CONTEXTS = ("gate", "test-discipline")


@dataclass(frozen=True)
class LaneResult:
    command: list[str]
    log_path: Path
    status: str
    summary: str
    returncode: int
    routing: str | None = None
    head_sha: str | None = None


def run_sim_validation(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    pr_number: int | None = None,
    post: bool = False,
    platform: str | None = None,
    runner: Any = subprocess.run,
) -> LaneResult:
    pr_number = pr_number or entry.pr_number
    if not pr_number:
        raise RuntimeError("sim-validation needs a PR number")

    command = [
        str(config.root / "bin" / "sim-validate"),
        "--pr",
        str(pr_number),
        "--repo",
        config.repo,
        "--config",
        str(config.path),
    ]
    if platform:
        command += ["--platform", platform]
    if post:
        command.append("--post")

    log_path = _lane_log_path(config, entry, "sim-validation")
    with _single_lane_lock(config, "sim-validation"):
        result = runner(
            command,
            cwd=config.root,
            capture_output=True,
            text=True,
        )
    log_path.write_text(_combined(result), encoding="utf-8")

    status = parse_sim_validation_status(result.stdout + "\n" + result.stderr)
    if not status:
        status = "success" if result.returncode == 0 else "unknown"
    head_sha = parse_sha(result.stdout + "\n" + result.stderr)
    summary = f"sim-validation {status}" + (f" at {head_sha}" if head_sha else "")
    update_run_entry(
        config,
        entry,
        current_step="sim-validation-passed" if status == "success" and result.returncode == 0 else "sim-validation-failed",
        pr_number=pr_number,
        sim_validation_status=status,
        sim_validation_summary=summary,
        final_head_sha=head_sha or entry.final_head_sha,
        last_summary=summary,
    )
    return LaneResult(command, log_path, status, summary, result.returncode, head_sha=head_sha)


def run_review(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    pr_number: int | None = None,
    post: bool = False,
    model: str | None = None,
    runner: Any = subprocess.run,
    github_client: Any = github,
) -> LaneResult:
    pr_number = pr_number or entry.pr_number
    if not pr_number:
        raise RuntimeError("review needs a PR number")
    checks, _green = github_client.pr_checks(config.repo, pr_number)
    missing_or_bad = [
        context
        for context in DETERMINISTIC_CONTEXTS
        if checks.get(context) != "pass"
    ]
    if missing_or_bad:
        raise RuntimeError(
            "review waits for green deterministic gates: "
            + ", ".join(f"{name}={checks.get(name, 'missing')}" for name in missing_or_bad)
        )

    head_before = github_client.pr_head(config.repo, pr_number)
    command = [
        str(config.root / "bin" / "review"),
        "--pr",
        str(pr_number),
        "--issue",
        str(entry.issue_number),
        "--repo",
        config.repo,
    ]
    if model:
        command += ["--model", model]
    if post:
        command.append("--post")

    log_path = _lane_log_path(config, entry, "review")
    result = runner(
        command,
        cwd=config.root,
        capture_output=True,
        text=True,
    )
    log_path.write_text(_combined(result), encoding="utf-8")

    text = result.stdout + "\n" + result.stderr
    verdict, routing, status = parse_review_result(text)
    if not verdict:
        verdict = "unknown"
    if routing not in ("clean", "flagged"):
        raise RuntimeError(f"review did not return clean/flagged routing: {routing or 'missing'}")
    head_after = github_client.pr_head(config.repo, pr_number)
    if head_after != head_before:
        raise RuntimeError(f"PR head changed during review ({head_before} -> {head_after})")
    github_client.set_pr_labels(config.repo, pr_number, routing, remove=["clean", "flagged"])
    if verdict == "approve":
        github_client.set_state(config.repo, entry.issue_number, "approved", ["in-progress", "in-review"])
    elif verdict in ("request-changes", "request_changes", "changes"):
        github_client.set_state(config.repo, entry.issue_number, "in-progress", ["in-review"])

    summary = f"review {verdict}/{routing} -> {status or 'unknown'} at {head_after}"
    update_run_entry(
        config,
        entry,
        current_step="review-passed" if verdict == "approve" else "review-requested-changes",
        pr_number=pr_number,
        review_status=verdict,
        review_routing=routing,
        review_summary=summary,
        final_head_sha=head_after,
        last_summary=summary,
    )
    return LaneResult(command, log_path, verdict, summary, result.returncode, routing=routing, head_sha=head_after)


def parse_sim_validation_status(text: str) -> str | None:
    match = re.search(r"sim-validation:\s+(success|failure|error)", text)
    return match.group(1) if match else None


def parse_review_result(text: str) -> tuple[str | None, str | None, str | None]:
    match = re.search(
        r"review verdict:\s+([A-Za-z_-]+)(?:/([A-Za-z_-]+))?\s+->\s+([A-Za-z_-]+)",
        text,
    )
    if not match:
        return None, None, None
    return match.group(1), match.group(2), match.group(3)


def parse_sha(text: str) -> str | None:
    match = re.search(r"sha:\s*([0-9a-f]{40})", text)
    return match.group(1) if match else None


@contextmanager
def _single_lane_lock(config: ProjectConfig, lane: str) -> Iterator[None]:
    lock_dir = config.root / ".orchestrator" / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{lane}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"{lane} lane is already running: {lock_path}") from exc
    try:
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        yield
    finally:
        os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _lane_log_path(config: ProjectConfig, entry: RunLedgerEntry, lane: str) -> Path:
    path = (
        config.root
        / ".orchestrator"
        / "logs"
        / config.name
        / f"issue-{entry.issue_number}"
        / f"{lane}.log"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _combined(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "") + (("\n--- stderr ---\n" + result.stderr) if result.stderr else "")
