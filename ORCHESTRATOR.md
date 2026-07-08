# Orchestrator - design spec (Phase 0c)

The orchestrator is the brain.
This document is its blueprint and operating contract.
The Phase 0c commands are intentionally thin, deterministic slices rather than a full always-on daemon.
Keep extending them only after each manual or watched run proves the next behavior.

## Principles

- **Persistent deterministic daemon.** A `launchd` process owns scheduling, claiming, locks, worker slots, leases, polling, wakeups, and reconciliation.
  It does not call an LLM for those jobs.
- **Event wakeups plus reconciliation.** GitHub issue events may wake the daemon, but only the daemon claims work.
  Periodic polling remains the safety net for missed events, reboot, sleep, runner downtime, and label drift.
- **Two sources of state.** GitHub issue/PR labels are the public lifecycle state (see [setup/labels.yaml](setup/labels.yaml)).
  A small local run ledger stores operational facts such as worker PID, leased worktree path, current step, session id, last failure summary, and log paths.
- **Owns control flow; delegates cognition.** Agents think (`codex exec --model gpt-5.5 -c model_reasoning_effort="high"`, `claude -p --model claude-opus-4-8 --effort max`), skills instruct, tools execute (treehouse, no-mistakes).
  The orchestrator wires them and never delegates scheduling judgment to a model.
- **Config-driven and project-agnostic.** Everything project-specific comes from `projects/<name>.yaml`; the orchestrator code knows nothing about any stack.
- **Agent-owned remote only.** In unattended mode, workers may not push directly to origin.
  They push to the configured agent remote/fork and open PRs into origin.

## The main loop (per tick)

```
load projects/<name>.yaml
if PAUSE label present on the control issue: stop cleanly, exit.
post heartbeat (timestamp) to the pinned status issue.
reconcile local run ledger with GitHub labels, worktree leases, live PIDs, PRs, and checks.
windows = probe(Codex window, Claude window)        # see Two-window scheduler
fill available implementer slots from `ready` and resumable `deferred` tasks.
fill available reviewer slots from green `in-review` PRs.
run at most one sim-validation job at a time until the project proves it is safe to raise.
run at most one daily-branch integration merge at a time.
write the token-free evening checklist.
sleep(interval) or wait for a wake event.
```

GitHub Actions or webhook events should call only a `wake` command.
They must not directly launch agent workers.
The daemon decides whether any worker slot is actually free.

## Per-task loop

Mirrors CONSTITUTION.md section 3, and the test/check design settled for the first project (the project's `docs/CONSTITUTION.md` > Checks; memory `tovi-ci-test-pipeline`).

0. **Preflight.** Validate the `ready` contract before claiming.
   Missing criteria, missing test levels, missing scope, unresolved blockers, or undeclared protected-path risk removes `ready` and adds `needs-human` or `blocked`.
1. **Claim.** Move `ready` -> `in-progress`.
   Acquire an isolated worktree: `wt=$(treehouse get --lease --lease-holder <task-id>)`.
   Record the lease in the local run ledger.
2. **Implement.** If the Codex window is dry, label `deferred` and move on.
   Else inject the implementer role into a bounded Codex invocation in `wt`:
   `codex exec "$(cat skills/pipeline-implementer/SKILL.md)\n\nTask: <issue body>"`.
3. **Checkpoint.** Require stable checkpoint commits during unattended work.
   These are operational recovery points; final merge can squash them.
4. **Local gate (pre-PR, on the Mac).** Run the project's fast gate via no-mistakes in a disposable worktree - format, lint, the fast suite (unit + widget), and the **backend E2E** (real file adapter today; SQLite/index assertions when that component exists) - with `ci_autofix` off (D2).
   Red -> the orchestrator invokes Codex with the logs and exact next objective.
5. **Progress handling.** Keep looping while Codex accepts the premise and makes material diffs.
   Mark `stuck` only when the implementer disputes the reviewer/spec, says the spec is unclear or wrong, repeats a protected-path conflict, repeats an architecture invariant violation, makes no material diff, or lacks required external input.
   Mark `deferred` when the window-share ceiling is reached while progress is still plausible.
6. **Sim-validation (pre-PR).** The orchestrator - not the agent - runs the cheapest credible real target, serialized at first.
   Pure core/agent/backend changes may be `N/A`; generic Flutter UI defaults to macOS; touch/mobile/platform-specific behavior selects iOS, Android, macOS, or a real device by project-configured path/content/criteria rules.
   Capture the real exit code.
7. **Raise + attest.** When the local gate and sim-validation are green or explicitly `N/A`, the orchestrator opens or updates the PR from the agent remote and **posts the `sim-validation` commit status** from step 6's real result.
   It holds the only token that may post statuses.
8. **CI + fix loop.** Poll `gh pr checks` (a plain REST/API call - zero agent tokens).
   On a red check, Codex fixes and pushes to the **same PR**, then the local gate and required statuses run again.
   `no-mistakes` stays a gate, not a second autonomous fixer.
9. **Base freshness.** Before a PR becomes daily-integration eligible, token-free code checks whether the branch is current with the daily branch.
   Clean rebases and deterministic re-gates happen automatically.
   Conflicted or non-trivial resolution wakes Codex only when necessary.
10. **Review.** Green -> `in-review`.
    If the Claude window is dry, leave it and resume next window.
    Else inject the reviewer role and run `claude -p --model claude-opus-4-8 --effort max` over the **exact final SHA** + criteria + implementer result, then **post the `review` status**.
    If Claude cannot run or cannot return a verdict, the reviewer wrapper falls back to `codex exec --model gpt-5.5 -c model_reasoning_effort="xhigh"`.
    `CLAUDE_REVIEW_MODEL`, `CLAUDE_REVIEW_EFFORT`, `CODEX_REVIEW_FALLBACK_MODEL`, and `CODEX_REVIEW_FALLBACK_EFFORT` may override the exact reviewer models when the operator intentionally changes the gate.
    Green CI is necessary, never sufficient.
    A test-assertion change is judged against the issue's **acceptance criteria**; if the criteria do not settle it, escalate to `needs-human` rather than guess.
    Run the advisory checker (Gemini) in parallel only if configured; attached, never gating.
11. **Route.** Review approval sets `approved` plus either `clean` or `flagged`.
    `clean` means glance-review candidate inside the final daily PR; `flagged` means real human attention.
    Return the worktree only after the task is no longer expected to resume.
12. **Daily integration.** The integration lane merges exactly one approved PR at a time into `day/YYYY-MM-DD`.
    It requires `gate`, `test-discipline`, `sim-validation`, and `review` to be green on the agent PR before the merge.
    After the merge, it waits for the configured post-merge branch checks on the daily branch.
    If those checks pass, it marks the task `integrated` and closes the GitHub issue as completed.
    If those checks fail, it reverts the just-merged PR, marks the task `integration-failed`, comments with the failure cause, and wakes the owning agent to fix and raise again.
13. **Final daily PR.** At the end of day, the orchestrator opens or updates one PR from `day/YYYY-MM-DD` to the default branch and posts `daily-integration`.
    The final PR lists already-integrated, already-closed issues rather than closing them.
    The human merges only this final PR.
    If final review or merge-to-main reveals a problem, create a new bug or follow-up issue and route it through the same agent loop.

## Status posting & the merge gate (orchestrator-enforced)

Branch protection / required status checks are **unavailable on a free private repo**, and the first project chose **no Pro**, so the final `main` gate is enforced by the orchestrator and a human command, not the platform.
Full model + token checklist: [setup/branch-protection.md](setup/branch-protection.md).
In short:

- Agent PRs target the daily branch.
  The required pre-integration contexts are `gate` (native CI job containing `format`, `analyze`, `test:fast`, and `backend-e2e`), `test-discipline`, plus `sim-validation` and `review` (**orchestrator-posted statuses**).
  The agent token cannot post statuses - the thing being judged never holds the pen.
- `approved` plus `clean` or `flagged` puts the PR in the serialized daily integration queue.
  The integration lane squash-merges into the daily branch, runs post-merge branch checks, closes the issue on success, and reverts the just-merged PR if the combined branch turns red.
- The final PR from the daily branch to the default branch requires `gate`, `test-discipline`, and `daily-integration`.
  The human merges that final PR with **`merge <pr>`**, which refuses non-daily heads, wrong bases, missing contexts, red checks, or a changed head SHA.
- The unattended preflight must fail if the worker can push directly to origin.
  Workers write only to the configured agent remote or fork.

## Worker environment

Do not duplicate Xcode, simulators, browsers, Flutter SDKs, or system caches in a separate macOS user for day one.
Instead, isolate credentials first:

- set worker `HOME` to a dedicated agent home;
- scrub the environment of human `GH_TOKEN`, SSH agent sockets, and unrelated secrets;
- inject only the agent credentials needed for the configured remote/fork and the agent CLI;
- keep the orchestrator status token outside the worker env and outside agent-readable worktrees;
- fail preflight if human GitHub auth, the orchestrator token, or `.env` is visible to a worker.

This is not perfect OS isolation.
It is the practical starting point that avoids duplicating the platform tooling stack.

## Two-window scheduler

The Codex and Claude subscription windows are independent resource taps on a two-stage pipeline.

- **Probe.** Detect each agent's remaining window, primarily by catching the rate-limit / "low credit balance" error at invocation (gnhf's pattern: treat it as a permanent-for-now error).
  Optionally parse a reported reset time.
- **Decoupled stalls.** Codex dry -> implementation stage pauses, but review can still drain `in-review` PRs on Claude's window.
  Claude dry -> reviews pause, but Codex can keep implementing `ready` tasks.
  Each stage resumes when *its own* window refills.
- **Resume.** On exhaustion or fairness pause, label affected tasks `deferred` and schedule the next tick for the expected reset (or poll every ~20-30 min).
  Because lifecycle state is in labels, operational state is in the local run ledger, and worktrees are held by leases, resume is just reconciliation plus the next bounded invocation.
- **Start conservative.** Begin with one watched worker, then two implementer workers plus one serialized sim-validation lane.
  Raise toward 4-5 implementer workers only after infrastructure noise is understood.

## How each tool is driven

- **treehouse** (CLI): `get --lease` / `return`.
  Orchestrator-only; the agent never sees it.
- **no-mistakes** (CLI): the gate + PR machinery, driven via `git push no-mistakes` and its `axi` interface for status.
  Configured per project; `ci_autofix` off or tightly bounded.
  The orchestrator-owned Codex loop is the only fix loop.
- **codex / claude** (CLIs): `codex exec --model gpt-5.5 -c model_reasoning_effort="high"` (implementer), `claude -p --model claude-opus-4-8 --effort max` (reviewer), and `codex exec --model gpt-5.5 -c model_reasoning_effort="xhigh"` as the reviewer fallback.
  Subscription windows, run locally.
- **gemini**: advisory checks, output attached to the PR.
  Free; never gates.

## The evening report

Token-free deterministic output.
No LLM report generation by default.
Read GitHub labels, PR metadata, required check states, and the worker run ledger.
Emit only clean PRs, flagged PRs, stuck tasks, deferred tasks, and short reason fields.
Also emit integrated PRs and integration failures so the final daily PR has a deterministic source of truth.

## Observability and control

- **Heartbeat.** Each tick stamps a pinned status issue; a missing heartbeat past a threshold triggers a push notification.
- **Kill switch.** A `PAUSE` label on the control issue, checked first thing each tick, halts the loop cleanly after the current step.
  Flippable from a phone via GitHub.

## Suggested module layout (when built)

```
orchestrator/
  main.*           # the tick loop, scheduler
  config.*         # load projects/<name>.yaml
  github.*         # gh wrapper: issues, labels, PRs, reviews (lifecycle state)
  ledger.*         # local run database / run directory
  windows.*        # probe + two-window bookkeeping
  agents.*         # codex/claude/gemini drivers + role injection
  integration.*    # daily branch creation, serialized merges, reverts, final daily PR
  tools.*          # treehouse + no-mistakes drivers
  task.*           # the per-task loop + stuck/deferred handling
  report.*         # evening digest
  control.*        # heartbeat + PAUSE
```

Keep it thin.
Most of the hard, dangerous work (worktrees, the gate, data-loss safety) lives in the adopted tools; this code only sequences them and bookkeeps labels.

## Build order (Phase 0c)

The detailed checklist lives in [setup/orchestrator-milestones.md](setup/orchestrator-milestones.md).

1. Minimal vertical slice: `config.*`, `github.*`, strict `ready` preflight, claim one issue, acquire a `treehouse` lease, run one bounded Codex invocation, run the local gate, push/open PR from the agent remote, and write the local run ledger.
2. Review lane: final-SHA Claude review, `review` status posting, and `clean`/`flagged` routing.
3. Sim-validation lane: serialized real-target validation and `sim-validation` status posting.
4. Daily integration lane: ensure `day/YYYY-MM-DD`, serially merge approved PRs, verify post-merge branch checks, revert breakers, and open the final daily PR.
5. Resume and fairness: `deferred`, window probing, worker slot filling, and local/GitHub reconciliation.
6. Wakeups and control: GitHub event wake path, polling safety net, heartbeat, and PAUSE.
7. Basic token-free report.

## Do not flip to unattended until all four fire

1. The `PAUSE` label halts the loop.
2. A true stuck condition stops and escalates.
3. A plausible long-running task pauses as `deferred` and later resumes.
4. Direct origin push by a worker is blocked by preflight.
5. An agent edit to a protected path is blocked.
6. A killed orchestrator triggers the heartbeat alert.
