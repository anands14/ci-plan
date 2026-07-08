# Agent-Driven Development Pipeline - Plan

Status: designed 2026-06-27, re-evaluated 2026-06-30, not yet built.
This document is standing context for every agent working in this repo (Codex, Claude, Gemini).
Read it before acting.

The application itself (platforms, features, launch order) is a separate "app plan" track.
This document is only about the *mechanism* of continuous, agent-driven development and integration.

---

## 1. The core idea and the one constraint

This is a **supervised-autonomy software factory**.
Agents plan, implement, test, review, and integrate work into a daily branch unattended during the day; the human reviews and merges one final PR to `main` in one evening session.
GitHub holds the work and enforces the gate; the Mac runs the agents on subscription windows.

The single binding constraint is **human validation bandwidth**, not compute and not money.
The human will usually do a quick simulator/device check and glance-review for clean entries in the final daily PR, with real attention reserved for flagged entries.
Everything is sized backward from that review style.
The original "public repo for free compute, agents auto-merge to main" framing was rejected: it optimized the cheap variable and deleted the only error-correcting check that matters - the human.
The private repo can stay private: agents run on the Mac, write only to an agent-owned remote/fork, integrate approved work into a daily branch, and the human remains the only merger to `main`.

---

## 2. Roles

- **Human** - the only uncorrelated check in the system.
  Owns the final `main` merge decision, the evening spec session, and the weekly retro.
  Nothing reaches `main` without explicit human approval.
  Clean entries in the daily PR are glance-review candidates; flagged entries require real attention.
- **Codex** (implementer) - writes code and tests from acceptance criteria.
  Subscription-windowed, flat-rate; runs via `codex exec`.
- **Claude** (gating reviewer) - the single authoritative automated reviewer.
  Runs *locally* on the Mac via `claude -p --model claude-opus-4-8` so it draws from the 5-hour subscription window, not metered API.
  `CLAUDE_REVIEW_MODEL` may override the exact model, but Opus 4.8 is the default gate.
  Only ever reviews already-green code.
- **Gemini** (advisory checker) - free credits.
  Bounded, advisory-only checks (acceptance-criteria conformance, test-honesty).
  Never gates, never stalls the pipeline.
- **GitHub** - the spine: issues = task queue, PRs = work unit and Codex/Claude handoff medium, Actions = non-LLM CI, labels = lifecycle state, and optional self-hosted runner events = wakeups.
  On private Free repos, branch protection is not the gate.
- **Mac orchestrator** - the brain: a thin, deterministic, persistent `launchd` daemon.
  It keeps workers full, owns claiming and leases, and uses GitHub labels plus a local run ledger to resume safely.
- **Integration agent** - a deterministic lane or dedicated agent identity that serially merges approved PRs into `day/YYYY-MM-DD`, runs post-merge branch checks, reverts a breaking PR, and notifies the owning agent to fix and raise again.
  It never merges to `main`.

---

## 3. The daily cycle

- **Evening (human + agent), as short as the final daily PR allows.** First, review clean included PRs quickly and flagged included PRs deliberately from the daily PR summary.
  Second, approve or refine tomorrow's task specs - concrete, testable acceptance criteria plus a files-in-scope manifest - and apply `ready` only when the spec contract is satisfied.
- **Daytime (unattended, across 5-hour windows).** The orchestrator keeps implementation slots filled from `ready` issues, pauses plausible long-running work as `deferred`, escalates true stuck work, and resumes across windows from labels plus local run state.
- **End of day.** The report is deterministic and basic: integrated PRs, flags, reverted PRs, stuck tasks, deferred tasks, and check status.
  No LLM report generation by default.
  The orchestrator opens or updates one final PR from `day/YYYY-MM-DD` to `main`; the human approves and merges only that PR.

---

## 4. The per-task loop

1. Claim a `ready` issue, create a branch and a draft PR.
2. Codex implements code plus tests derived from the acceptance criteria.
3. **Cheap gate first:** lint, build, unit/widget/smoke tests on Linux CI.
   Deterministic and fast.
   Never spend review tokens on code that does not compile or fails its own tests.
4. Red? The same implementer iterates with the failure logs while it is accepting the premise and making material progress.
   Same failing test alone is not stuck.
5. Green? **Now** Claude reviews (gating) and Gemini runs its advisory checks.
   Review runs once, on the final green candidate.
6. Changes requested? Codex addresses them while it accepts the objection and keeps making material progress.
   Same reviewer objection alone is not stuck.
7. A task becomes `stuck` only when the implementer disputes the reviewer/spec, says the spec is unclear or wrong, repeats a protected-path conflict, repeats an architecture invariant violation, makes no material diff, or lacks required external input.
8. A task becomes `deferred` when the window-share ceiling is reached while progress is still plausible.
   The worktree lease and local run state are preserved for later resume.
9. Approved? The reviewer classifies the PR as `clean` or `flagged`.
   The integration lane serially merges approved PRs into `day/YYYY-MM-DD`.
10. After each merge into the daily branch, all configured post-merge checks run against the combined branch.
    Pass -> mark the task `integrated` and advance the queue.
    Fail -> revert the just-merged PR, label the task `integration-failed`, notify the owning agent with the failure cause, and ask it to fix and raise again.
11. At the end of the day, raise one PR from the daily branch to `main`.
    Clean included PRs are glance-review candidates; flagged included PRs require real human attention.

---

## 5. Guardrails (the reliability invariants)

- **Hard human-to-main merge gate.** Only the human merges to `main`.
  Agent-managed daily-branch merges are allowed only after review and required checks pass.
  The integration lane merges one PR at a time and immediately verifies the combined branch.
  CI green is necessary, never sufficient.
- **Tests come from acceptance criteria,** not the implementer's whim.
  A CI guard fails the build if a diff removes a test, adds a skip/ignore annotation, or drops coverage below the floor.
- **Persistent, not hypnotized.** Implementer loops keep working while progress is real, but the orchestrator stops or defers them on explicit no-progress signals.
  The window-share ceiling is a fairness pause, not a failure judgment.
- **Tiered constitution.** Invariants (security, no-weakening-tests, dependency boundaries) are escalate-and-wait.
  Conventions (naming, structure) may be deviated from, but only *loudly* - flagged in the PR for scrutiny.
  Silent deviation is the one forbidden thing.
  Agents never self-amend the constitution.
- **Protected paths.** Agents can propose but never edit the CI config, the merge gate, or the constitution.
- **Strict `ready` contract.** Only human-approved or separately reviewed spec-author output gets the `ready` label.
  Missing criteria, missing test levels, missing scope, unresolved blockers, or undeclared protected-path risk removes `ready`.
- **Agent-owned remote.** Before unattended mode, workers may not push directly to origin.
  They write only to an agent-owned fork or remote and open PRs into origin.
- **Credential isolation first.** Workers use a scrubbed environment, a dedicated worker `HOME`, and only the credentials needed for the task.
  They share Xcode, simulators, Flutter, and caches with the Mac user to avoid duplicating the platform stack.
- **Deterministic orchestrator.** Scheduling, claiming, locking, polling, reconciliation, and reports are ordinary code, not LLM calls.
- **Heartbeat and a phone-flippable kill switch,** so an unattended day can neither silently die nor run away.

---

## 6. Test strategy

- **Pyramid.** Per-PR gate is fast and deterministic: unit and widget tests plus one thin integration smoke on the cheapest target (Linux: Web or Android emulator).
  The full cross-platform end-to-end suite runs nightly, batched - Android and Web on Linux, iOS and macOS on the Mac.
- **Flake firewall - non-negotiable.** No end-to-end failure becomes a bug or triggers a fix-loop until it has survived retries.
  Flakiness must never drive the autonomous machine.
- **Acceptance criteria carry a test level,** so inherently end-to-end criteria get a per-PR smoke check and full coverage nightly, never gating the fast loop on a flaky full run.
- **Post-merge bugs** are new tasks through the same gate.
  The reproduction becomes a permanent regression test.
  "The test is wrong" is the rare escalation, never the default the agent may assume.

---

## 7. Context and token model

Three layers per agent, kept minimal on purpose - every token of bloat is window-credit spent.

- **Standing (cached):** a *lean* constitution plus a repo map.
  Always loaded, prompt-cached, hierarchical (module docs load only when that module is touched).
- **Task (from the spec):** acceptance criteria plus the files-in-scope manifest.
  The spec tells the agent where to work so it does not explore blind.
- **On-demand (agent-pulled):** targeted reads bounded by the task scope.

The scope manifest does triple duty: it saves window credits, keeps review diff-centric, and acts as a PR-size guard (a task whose manifest sprawls is too big and gets split).
The deepest context lever is architectural: **deep modules with narrow interfaces** mean a task loads one module, not the whole repo.

---

## 8. Budget - the two-window scheduler

The budget is not dollars; it is **two independent 5-hour subscription windows** (Codex and Claude), refilling on a rolling basis, plus free Gemini credits.
The persistent daemon itself spends zero LLM tokens.
Tokens are spent only when it invokes Codex, Claude, Gemini, or another model for a concrete task step.

- The scheduler treats the two windows as separate taps on a two-stage pipeline.
  If Codex's window is dry, implementation stalls but Claude can still review green PRs; if Claude's is dry, reviews stall but Codex keeps implementing.
  Each stage resumes when its own window refills.
- **Small-wins-first:** bank quick, sure tasks early so a window that dies early still yields mergeable PRs.
- **Cross-window resume is cheap** because lifecycle state lives in GitHub labels, local operational state lives in the run ledger, and the in-flight worktree is held by a durable lease that survives with zero processes (see treehouse below).
- **Bounded prompts over persistent state.** Worktree, branch, issue, PR, logs, and run state persist.
  Codex conversations do not need to persist forever.
  Most retries should be fresh bounded invocations over the same worktree with the task spec, current diff, and latest failure/review output.

---

## 9. The evening report

A token-free **routing layer over GitHub, not a replacement for it.**
Review happens on each agent PR, daily integration happens on the daily branch, and the human merge happens only on the final daily PR.
The report is a basic checklist, not a generated essay.
It sorts into clean PRs awaiting integration, flagged PRs awaiting integration, integrated PRs, integration failures, stuck tasks, and deferred tasks, with only issue/PR numbers, check status, reviewer routing, and short reason fields.

---

## 10. How the system improves

Track six signals: bounce-back rate, escalation rate, window-exhaustion frequency, flake rate, conformance-fail rate, and - the key one - **reviewer-false-approval rate** (the rubber-stamp detector).
A **weekly retro** converts every generalizable bounce into a new constitution rule, rubric check, or spec-template field.
The fix target is almost always the standing artifacts, not "the model is bad."
This is what makes reliability compound instead of plateau.

---

## 11. Build sequence (Phase 0)

The autonomous loop cannot build itself, so Phase 0 is supervised and hands-on.

- **0a - Substrate.** Co-author the constitution, the app skeleton that embodies the architecture, the CI pipelines, the test harness, and the protected-paths config.
- **0b - Prove it by hand (day 1).** The human plays orchestrator: drive Codex to implement a real task, drive Claude to review it, watch the windows.
  Validate spec quality, the acceptance-criteria-as-tests approach, the rubric, and stuck/deferred behavior with full visibility.
  The first hand-run task is the real `codex -> no-mistakes gate -> PR` end-to-end.
- **0c - Minimal vertical orchestrator.** Build only the first slice: read `ready`, preflight the spec, claim one issue, acquire a `treehouse` lease, run one bounded Codex invocation, run the deterministic local gate, push to the agent remote/open a PR, and write local run state.
- **0d - Add lanes.** Add review, sim-validation, event wakeups, local run reconciliation, and the basic report.
- **0e - Stage unattended parallelism.** Move from one watched worker to two workers, then a half-day unattended run, then 4-5 implementer workers only after failures are mostly product/test failures rather than infrastructure noise.
- **Graduation to unattended** is gated on *behavior, not the calendar*: the PAUSE label halts the loop, stuck conditions stop and escalate, deferred tasks resume, direct origin push is blocked, an agent's edit to a protected path is blocked, and a killed orchestrator triggers the heartbeat alert.

---

## 12. Residual risks (go in clear-eyed)

- **Subscription terms.** Headless/automated use of subscription credits must remain permitted.
  Per current understanding, `codex exec` and `claude -p --model claude-opus-4-8` draw from the 5-hour window when run locally and switch to API billing for CI/shared/untrusted runners - which is exactly why the agents run locally on the Mac.
  Re-verify periodically.
- **Glance review has risk.** Clean PRs are designed for quick validation, but flagged PRs must get real attention.
  Rubber-stamping flagged work deletes the main safety check.
- **Quality entropy is never fully solved.** AI reviewing AI shares blind spots.
  The guardrails reduce correlated wrongness; they do not abolish it.
  The human is the last uncorrelated check on 8 diffs a night.
- **Windows may bind harder than expected** until specs are tight.
- **Flutter multi-platform E2E is genuinely flaky.** The firewall contains it; the maintenance does not vanish.

---

## 13. Tech stack

- **Brain:** thin custom orchestrator (we own this), kept alive by `launchd`.
- **Isolation:** `treehouse`.
- **Local gate:** `no-mistakes`.
- **Spine:** GitHub (issues, PRs, labels, Actions CI, optional self-hosted wakeups).
- **Agents:** Codex (`codex exec`), Claude (`claude -p --model claude-opus-4-8`), Gemini.
- **Wakeups:** GitHub issue events via a self-hosted runner or equivalent lightweight wake path, plus periodic reconciliation polling.
- **No tmux, no heavyweight framework, no Sandcastle adoption as the primary runner.**

---

## 14. Implementation - using the cloned repos

Four repositories by `kunchenguid` are cloned in this folder as reference and building blocks.
The strategy is **compose clean primitives under our own thin orchestrator** - adopt the proven single-purpose tools, skip the opinionated composition, and build only the irreducible delta.

### Adopt as-is: `treehouse` (isolation layer)

A daemon-free Go worktree-pool manager.
Use it as the per-task isolation layer.

- Acquire a worktree for a task: `path=$(treehouse get --lease --lease-holder <task-id>)`.
  The path prints clean on stdout; banners go to stderr.
- Release when the task lands or is abandoned: `treehouse return "$path"`.
- The lease is **process-independent**: it survives with zero processes inside the worktree, which is the mechanical backbone of cross-window resume - a task paused when a window runs dry keeps its warm worktree (dependencies and Flutter build cache intact) until the next window resumes it.
  Verified live in the 2026-06-27 spike.
- Reusable warm pools avoid re-running `pub get` and re-warming Gradle per task.

### Adopt, configured: `no-mistakes` (local pre-PR gate)

A Go local git-proxy.
Push a branch to it instead of `origin`; it runs review/test/lint in its own disposable worktree, forwards to the configured push target only when green, and opens a clean PR.

- Configure the checks in `.no-mistakes.yaml` (`commands.{test,lint,format}`).
- It already implements two of our invariants natively: its **trust boundary** loads code-executing config only from the trusted default branch, never the pushed SHA (this *is* our protected-paths guard), and its **review auto-fix is off by default**, parking judgment calls for a human (this *is* our escalate-don't-auto-fix rule).
  It also has strong data-loss prevention (force-push lease guards, rebase-from-fresh-remote).
- **Two configured boundaries, confirmed by the spike:**
  1. It does **not** auto-merge - it opens a PR and waits for the orchestrator's daily integration lane.
     Keep it that way; the integration lane owns merge sequencing.
  2. Its CI auto-fix is bounded by an idle timeout, not our stuck/deferred rules, and its internal review is single-agent.
     So: keep CI auto-fix off or tightly bounded, let the orchestrator-owned Codex loop handle fixes, and keep the **cross-model Claude-reviews-Codex** review as our own separate layer - no-mistakes' same-model review is only a slop pre-filter.
- Composition with treehouse is clean by **git-push handoff**: the implementer works in a treehouse-leased worktree, pushes the branch to the no-mistakes gate, and no-mistakes checks that SHA into its own worktree.
  They are sequential stages and never contend.

### Reference only: `gnhf` (inner-loop patterns)

A single-agent "ralph" loop (TypeScript).
Its open-ended, many-commits-per-objective model fights our bounded one-task-one-PR shape, so we drive `codex exec` from our own orchestrator rather than adopt it.
Borrow its proven patterns: exponential backoff, sleep prevention (`caffeinate`), structured run summaries, and especially its clean handling of "Claude low credit balance" as a permanent-for-now error that aborts gracefully - which is most of our window-exhaustion handling.

### Reference only: `firstmate` (composition patterns), skip the tooling

The crew-orchestration layer (shell + tmux).
It enforces a human merge gate and is restart-proof, but its tmux-based, watchable-crew model is built for *attended* operation - the wrong mode for our unattended loop.
Borrow the patterns (zero-token bash supervision, merge-gate, `AGENTS.md`-as-orchestrator, the OPINIONS.md-as-constitution idea), skip the tmux composition.

### Reference only: `sandcastle` (runner patterns), skip the control model

Sandcastle is a good source for structured output, session capture/resume, branch worktree patterns, provider abstraction, and timeouts.
Do not adopt it wholesale as the primary orchestrator.
Its templates lean toward broad agent-managed branch merging and same-family review, while this pipeline needs GitHub-label lifecycle state, private-Free merge constraints, human-only merge to `main`, a serialized daily integration lane, orchestrator-owned status attestation, `treehouse` leases, `no-mistakes`, Codex implementer plus Claude reviewer, and a serialized Mac simulator lane.

### Build ourselves (the irreducible delta nothing provides)

- The **two-window scheduler** (Codex and Claude windows, cross-window resume, worker-slot fairness).
- The **cross-model implement -> review gate** (Codex implements a PR, Claude reviews that same work - different models, for decorrelation).
- **GitHub issues-as-queue** plus the label state machine, strict `ready` preflight, event wakeups, and small-wins ordering.
- The **daily integration lane**: one approved PR at a time into `day/YYYY-MM-DD`, post-merge checks on the combined branch, automatic revert on failure, and a final daily PR to `main`.
- The **advisory-Gemini** checks and the **flake firewall**.
- The **token-free evening checklist** and the weekly-retro metrics.

All of it sits on top of `treehouse` (isolation) plus `no-mistakes` (gate) plus GitHub (spine), driven by `codex exec` and `claude -p --model claude-opus-4-8` on local subscription windows.
