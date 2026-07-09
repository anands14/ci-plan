"""Deterministic operator reports."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

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


@dataclass(frozen=True)
class WatchRow:
    issue_number: int
    current_step: str
    agent: str
    model: str
    pr_number: int | None
    lease: str
    summary: str


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


def watch_rows(config: ProjectConfig) -> list[WatchRow]:
    rows = []
    for entry in sorted(_entries_by_issue(config).values(), key=lambda item: item.issue_number):
        agent, model = _agent_for_step(config, entry.current_step)
        rows.append(
            WatchRow(
                issue_number=entry.issue_number,
                current_step=entry.current_step,
                agent=agent,
                model=model,
                pr_number=entry.pr_number,
                lease=_short_path(entry.lease_path),
                summary=_short_reason(entry, limit=120),
            )
        )
    return rows


def watch_report(config: ProjectConfig) -> str:
    rows = watch_rows(config)
    if not rows:
        return "No orchestrator runs recorded.\n"

    headers = ("Issue", "Step", "Agent", "Model", "PR", "Lease", "Summary")
    values = [
        (
            f"#{row.issue_number}",
            row.current_step,
            row.agent,
            row.model,
            f"#{row.pr_number}" if row.pr_number else "-",
            row.lease,
            row.summary,
        )
        for row in rows
    ]
    widths = [
        max(len(headers[index]), *(len(value[index]) for value in values))
        for index in range(len(headers))
    ]
    lines = [_format_watch_row(headers, widths), _format_watch_row(tuple("-" * width for width in widths), widths)]
    lines.extend(_format_watch_row(value, widths) for value in values)
    return "\n".join(lines) + "\n"


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


def _agent_for_step(config: ProjectConfig, step: str) -> tuple[str, str]:
    if step.startswith("review"):
        return "reviewer", config.reviewer_model
    if step.startswith("sim-validation"):
        return "orchestrator", "deterministic"
    if step.startswith("gate") or step.startswith("handoff") or step.startswith("integration"):
        return "orchestrator", "deterministic"
    if step.startswith("advisor"):
        return "advisor", config.advisor_model
    return "implementer", config.implementer_model


def _short_path(value: str) -> str:
    path = Path(value)
    parts = path.parts
    if len(parts) <= 3:
        return value
    return str(Path("...") / Path(*parts[-3:]))


def _format_watch_row(values: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))


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
