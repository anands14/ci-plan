"""Command line entry point for the local orchestrator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from .agents import checkpoint_entry, run_implementer_once
from .cadence import daily_report, run_nightly_e2e, weekly_retro
from .concurrency import read_concurrency_policy, set_concurrency_stage
from .config import ConfigError, load_project_config
from .context_metrics import analyze_context_run
from .freshness import run_base_refresh
from .gate import run_gate
from .handoff import run_pr_handoff
from .heartbeat import check_heartbeat, write_heartbeat
from .integration import ensure_daily_branch, integrate_next_approved, integrate_pr, open_daily_pr
from .ledger import read_run_entry
from .outcomes import resume_deferred
from .preflight import failed, format_results, run_preflight
from .queueing import advance_ready_frontier, claim_all_ready, claim_next_ready
from .reconcile import reconcile, record_wakeup
from .reporting import evening_report
from .safety import ADVANCING_COMMANDS, is_paused, pause_message
from .tick import run_tick
from .validation import run_review, run_sim_validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="framework repo root; defaults to this checkout",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="run Phase 0c M0 checks without claiming work",
    )
    preflight.add_argument("--project", required=True)

    claim_next = subparsers.add_parser(
        "claim-next",
        help="run Phase 0c M1 queue validation and claim one ready issue",
    )
    claim_next.add_argument("--project", required=True)
    claim_next.add_argument(
        "--dry-run",
        action="store_true",
        help="show queue decisions without editing labels, leasing, or writing ledger",
    )
    advance_frontier = subparsers.add_parser(
        "advance-frontier",
        help="promote blocked issues to ready once every #N blocker they declare is closed",
    )
    advance_frontier.add_argument("--project", required=True)
    advance_frontier.add_argument("--dry-run", action="store_true")
    claim_all = subparsers.add_parser(
        "claim-all",
        help="claim every currently-safe ready issue - no fixed worker-count cap",
    )
    claim_all.add_argument("--project", required=True)
    claim_all.add_argument(
        "--dry-run",
        action="store_true",
        help="show claim/defer/reject decisions without editing labels, leasing, or writing ledger",
    )
    run = subparsers.add_parser(
        "run",
        help="one full tick (advance frontier, claim-all, implement+gate+handoff+sim-validate+review "
        "in parallel, then serially integrate) - or loop until nothing is left with --poll",
    )
    run.add_argument("--project", required=True)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--poll",
        action="store_true",
        help="keep ticking until a tick claims and integrates nothing, instead of running once",
    )
    run.add_argument("--poll-seconds", type=float, default=30.0)
    run.add_argument("--max-ticks", type=int, default=None)
    run_implementer = subparsers.add_parser(
        "run-implementer",
        help="run Phase 0c M2: one bounded implementer step (tool inferred from the configured model)",
    )
    run_implementer.add_argument("--project", required=True)
    run_implementer.add_argument("--issue", required=True, type=int)
    run_implementer.add_argument(
        "--dry-run",
        action="store_true",
        help="build the command and prompt metadata without invoking Codex",
    )
    checkpoint = subparsers.add_parser(
        "checkpoint",
        help="create a checkpoint commit for a claimed issue lease",
    )
    checkpoint.add_argument("--project", required=True)
    checkpoint.add_argument("--issue", required=True, type=int)
    gate = subparsers.add_parser(
        "gate",
        help="run Phase 0c M3 deterministic gate for a claimed issue",
    )
    gate.add_argument("--project", required=True)
    gate.add_argument("--issue", required=True, type=int)
    handoff = subparsers.add_parser(
        "handoff",
        help="run Phase 0c M4: push through the agent remote and open/update the PR",
    )
    handoff.add_argument("--project", required=True)
    handoff.add_argument("--issue", required=True, type=int)
    handoff.add_argument("--branch")
    handoff.add_argument("--intent")
    handoff.add_argument(
        "--no-yes",
        action="store_true",
        help="do not pass --yes to no-mistakes",
    )
    sim_validation = subparsers.add_parser(
        "sim-validation",
        help="run Phase 0c M5: serialized real-target validation and status posting",
    )
    sim_validation.add_argument("--project", required=True)
    sim_validation.add_argument("--issue", required=True, type=int)
    sim_validation.add_argument("--pr", type=int)
    sim_validation.add_argument("--platform", choices=["macos", "ios", "both"])
    sim_validation.add_argument("--post", action="store_true")
    review = subparsers.add_parser(
        "review",
        help="run Phase 0c M6: final-SHA review and routing (tool inferred from the configured model)",
    )
    review.add_argument("--project", required=True)
    review.add_argument("--issue", required=True, type=int)
    review.add_argument("--pr", type=int)
    review.add_argument("--model")
    review.add_argument("--post", action="store_true")
    ensure_day = subparsers.add_parser(
        "ensure-daily-branch",
        help="run Phase 0c M8: create today's integration branch from the default branch when needed",
    )
    ensure_day.add_argument("--project", required=True)
    ensure_day.add_argument("--branch")
    ensure_day.add_argument("--dry-run", action="store_true")
    integrate = subparsers.add_parser(
        "integrate-pr",
        help="run Phase 0c M8: merge one approved PR into the daily branch and revert it if post-merge checks fail",
    )
    integrate.add_argument("--project", required=True)
    integrate.add_argument("--issue", required=True, type=int)
    integrate.add_argument("--pr", type=int)
    integrate.add_argument("--branch")
    integrate.add_argument("--dry-run", action="store_true")
    integrate_next = subparsers.add_parser(
        "integrate-next",
        help="run Phase 0c M8: merge the next approved PR targeting the daily branch",
    )
    integrate_next.add_argument("--project", required=True)
    integrate_next.add_argument("--branch")
    integrate_next.add_argument("--dry-run", action="store_true")
    daily_pr = subparsers.add_parser(
        "open-daily-pr",
        help="run Phase 0c M8: open or update the final daily PR into the default branch",
    )
    daily_pr.add_argument("--project", required=True)
    daily_pr.add_argument("--branch")
    daily_pr.add_argument("--post", action="store_true")
    daily_pr.add_argument("--dry-run", action="store_true")
    base_refresh = subparsers.add_parser(
        "base-refresh",
        help="run Phase 0c M7: check base freshness and cleanly refresh when possible",
    )
    base_refresh.add_argument("--project", required=True)
    base_refresh.add_argument("--issue", required=True, type=int)
    wake = subparsers.add_parser(
        "wake",
        help="run Phase 0c M9: record a GitHub event wakeup for the daemon",
    )
    wake.add_argument("--project", required=True)
    wake.add_argument("--event", required=True, choices=["labeled", "reopened", "edited", "poll"])
    wake.add_argument("--issue", type=int)
    reconcile_parser = subparsers.add_parser(
        "reconcile",
        help="run Phase 0c M9: reconcile ledgers, leases, labels, PRs, and checks",
    )
    reconcile_parser.add_argument("--project", required=True)
    evening = subparsers.add_parser(
        "evening-report",
        help="run Phase 0c M10: emit the token-free evening checklist",
    )
    evening.add_argument("--project", required=True)
    concurrency = subparsers.add_parser(
        "concurrency",
        help="run Phase 0c M11: inspect or set the staged concurrency guardrail",
    )
    concurrency.add_argument("--project", required=True)
    concurrency.add_argument(
        "--stage",
        choices=["watched-worker", "two-plus-sim", "half-day-unattended", "scale-up"],
    )
    heartbeat = subparsers.add_parser(
        "heartbeat",
        help="run Phase 0c M13: write or check the orchestrator heartbeat",
    )
    heartbeat.add_argument("--project", required=True)
    heartbeat.add_argument("--check", action="store_true")
    heartbeat.add_argument("--max-age-seconds", type=int)
    resume = subparsers.add_parser(
        "resume-deferred",
        help="run Phase 0c M13: resume a deferred task when its window returns",
    )
    resume.add_argument("--project", required=True)
    resume.add_argument("--issue", required=True, type=int)
    nightly = subparsers.add_parser(
        "nightly-e2e",
        help="run Phase 0c M14: nightly full E2E with flake-firewall retries",
    )
    nightly.add_argument("--project", required=True)
    nightly.add_argument("--dry-run", action="store_true")
    daily = subparsers.add_parser(
        "daily-report",
        help="run Phase 0c M14: deterministic daily operating report",
    )
    daily.add_argument("--project", required=True)
    weekly = subparsers.add_parser(
        "weekly-retro",
        help="run Phase 0c M14: weekly retro metrics",
    )
    weekly.add_argument("--project", required=True)
    context_report = subparsers.add_parser(
        "context-report",
        help="measure repeated reads, re-derived lessons, full-gate mentions, and token spread",
    )
    context_report.add_argument("--project", required=True)

    args = parser.parse_args(argv)

    try:
        config = load_project_config(args.project, root=args.root)
    except ConfigError as exc:
        print(f"FAIL load project config - {exc}", file=sys.stderr)
        return 1
    if args.command in ADVANCING_COMMANDS and is_paused(config):
        print(pause_message(config), file=sys.stderr)
        return 2

    if args.command == "preflight":
        results = run_preflight(config)
        print(format_results(results))
        return 1 if failed(results) else 0
    if args.command == "claim-next":
        try:
            result = claim_next_ready(config, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL claim-next - {exc}", file=sys.stderr)
            return 1
        for action in result.actions:
            print(action)
        for number, label, reasons in result.rejected:
            print(f"issue #{number} routed to {label}:")
            for reason in reasons:
                print(f"  - {reason}")
        return 0
    if args.command == "advance-frontier":
        try:
            promoted = advance_ready_frontier(config, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL advance-frontier - {exc}", file=sys.stderr)
            return 1
        if promoted:
            for number in promoted:
                print(f"issue #{number}: blocked -> ready (every declared blocker is closed)")
        else:
            print("no blocked issue is ready to promote")
        return 0
    if args.command == "claim-all":
        try:
            result = claim_all_ready(config, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL claim-all - {exc}", file=sys.stderr)
            return 1
        for action in result.actions:
            print(action)
        for number in result.deferred:
            print(f"issue #{number}: deferred (scope overlaps in-flight or already-claimed work)")
        for number, label, reasons in result.rejected:
            print(f"issue #{number} routed to {label}:")
            for reason in reasons:
                print(f"  - {reason}")
        print(f"claimed {len(result.claimed)} issue(s): {[c.issue_number for c in result.claimed]}")
        return 0
    if args.command == "run":
        try:
            ticks = 0
            while True:
                result = run_tick(config, dry_run=args.dry_run)
                ticks += 1
                if result.promoted:
                    print(f"promoted: {result.promoted}")
                if result.claimed:
                    print(f"claimed: {result.claimed}")
                if result.deferred:
                    print(f"deferred: {result.deferred}")
                for pipeline_result in result.pipeline_results:
                    print(
                        f"issue #{pipeline_result.issue_number} stopped at {pipeline_result.stage}: "
                        f"{pipeline_result.summary}"
                    )
                if result.integrated:
                    print(f"integrated: {result.integrated}")
                if not args.poll:
                    break
                if args.max_ticks and ticks >= args.max_ticks:
                    break
                if not (result.promoted or result.claimed or result.integrated):
                    print(f"nothing to do; sleeping {args.poll_seconds}s")
                    time.sleep(args.poll_seconds)
                    continue
        except Exception as exc:
            print(f"FAIL run - {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "run-implementer":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_implementer_once(config, entry, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL run-implementer - {exc}", file=sys.stderr)
            return 1
        print(f"command: {' '.join(result.command)}")
        print(f"prompt: {result.prompt_path}")
        print(f"result: {result.result_path}")
        print(f"log: {result.log_path}")
        print(f"head before: {result.head_before or 'unknown'}")
        print(f"head after: {result.head_after or 'unknown'}")
        if result.codex_session_id:
            print(f"codex session: {result.codex_session_id}")
        print(f"summary: {result.summary}")
        return result.returncode
    if args.command == "checkpoint":
        try:
            entry = read_run_entry(config, args.issue)
            result = checkpoint_entry(config, entry)
        except Exception as exc:
            print(f"FAIL checkpoint - {exc}", file=sys.stderr)
            return 1
        print(result.message)
        print(f"head before: {result.head_before or 'unknown'}")
        print(f"head after: {result.head_after or 'unknown'}")
        return 0 if result.created else 1
    if args.command == "gate":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_gate(config, entry)
        except Exception as exc:
            print(f"FAIL gate - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        for command in result.commands:
            state = "PASS" if command.returncode == 0 else "FAIL"
            print(f"{state} {command.name}: {command.command}")
            print(f"  log: {command.log_path}")
        return 0 if result.passed else 1
    if args.command == "handoff":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_pr_handoff(
                config,
                entry,
                branch=args.branch,
                intent=args.intent,
                yes=not args.no_yes,
            )
        except Exception as exc:
            print(f"FAIL handoff - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        print(f"branch: {result.pushed_branch}")
        print(f"pr: {result.pr_url or 'unknown'}")
        print(f"head: {result.head_sha or 'unknown'}")
        print(f"log: {result.log_path}")
        return 0 if result.status == "passed" else 1
    if args.command == "sim-validation":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_sim_validation(
                config,
                entry,
                pr_number=args.pr,
                post=args.post,
                platform=args.platform,
            )
        except Exception as exc:
            print(f"FAIL sim-validation - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        print(f"head: {result.head_sha or 'unknown'}")
        print(f"log: {result.log_path}")
        return 0 if result.status == "success" and result.returncode == 0 else 1
    if args.command == "review":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_review(
                config,
                entry,
                pr_number=args.pr,
                post=args.post,
                model=args.model,
            )
        except Exception as exc:
            print(f"FAIL review - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        print(f"routing: {result.routing or 'unknown'}")
        print(f"head: {result.head_sha or 'unknown'}")
        print(f"log: {result.log_path}")
        return 0 if result.status == "approve" and result.returncode == 0 else 1
    if args.command == "ensure-daily-branch":
        try:
            result = ensure_daily_branch(config, branch=args.branch, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL ensure-daily-branch - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        for command in result.commands:
            print(f"command: {' '.join(command)}")
        return 0 if result.status in {"planned", "exists", "created"} else 1
    if args.command == "integrate-pr":
        try:
            entry = read_run_entry(config, args.issue)
            result = integrate_pr(
                config,
                entry,
                pr_number=args.pr,
                branch=args.branch,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"FAIL integrate-pr - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        if result.branch_checks:
            print(f"branch checks: {result.branch_checks.status}")
            for reason in result.branch_checks.reasons:
                print(f"  - {reason}")
        if result.revert_result:
            print(f"revert: {result.revert_result.status}")
            print(f"revert log: {result.revert_result.log_path}")
        return 0 if result.status in {"planned", "passed"} else 1
    if args.command == "integrate-next":
        try:
            result = integrate_next_approved(
                config,
                branch=args.branch,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"FAIL integrate-next - {exc}", file=sys.stderr)
            return 1
        if result is None:
            print("no approved PR with a matching run ledger is ready for integration")
            return 0
        print(result.summary)
        return 0 if result.status in {"planned", "passed"} else 1
    if args.command == "open-daily-pr":
        try:
            result = open_daily_pr(
                config,
                branch=args.branch,
                post=args.post,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"FAIL open-daily-pr - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        print(f"body: {result.body_path}")
        print(f"pr: {result.pr_url or result.pr_number or 'n/a'}")
        if result.post_status_command:
            print(f"status command: {' '.join(result.post_status_command)}")
        return 0 if result.status in {"planned", "created", "updated"} else 1
    if args.command == "base-refresh":
        try:
            entry = read_run_entry(config, args.issue)
            result = run_base_refresh(config, entry)
        except Exception as exc:
            print(f"FAIL base-refresh - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        print(f"head before: {result.head_before or 'unknown'}")
        print(f"head after: {result.head_after or 'unknown'}")
        print(f"review action: {result.review_action}")
        return 0 if result.status in ("current", "refreshed") else 1
    if args.command == "wake":
        try:
            path = record_wakeup(
                config,
                event=args.event,
                issue_number=args.issue,
                payload={"source": "bin/orchestrator wake"},
            )
        except Exception as exc:
            print(f"FAIL wake - {exc}", file=sys.stderr)
            return 1
        print(f"wakeup recorded: {path}")
        return 0
    if args.command == "reconcile":
        try:
            report = reconcile(config)
        except Exception as exc:
            print(f"FAIL reconcile - {exc}", file=sys.stderr)
            return 1
        print(f"polling fallback: every {report.polling_seconds}s")
        for item in report.items:
            actions = ", ".join(item.actions) if item.actions else "none"
            print(
                f"issue #{item.issue_number}: step={item.current_step} "
                f"lease={'yes' if item.lease_exists else 'no'} "
                f"pid={item.pid_alive if item.pid_alive is not None else 'n/a'} "
                f"actions={actions}"
            )
        return 0
    if args.command == "evening-report":
        try:
            print(evening_report(config), end="")
        except Exception as exc:
            print(f"FAIL evening-report - {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "concurrency":
        try:
            if args.stage:
                path = set_concurrency_stage(config, args.stage)
                print(f"concurrency stage recorded: {path}")
            policy = read_concurrency_policy(config)
        except Exception as exc:
            print(f"FAIL concurrency - {exc}", file=sys.stderr)
            return 1
        print(f"stage: {policy.stage}")
        print(f"implementers: {policy.implementers}/{policy.max_implementers}")
        print(f"sim-validations: {policy.sim_validations}")
        print(f"reviewers: {policy.reviewers}")
        return 0
    if args.command == "heartbeat":
        try:
            if args.check:
                status = check_heartbeat(config, max_age_seconds=args.max_age_seconds)
                print(status.reason)
                if status.alert_path:
                    print(f"alert: {status.alert_path}")
                return 0 if status.ok else 1
            path = write_heartbeat(config)
            print(f"heartbeat written: {path}")
        except Exception as exc:
            print(f"FAIL heartbeat - {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "resume-deferred":
        try:
            entry = read_run_entry(config, args.issue)
            result = resume_deferred(config, entry)
        except Exception as exc:
            print(f"FAIL resume-deferred - {exc}", file=sys.stderr)
            return 1
        print(result.summary)
        return 0 if result.resumed else 1
    if args.command == "nightly-e2e":
        try:
            result = run_nightly_e2e(config, dry_run=args.dry_run)
        except Exception as exc:
            print(f"FAIL nightly-e2e - {exc}", file=sys.stderr)
            return 1
        for target in result.results:
            print(f"{target.status} {target.name}: {target.command}")
        if result.record_path:
            print(f"record: {result.record_path}")
        return 0 if all(item.status in {"planned", "passed", "flaky"} for item in result.results) else 1
    if args.command == "daily-report":
        try:
            print(daily_report(config), end="")
        except Exception as exc:
            print(f"FAIL daily-report - {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "weekly-retro":
        try:
            print(weekly_retro(config), end="")
        except Exception as exc:
            print(f"FAIL weekly-retro - {exc}", file=sys.stderr)
            return 1
        return 0
    if args.command == "context-report":
        try:
            report = analyze_context_run(config)
            print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
        except Exception as exc:
            print(f"FAIL context-report - {exc}", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
