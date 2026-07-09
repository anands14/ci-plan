# Orchestrator - design spec and operating contract

The orchestrator is the brain.
This document is its blueprint and operating contract.
Its commands are intentionally thin, deterministic slices rather than a full always-on daemon (the `launchd` wiring is still a manual, per-machine setup step - see "Build order").
Keep extending them only after each manual or watched run proves the next behavior.

## Principles

- **Persistent deterministic daemon.** A `launchd` process owns scheduling, claiming, locks, worker slots, leases, polling, wakeups, and reconciliation.
  It does not call an LLM for those jobs.
- **Event wakeups plus reconciliation.** GitHub issue events may wake the daemon, but only the daemon claims work.
  Periodic polling remains the safety net for missed events, reboot, sleep, runner downtime, and label drift.
- **Two sources of state.** GitHub issue/PR labels are the public lifecycle state (see [setup/labels.yaml](setup/labels.yaml)).
  A small local run ledger stores operational facts such as worker PID, leased worktree path, current step, session id, last failure summary, and log paths.
- **Owns control flow; delegates cognition.** Agents think, skills instruct, tools execute (treehouse, no-mistakes).
  Which CLI actually runs a role is resolved generically from its configured model (`orchestrator/config.py:infer_tool`) - no role is hardcoded to Codex, Claude, or any other tool.
  The orchestrator wires them and never delegates scheduling judgment to a model; the one narrow exception is the advisor, an on-demand consult the deterministic code calls out to but never asks to schedule anything (see "Advisor" below).
- **Config-driven and project-agnostic.** Everything project-specific comes from `projects/<name>.yaml`; the orchestrator code knows nothing about any stack.
- **Agent-owned remote only.** In unattended mode, workers may not push directly to origin.
  They push to the configured agent remote/fork and open PRs into origin.

## The main loop (per tick)

```
load projects/<name>.yaml
if PAUSE label present on the control issue: stop cleanly, exit.
post heartbeat (timestamp) to the pinned status issue.
reconcile local run ledger with GitHub labels, worktree leases, live PIDs, PRs, and checks.
promote blocked -> ready for every issue whose declared #N blockers are now closed.  # advance_ready_frontier
windows = probe(each configured tool's window)      # see the per-tool window scheduler
claim every currently-ready, currently-safe issue - no fixed worker-count cap.       # claim_all_ready
run each claimed issue's pipeline (implement -> gate -> handoff -> sim-validate -> review) in parallel.
serially integrate whatever is approved and eligible, one PR at a time.
write the token-free evening checklist.
sleep(interval) or wait for a wake event.
```

`bin/orchestrator run [--poll]` is this whole loop as one command - see "How each tool is driven" for the pieces it calls.
GitHub Actions or webhook events should call only a `wake` command.
They must not directly launch agent workers.
The daemon decides whether any worker slot is actually free - and here, "free" means *not colliding in scope with something already running*, not *under some worker-count ceiling*.

## Per-task loop

Mirrors CONSTITUTION.md section 3, and the test/check design settled for the first project (the project's `docs/CONSTITUTION.md` > Checks; memory `tovi-ci-test-pipeline`).

0. **Preflight.** Validate the `ready` contract before claiming.
   Missing criteria, missing test levels, missing scope, unresolved blockers, or undeclared protected-path risk removes `ready` and adds `needs-human` or `blocked`.
   A `blocked` issue is promoted back to `ready` on its own, no human relabeling needed, the moment every `#N` it declares is closed (`queueing.advance_ready_frontier`).
1. **Claim.** Move every currently-safe `ready` issue to `in-progress` in one pass, not one at a time (`queueing.claim_all_ready`).
   "Currently-safe" means: not scope-overlapping anything already `in-progress`, and not scope-overlapping another issue claimed in this same pass (an undeclared overlap is rejected to `needs-human`; a declared or in-flight overlap is deferred to the next pass instead of claimed alongside it).
   There is no fixed worker-count cap - concurrency is bounded by the frontier and by scope collisions, not a policy number.
   Acquire an isolated worktree per claimed issue: `wt=$(treehouse get --lease --lease-holder <task-id>)`.
   Record the lease in the local run ledger.
2. **Implement.** If the implementer's tool's window is dry, label `deferred` and move on.
   Else inject the implementer role into a bounded invocation in `wt` via the generic dispatcher (`agents.build_implementer_command` resolves the CLI from the configured model).
3. **Checkpoint.** Require stable checkpoint commits during unattended work.
   These are operational recovery points; final merge can squash them.
4. **Local gate (pre-PR, on the Mac).** Run the project's fast gate via no-mistakes in a disposable worktree - format, lint, the fast suite (unit + widget), and the **backend E2E** (real file adapter today; SQLite/index assertions when that component exists) - with `ci_autofix` off (D2).
   Red -> the orchestrator invokes the implementer again with the logs and exact next objective.
5. **Progress handling.** Keep looping while the implementer accepts the premise and makes material diffs.
   Before marking `stuck` - implementer disputes the reviewer/spec, spec unclear or wrong, repeated protected-path conflict, repeated architecture invariant violation, no material diff, or missing external input - consult the advisor once and give the implementer one retried turn with its answer; only mark `stuck` if that doesn't resolve it (`agents._consult_advisor_and_retry`).
   Mark `deferred` when the window-share ceiling is reached while progress is still plausible.
6. **Sim-validation (pre-PR).** The orchestrator - not the agent - runs the cheapest credible real target, drawn from a configurable pool of simulator/device slots (`validation._pool_lane_lock`; a pool of 1 reproduces the original serialized behavior).
   Pure core/agent/backend changes may be `N/A`; generic Flutter UI defaults to macOS; touch/mobile/platform-specific behavior selects iOS, Android, macOS, or a real device by project-configured path/content/criteria rules.
   Capture the real exit code.
7. **Raise + attest.** When the local gate and sim-validation are green or explicitly `N/A`, the orchestrator opens or updates the PR from the agent remote and **posts the `sim-validation` commit status** from step 6's real result.
   It holds the only token that may post statuses.
8. **CI + fix loop.** Poll `gh pr checks` (a plain REST/API call - zero agent tokens).
   On a red check, the implementer fixes and pushes to the **same PR**, then the local gate and required statuses run again.
   `no-mistakes` stays a gate, not a second autonomous fixer.
9. **Base freshness.** Before a PR becomes daily-integration eligible, token-free code checks whether the branch is current with the daily branch.
   Clean rebases and deterministic re-gates happen automatically.
   Conflicted or non-trivial resolution wakes the implementer only when necessary.
10. **Review.** Green -> `in-review`.
    If the reviewer's tool's window is dry, leave it and resume next window.
    Else inject the reviewer role over the **exact final SHA** + criteria + implementer result, then **post the `review` status**.
    The reviewer's tool is generic too: `bin/review --tool` resolves from the configured model, falling back to a configured fallback model/tool if the primary cannot run or cannot return a verdict.
    Either the implementer or the reviewer may consult the advisor once, mid-turn, on a specific question (`bin/advise` / `agents.run_advisor_once`) - it is never itself the reviewer.
    Green CI is necessary, never sufficient.
    A test-assertion change is judged against the issue's **acceptance criteria**; if the criteria do not settle it, escalate to `needs-human` rather than guess.
11. **Route.** Review approval sets `approved` plus either `clean` or `flagged`.
    Same-model implementer and reviewer is allowed; it is not this loop's job to compensate for it - the human owns that decorrelation check consciously at the daily-branch-to-main gate (step 13), not here.
    `clean` means glance-review candidate inside the final daily PR; `flagged` means real human attention.
    Return the worktree only after the task is no longer expected to resume.
12. **Daily integration.** The integration lane merges exactly one approved PR at a time into `day/YYYY-MM-DD`.
    It requires `gate`, `test-discipline`, `sim-validation`, and `review` to be green on the agent PR before the merge.
    After the merge, it waits for the configured post-merge branch checks on the daily branch.
    If those checks pass, it marks the task `integrated` and closes the GitHub issue as completed.
    If those checks fail, it reverts the just-merged PR, marks the task `integration-failed`, comments with the failure cause, and wakes the owning agent to fix and raise again.
13. **Final daily PR.** At the end of day, the orchestrator opens or updates one PR from `day/YYYY-MM-DD` to the default branch and posts `daily-integration`.
    The final PR lists already-integrated, already-closed issues rather than closing them.
    The human merges only this final PR, and may consciously bring in a different reviewer model for this one look if same-model implement/review was used per-task - a manual, ad hoc step, not a built pipeline lane.
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

## The per-tool window scheduler

Windows are independent resource taps keyed by **resolved tool**, not by role - because a role's tool is a config choice (`orchestrator/config.py:infer_tool`), not an architectural fact.
Point implementer and reviewer at the same model and they share one tap and contend for it; point them at different models and each gets its own.
The advisor draws from its own configured tool's window too, same as any other role.

- **Probe.** Detect each tool's remaining window, primarily by catching the rate-limit / "low credit balance" error at invocation (gnhf's pattern: treat it as a permanent-for-now error).
  Optionally parse a reported reset time.
- **Decoupled stalls.** A dry tool pauses every role configured to it; roles on a different tool keep going.
  Each role resumes when *its tool's* window refills.
- **Contention when shared.** If two roles share a tool and its window is scarce, finish in-flight work on that tool before starting new work on it - don't strand a task mid-review to start a fresh implementation on the same tap.
- **Resume.** On exhaustion or fairness pause, label affected tasks `deferred` and schedule the next tick for the expected reset (or poll every ~20-30 min).
  Because lifecycle state is in labels, operational state is in the local run ledger, and worktrees are held by leases, resume is just reconciliation plus the next bounded invocation.
- **No fixed worker-count cap.** Concurrency is bounded by the dependency frontier and scope collisions (see "Claim" above), not a policy number; a shared or dry window is a real, physical throttle, which is exactly why it's tracked per tool.

## How each tool is driven

- **treehouse** (CLI): `get --lease` / `return`.
  Orchestrator-only; the agent never sees it.
- **no-mistakes** (CLI): the gate + PR machinery, driven via `git push no-mistakes` and its `axi` interface for status.
  Configured per project; `ci_autofix` off or tightly bounded.
  The orchestrator-owned implementer loop is the only fix loop.
- **implementer / reviewer / advisor** (generic dispatch, any CLI): each role is `{model, effort}` in `projects/<name>.yaml`; the tool is inferred from the model name (`claude-*`/`fable-*` -> `claude`, `gpt-*` -> `codex`, ...) unless a `tool:` override is set.
  `agents.build_implementer_command` and `bin/review --tool` are the two dispatch points today; extend the inference table when a new provider shows up.
  Subscription windows, run locally.
  The reviewer falls back to a configured fallback model/tool if the primary cannot run or cannot return a verdict.
  The advisor is invoked via `bin/advise`, on demand only - never polled, never scheduled a slot.

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

## Module layout (as built)

```
orchestrator/
  __main__.py      # the CLI: preflight, claim-next/claim-all, advance-frontier, run (tick), ...
  config.py        # load projects/<name>.yaml; infer_tool resolves a role's CLI from its model
  github.py        # gh wrapper: issues, labels, PRs, reviews, issues_with_label, issue_closed
  ledger.py        # local run database / run directory
  queueing.py      # ready-contract validation, advance_ready_frontier, claim_all_ready
  agents.py        # generic implementer dispatch, run_advisor_once, advisor_request handling
  outcomes.py       # deterministic stuck/deferred classification
  tick.py          # one full tick: frontier -> claim-all -> parallel pipeline -> serial integrate
  gate.py          # local gate runner
  handoff.py       # PR handoff through the agent remote
  validation.py    # sim-validation (pooled lane lock) + review (shells to bin/review)
  integration.py   # daily branch creation, serialized merges, reverts, final daily PR
  tools.py         # treehouse driver
  concurrency.py   # staged concurrency policy (reviewers, sim-validation pool size)
  heartbeat.py / safety.py / reconcile.py / reporting.py / cadence.py  # observability + control
```

Keep it thin.
Most of the hard, dangerous work (worktrees, the gate, data-loss safety) lives in the adopted tools; this code only sequences them and bookkeeps labels.

## Build order

The detailed checklist lives in [setup/orchestrator-milestones.md](setup/orchestrator-milestones.md).
Phase 0c's vertical-slice commands (preflight, claim-next, run-implementer, gate, handoff, sim-validation, review, integrate-pr/-next, open-daily-pr, wake, reconcile, evening-report) are all built and tested.
On top of them:

1. Frontier + unbounded claiming: `advance-frontier` and `claim-all` (this doc's "Claim" step) - built, tested, no fixed worker-count cap.
2. Generic dispatch: implementer, reviewer, and advisor all resolve their CLI from their configured model - built, tested.
3. The advisor role: proactive `advisor_request` and the reactive stuck-backstop, one round-trip each - built, tested.
4. `run` (the tick command): frontier -> claim-all -> parallel per-issue pipeline -> serial integration, with `--poll` to loop - built, tested with mocked externals (treehouse, gh, the agent CLIs).
5. Not yet done: a `launchd` plist wiring `run --poll` into an always-on daemon - that's an OS-level, per-machine setup step, not code this repo ships.

## Do not flip to unattended until all four fire

1. The `PAUSE` label halts the loop.
2. A true stuck condition stops and escalates.
3. A plausible long-running task pauses as `deferred` and later resumes.
4. Direct origin push by a worker is blocked by preflight.
5. An agent edit to a protected path is blocked.
6. A killed orchestrator triggers the heartbeat alert.
