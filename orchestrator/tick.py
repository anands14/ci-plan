"""One full orchestrator tick: advance the frontier, claim everything safe,
drive each claimed issue through the pipeline in parallel, then serially
integrate whatever is approved and eligible.

This is the "just point it at a range of issues" entry point: nothing here
takes a wave-plan as input. The frontier and the collision serialization are
computed from data already on the issues (`Blocked by #N` edges, `Files in
scope` manifests) - see `queueing.advance_ready_frontier` and
`queueing.claim_all_ready`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from . import github
from .agents import run_implementer_once
from .config import ProjectConfig
from .gate import run_gate
from .handoff import run_pr_handoff
from .integration import integrate_next_approved
from .ledger import read_run_entry
from .queueing import advance_ready_frontier, claim_all_ready
from .tools import acquire_treehouse_lease, release_treehouse_lease
from .ledger import write_run_entry
from .validation import run_review, run_sim_validation


@dataclass(frozen=True)
class IssuePipelineResult:
    issue_number: int
    stage: str
    summary: str


@dataclass(frozen=True)
class TickResult:
    promoted: list[int]
    claimed: list[int]
    deferred: list[int]
    pipeline_results: list[IssuePipelineResult]
    integrated: list[int]


def run_one_issue_pipeline(
    config: ProjectConfig,
    issue_number: int,
    *,
    github_client: Any = github,
) -> IssuePipelineResult:
    """implement -> gate -> handoff -> sim-validate -> review, stopping at the first non-green stage."""
    entry = read_run_entry(config, issue_number)
    impl = run_implementer_once(config, entry, github_client=github_client)
    if impl.returncode != 0:
        return IssuePipelineResult(issue_number, "implementer", impl.summary)

    entry = read_run_entry(config, issue_number)
    gate = run_gate(config, entry)
    if not gate.passed:
        return IssuePipelineResult(issue_number, "gate", gate.summary)

    entry = read_run_entry(config, issue_number)
    handoff = run_pr_handoff(config, entry, github_client=github_client)
    if handoff.status != "passed":
        return IssuePipelineResult(issue_number, "handoff", handoff.summary)

    entry = read_run_entry(config, issue_number)
    run_sim_validation(config, entry, post=True)

    entry = read_run_entry(config, issue_number)
    review = run_review(config, entry, post=True, github_client=github_client)
    return IssuePipelineResult(issue_number, "review", review.summary)


def run_tick(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    github_client: Any = github,
    max_workers: int | None = None,
    pipeline_runner: Any = run_one_issue_pipeline,
    lease_func: Any = acquire_treehouse_lease,
    release_func: Any = release_treehouse_lease,
    write_entry_func: Any = write_run_entry,
) -> TickResult:
    promoted = advance_ready_frontier(config, dry_run=dry_run, github_client=github_client)
    batch = claim_all_ready(
        config,
        dry_run=dry_run,
        github_client=github_client,
        lease_func=lease_func,
        release_func=release_func,
        write_entry_func=write_entry_func,
    )
    claimed_numbers = [c.issue_number for c in batch.claimed if c.issue_number is not None]

    pipeline_results: list[IssuePipelineResult] = []
    if not dry_run and claimed_numbers:
        workers = max_workers or len(claimed_numbers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(pipeline_runner, config, number, github_client=github_client): number
                for number in claimed_numbers
            }
            for future in as_completed(futures):
                number = futures[future]
                try:
                    pipeline_results.append(future.result())
                except Exception as exc:
                    pipeline_results.append(IssuePipelineResult(number, "pipeline", f"failed: {exc}"))

    integrated: list[int] = []
    if not dry_run:
        while True:
            result = integrate_next_approved(config, github_client=github_client)
            if result is None or result.status != "passed":
                break
            integrated.append(result.issue_number)

    return TickResult(
        promoted=promoted,
        claimed=claimed_numbers,
        deferred=batch.deferred,
        pipeline_results=pipeline_results,
        integrated=integrated,
    )
