# Automated process milestone checklist

This is the canonical checklist for putting the automated process in place.
It includes the setup proof work, the Phase 0c orchestrator build, merge enforcement, graduation checks, and operating cadence.
Do not jump to a full unattended system first.
Each milestone should be runnable and observable before the next one starts.

## F0 - Target project registration

- [x] Create and fill `projects/<name>.yaml`.
- [x] Verify the target project constitution exists and is referenced by the target repo's agent docs.
- [x] Verify the target repo has `.no-mistakes.yaml`.
- [x] Provision the GitHub labels from `setup/labels.yaml`.
- [x] Verify the target repo has issue and PR templates.
- [x] Create or verify the dedicated worker `HOME`.
- [x] Verify worker credential isolation.
- [x] Configure and verify the agent remote or fork.

## F1 - Hand-run loop proof

- [x] Claim a `ready` issue by hand.
- [x] Drive Codex implementation.
- [x] Run tests and the no-mistakes gate.
- [x] Open a PR from the agent remote.
- [x] Run sim/device validation or record a valid `N/A`.
- [x] Run Claude review on the final SHA.
- [x] Route the PR as approved plus clean or flagged.
- [x] Exercise daily-branch integration.
- [x] Exercise the final human merge path through `bin/merge`.

## M0 - Preflight only

Runnable check: `bin/orchestrator preflight --project <name>`.

- [x] Load `projects/<name>.yaml`.
- [x] Verify the target repo exists locally.
- [x] Verify `treehouse`, `no-mistakes`, `gh`, `codex`, and `claude` are discoverable where required.
- [x] Verify the worker environment uses the dedicated worker `HOME`.
- [x] Verify the worker environment cannot see the orchestrator status token.
- [x] Verify the worker environment cannot see human GitHub auth.
- [x] Verify the worker cannot push directly to origin.
- [x] Verify the configured agent remote/fork can accept a branch push.

## M1 - Queue and claim

Runnable check: `bin/orchestrator claim-next --project <name> --dry-run`.

- [x] Read open issues with `ready`.
- [x] Enforce the strict `ready` contract.
- [x] Remove `ready` and add `needs-human` or `blocked` when the contract fails.
- [x] Claim exactly one valid issue by moving it to `in-progress`.
- [x] Acquire a `treehouse` lease for the issue.
- [x] Write a local run ledger entry with issue number, lease path, current step, and log path.

## M2 - One bounded implementer step

Runnable command after M1 live claim: `bin/orchestrator run-implementer --project <name> --issue <n>`.

- [x] Inject `pipeline-implementer`.
- [x] Invoke Codex once in the leased worktree with the issue body and scope manifest.
- [x] Require checkpoint commits after stable progress.
- [x] Record the Codex session id when available.
- [x] Record a compact step summary without feeding transcripts into another model.

## M3 - Deterministic gate and Codex fix loop

Runnable command: `bin/orchestrator gate --project <name> --issue <n>`.

- [x] Run format, lint, fast tests, and backend E2E through the configured gate.
- [x] Keep `no-mistakes` auto-fix off.
- [x] Feed failing logs back to Codex only when the stuck rules do not apply.
- [x] Mark `stuck` for disputed spec/review, repeated protected-path conflict, repeated architecture invariant violation, no material diff, or missing external input.
- [x] Mark `deferred` when the window-share ceiling trips while progress remains plausible.

## M4 - PR handoff

Runnable command: `bin/orchestrator handoff --project <name> --issue <n>`.

- [x] Push only to the agent remote/fork.
- [x] Open or update the PR into origin.
- [x] Fill the PR template from issue criteria, tests, deviations, and uncertainties.
- [x] Refuse to proceed if the worker can push origin.

## M5 - Sim-validation lane

Runnable command: `bin/orchestrator sim-validation --project <name> --issue <n> --pr <n> --post`.

- [x] Select the cheapest credible real target from project config.
- [x] Serialize sim-validation jobs at first.
- [x] Post `sim-validation` from the orchestrator token only.
- [x] Allow `N/A` only for pure backend/core work under project rules.

## M6 - Review lane

Runnable command: `bin/orchestrator review --project <name> --issue <n> --pr <n> --post`.

- [x] Wait until deterministic gates are green.
- [x] Run Claude only on the exact final SHA.
- [x] Require `verdict` plus `routing` of `clean` or `flagged`.
- [x] Post `review` from the orchestrator token only.
- [x] Send `request-changes` back to the Codex loop.

Live note: PR #10 is green through no-mistakes, `sim-validation=success`, `review=success`, and is ready for daily-branch integration.

## M7 - Base freshness

Runnable command: `bin/orchestrator base-refresh --project <name> --issue <n>`.

- [x] Check whether the PR branch is current with the configured integration base.
- [x] Perform clean token-free rebase/refresh when possible.
- [x] Rerun deterministic gates after refresh.
- [x] Wake Codex only for conflicted or non-trivial resolution.
- [x] Rerun Claude only when the final diff materially changed.

## M8 - Daily integration lane

Runnable commands: `bin/orchestrator ensure-daily-branch --project <name>`, `bin/orchestrator integrate-pr --project <name> --issue <n> --pr <n>`, and `bin/orchestrator open-daily-pr --project <name> --post`.

- [x] Ensure `day/YYYY-MM-DD` exists from the default branch.
- [x] Retarget agent PRs to the daily branch during handoff.
- [x] Require `gate`, `test-discipline`, `sim-validation`, and `review` before integrating an agent PR.
- [x] Merge exactly one approved PR at a time into the daily branch.
- [x] Run post-merge checks on the combined daily branch.
- [x] Revert the just-merged PR if post-merge checks fail.
- [x] Notify the owning agent with the breaking cause and revert status.
- [x] Open or update the final daily PR to the default branch.
- [x] Post `daily-integration` from the orchestrator token only.

## M9 - Event wakeups and reconciliation

Runnable commands: `bin/orchestrator wake --project <name> --event labeled --issue <n>` and `bin/orchestrator reconcile --project <name>`.

- [x] Add a GitHub issue event wake path for `labeled`, `reopened`, and `edited`.
- [x] Ensure wakeups only notify the daemon.
- [x] Keep periodic polling as the safety net.
- [x] Reconcile GitHub labels, local ledger, worktree leases, live PIDs, PRs, and check states on every tick.

## M10 - Basic evening checklist

Runnable command: `bin/orchestrator evening-report --project <name>`.

- [x] Emit clean PRs.
- [x] Emit flagged PRs.
- [x] Emit integrated PRs.
- [x] Emit integration failures.
- [x] Emit stuck tasks.
- [x] Emit deferred tasks.
- [x] Include only issue number, PR number, check state, routing, and short reason.
- [x] Do not call an LLM to generate the checklist by default.

## M11 - Staged concurrency

Runnable command: `bin/orchestrator concurrency --project <name> --stage watched-worker`.

- [x] Add a staged concurrency guardrail.
- [x] Run one watched worker.
- [ ] Run two implementer workers plus one sim-validation lane.
- [ ] Run an unattended half-day with two workers.
- [ ] Raise toward 4-5 implementer workers only after infrastructure failures are understood.

## M12 - Merge gate enforcement

- [x] Require agent PRs to have `gate`, `test-discipline`, `sim-validation`, and `review` before daily integration.
- [x] Require final daily PRs to have `gate`, `test-discipline`, and `daily-integration`.
- [x] Require human merge to `main` through `bin/merge`.
- [x] Verify no orchestrator or agent path merges to `main`.
- [x] Verify `bin/merge` refuses non-daily heads, wrong bases, missing contexts, red checks, and changed heads.
- [x] Verify agent PRs use squash merge into the daily branch.
- [x] Verify the final daily PR uses a merge commit into `main`.

## M13 - Graduation checks

- [x] Verify `PAUSE` halts the loop.
- [x] Verify a true stuck condition escalates instead of looping forever.
- [x] Verify a deferred task resumes after the relevant window returns.
- [x] Verify direct origin push by a worker is blocked.
- [x] Verify protected-path edits are blocked or escalated.
- [x] Verify a killed orchestrator triggers the heartbeat alert.

## M14 - Operating cadence

- [x] Put nightly full E2E in place.
- [x] Add the flake firewall for nightly E2E.
- [x] Emit the deterministic daily report.
- [x] Track bounce-back rate.
- [x] Track escalation rate.
- [x] Track window-exhaustion frequency.
- [x] Track flake rate.
- [x] Track conformance-fail rate.
- [x] Track reviewer false approvals.
- [x] Run the weekly retro against those metrics.
