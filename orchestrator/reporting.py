"""Deterministic operator reports."""

from __future__ import annotations

from dataclasses import dataclass
import json

from . import github
from .config import ProjectConfig
from .ledger import RunLedgerEntry
from .reconcile import ReconcileItem, reconcile


@dataclass(frozen=True)
class EveningRow:
    bucket: str
    issue_number: int
    pr_number: int | None
    check_state: str
    routing: str
    reason: str


def evening_rows(config: ProjectConfig, *, github_client=github) -> list[EveningRow]:
    entries = _entries_by_issue(config)
    report = reconcile(config, github_client=github_client)
    rows: list[EveningRow] = []
    for item in report.items:
        entry = entries.get(item.issue_number)
        if entry is None:
            continue
        bucket = _bucket(entry, item)
        if bucket is None:
            continue
        rows.append(
            EveningRow(
                bucket=bucket,
                issue_number=item.issue_number,
                pr_number=item.pr_number,
                check_state=_check_state(item.checks),
                routing=entry.review_routing or _routing_from_labels(item.labels),
                reason=_short_reason(entry),
            )
        )
    return rows


def evening_report(config: ProjectConfig, *, github_client=github) -> str:
    buckets = [
        "clean PRs",
        "flagged PRs",
        "integrated PRs",
        "integration failures",
        "stuck tasks",
        "deferred tasks",
    ]
    rows = evening_rows(config, github_client=github_client)
    lines = ["# Evening Checklist", ""]
    for bucket in buckets:
        lines.append(f"## {bucket}")
        bucket_rows = [row for row in rows if row.bucket == bucket]
        if not bucket_rows:
            lines.append("- none")
        else:
            for row in bucket_rows:
                pr = f"PR #{row.pr_number}" if row.pr_number else "PR n/a"
                lines.append(
                    f"- issue #{row.issue_number}; {pr}; checks={row.check_state}; "
                    f"routing={row.routing or 'n/a'}; reason={row.reason}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _entries_by_issue(config: ProjectConfig) -> dict[int, RunLedgerEntry]:
    runs_dir = config.root / ".orchestrator" / "runs"
    if not runs_dir.is_dir():
        return {}
    entries = {}
    for path in sorted(runs_dir.glob(f"{config.name}-issue-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = RunLedgerEntry(**data)
        entries[entry.issue_number] = entry
    return entries


def _bucket(entry: RunLedgerEntry, item: ReconcileItem) -> str | None:
    routing = entry.review_routing or _routing_from_labels(item.labels)
    if entry.current_step in ("review-passed", "approved") and routing == "clean":
        return "clean PRs"
    if entry.current_step in ("review-passed", "approved") and routing == "flagged":
        return "flagged PRs"
    if entry.current_step == "integrated" or "integrated" in item.labels:
        return "integrated PRs"
    if entry.current_step == "integration-failed" or "integration-failed" in item.labels:
        return "integration failures"
    if entry.current_step == "stuck" or "stuck" in item.labels:
        return "stuck tasks"
    if entry.current_step == "deferred" or "deferred" in item.labels:
        return "deferred tasks"
    return None


def _routing_from_labels(labels: list[str]) -> str:
    if "clean" in labels:
        return "clean"
    if "flagged" in labels:
        return "flagged"
    return ""


def _check_state(checks: dict[str, str]) -> str:
    if not checks:
        return "none"
    required = ("gate", "test-discipline", "sim-validation", "review")
    parts = [f"{name}:{checks.get(name, 'missing')}" for name in required]
    return ",".join(parts)


def _short_reason(entry: RunLedgerEntry, limit: int = 96) -> str:
    reason = (
        entry.integration_summary
        or entry.review_summary
        or entry.base_summary
        or entry.sim_validation_summary
        or entry.gate_summary
        or entry.last_summary
        or entry.current_step
    )
    reason = " ".join(reason.split())
    return reason if len(reason) <= limit else reason[: limit - 1] + "..."
