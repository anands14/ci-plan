"""Local run ledger for resumable orchestrator state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from .config import ProjectConfig


@dataclass(frozen=True)
class RunLedgerEntry:
    project: str
    repo: str
    issue_number: int
    issue_title: str
    lease_path: str
    current_step: str
    log_path: str
    claimed_at: str
    codex_session_id: str | None = None
    prompt_path: str | None = None
    result_path: str | None = None
    head_before: str | None = None
    head_after: str | None = None
    last_summary: str | None = None
    gate_status: str | None = None
    gate_summary: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    handoff_status: str | None = None
    handoff_summary: str | None = None
    final_head_sha: str | None = None
    sim_validation_status: str | None = None
    sim_validation_summary: str | None = None
    review_status: str | None = None
    review_routing: str | None = None
    review_summary: str | None = None
    base_status: str | None = None
    base_summary: str | None = None
    integration_branch: str | None = None
    integration_status: str | None = None
    integration_summary: str | None = None
    integration_head_sha: str | None = None
    integration_revert_sha: str | None = None
    worker_pid: int | None = None
    advisor_question: str | None = None
    advisor_summary: str | None = None


def make_run_entry(
    config: ProjectConfig,
    issue: dict,
    lease_path: Path,
    step: str = "claimed",
) -> RunLedgerEntry:
    log_path = (
        config.root
        / ".orchestrator"
        / "logs"
        / config.name
        / f"issue-{issue['number']}.log"
    )
    return RunLedgerEntry(
        project=config.name,
        repo=config.repo,
        issue_number=int(issue["number"]),
        issue_title=str(issue["title"]),
        lease_path=str(lease_path),
        current_step=step,
        log_path=str(log_path),
        claimed_at=datetime.now(timezone.utc).isoformat(),
    )


def write_run_entry(config: ProjectConfig, entry: RunLedgerEntry) -> Path:
    runs_dir = config.root / ".orchestrator" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    Path(entry.log_path).parent.mkdir(parents=True, exist_ok=True)

    path = runs_dir / f"{entry.project}-issue-{entry.issue_number}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(asdict(entry), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def run_entry_path(config: ProjectConfig, issue_number: int) -> Path:
    return (
        config.root
        / ".orchestrator"
        / "runs"
        / f"{config.name}-issue-{issue_number}.json"
    )


def read_run_entry(config: ProjectConfig, issue_number: int) -> RunLedgerEntry:
    path = run_entry_path(config, issue_number)
    if not path.is_file():
        raise FileNotFoundError(f"run ledger not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return RunLedgerEntry(**data)


def update_run_entry(config: ProjectConfig, entry: RunLedgerEntry, **changes: object) -> Path:
    return write_run_entry(config, replace(entry, **changes))
