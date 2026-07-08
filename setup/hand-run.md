# Hand-running a task (Phase 0b - prove the loop before automating)

Run one real task through the whole pipeline by hand, repeatedly, until it reliably yields green, mergeable PRs.
This is the gate before building the orchestrator: the orchestrator is just a thin scheduler that calls these same steps, so the steps must be proven first.

The orchestrator's pipeline steps already exist as standalone scripts in [`bin/`](../bin).
A hand-run is you driving them in order, with the two agent calls (`codex`, `claude`) run on your machine.

## Current first task

The first Phase 0b proof task is Tovi issue [#7](https://github.com/anands14/tovi/issues/7), `Core: create tasks with optional tags`.
The source copy of the issue body is [first-hand-run-task.md](first-hand-run-task.md).
It produced PR [#8](https://github.com/anands14/tovi/pull/8), which is routed `approved,flagged,deviation`.

## Phase 0b findings from task #7

- The review wrapper must parse the reviewer JSON even when the model returns the JSON object inside a Markdown review.
  `bin/review` now handles strict JSON, fenced JSON, and simple `"verdict": "..."` extraction.
- PR body fixes do not reliably refresh `github.event.pull_request.body` for an existing failed `pull_request` workflow run.
  The PR body must satisfy `test-discipline` before the first CI run, or a new commit must trigger `synchronize`.
- no-mistakes caught a real serializer bug outside the original file-scope manifest.
  The code fix was correct, but the routing stayed `flagged,deviation` because the PR declared `Deviations: none`.

## Prerequisites (one-time, all done unless noted)

- Tokens in [`.env`](../.env): agent + orchestrator, with the firewall scopes.
  Verified.
- `no-mistakes init` run in the repo (the `no-mistakes` remote + daemon).
  Verified.
- `fvm` SDK installed (`fvm flutter --version` works).
  Verified.
- A booted iOS simulator for iOS sim-validation (`xcrun simctl boot ...`), or rely on the macOS app for core-only changes.
- **`codex` and `claude` on PATH** - the two agents.
  These are the only steps the framework sandbox can't run; they run in your shell.
- `gh` authenticated as the orchestrator identity for daily-branch integration.
- `gh` authenticated as you for the final PR to `main`.

## The loop, one task

1. **Claim a ready task.**
   ```sh
   gh issue list --label ready
   gh issue edit <n> --add-label in-progress --remove-label ready
   bin/orchestrator ensure-daily-branch --project humanmind
   git checkout -b feat/<slug> origin/day/$(date +%F)      # or: treehouse get --lease
   ```

2. **Implement (codex).** Inject the implementer role + the issue body; codex writes code **and** tests derived from the acceptance criteria.
   Default model: GPT-5.5 high unless the human explicitly overrides.
   ```sh
   codex exec --model gpt-5.5 -c 'model_reasoning_effort="high"' "$(cat skills/pipeline-implementer/SKILL.md)

   Task: $(gh issue view <n> --json body -q .body)"
   ```

3. **Local gate (no-mistakes).** Cheap, on the Mac, before any CI round-trip.
   ```sh
   git push no-mistakes feat/<slug>      # format/lint/test/backend-e2e in a throwaway worktree; opens a draft PR when green
   ```
   Red -> hand codex the logs and re-implement while it accepts the premise and is making material progress.

4. **Sim-validation.** Change-aware; posts the `sim-validation` status.
   ```sh
   bin/sim-validate --pr <N> --post       # add --platform ios|macos|both to force; --dry-run to preview
   ```

5. **CI gate.** The PR triggers GitHub CI (`gate`, whose steps are `format` / `analyze` / `test:fast` / `backend-e2e`, plus `test-discipline`).
   ```sh
   gh pr checks <N> --watch
   ```
   Red -> fix via codex, push to the same PR, and re-gate while progress is material.

6. **Cross-model review (Claude Opus 4.8 Max, on the final SHA).** Posts the `review` status.
   ```sh
   bin/review --pr <N> --post
   ```
   The wrapper defaults to `claude-opus-4-8 --effort max`, accepts `--model <claude-model>` and `--effort <level>` for intentional overrides, and includes the model in the posted status description.
   If Claude cannot run or cannot return a verdict, it falls back to GPT-5.5 xhigh through Codex.
   `request-changes` -> codex addresses, re-gate, and re-review while it accepts the objection.

7. **Daily integration.** Only when all required agent-PR contexts are green.
   ```sh
   bin/orchestrator integrate-pr --project humanmind --issue <issue> --pr <N>
   ```
   This squash-merges the PR into `day/YYYY-MM-DD`, runs the post-merge branch checks, and reverts that PR if the daily branch turns red.
   A reverted PR is commented with the breaking cause and sent back to the agent for repair.

8. **Final daily PR.** At the end of the day, raise or update one PR from the daily branch to `main`.
   ```sh
   bin/orchestrator open-daily-pr --project humanmind --post
   bin/merge <daily-pr>                   # refuses unless this is day/* -> main and final checks are green
   ```

9. **Post-merge.** A bug found later is a new task through this same loop; its repro becomes a permanent regression test.

## Stuck, deferred, and escalation - never spin

Same failing test or same reviewer objection is not automatically stuck if Codex keeps accepting the premise and making material diffs.
Mark `stuck` / `needs-human` when Codex disputes the reviewer or spec, says the spec is unclear or wrong, repeats a protected-path conflict, repeats an architecture invariant violation, makes no material diff, or lacks required external input.
If the per-task window-share ceiling trips while progress is still plausible, label `deferred`, keep the worktree lease, and resume later.

## What to measure (the whole point of the hand-run)

- **Bounce-back rate** - how often the gate or review rejects.
  Validates the implementer/reviewer split.
- **Reviewer false-approval rate** - did review pass something it should not have? The system's #1 metric.
- **Window-share per task** - is one task starving the others?

Record these.
They tune the constitution and the review rubric, and they tell you when the loop is solid enough to automate.

## When it's proven

When hand-runs reliably produce green daily-branch integrations, clean reverts for breakers, and a boring final daily PR, build the orchestrator ([ORCHESTRATOR.md](../ORCHESTRATOR.md)) - it wires these exact steps into the two-window scheduler.
Flip it to unattended only when the safety checks fire: PAUSE halts, a true stuck condition escalates, a plausible long-running task defers and resumes, direct origin push is blocked, a protected-path edit is blocked, and a killed orchestrator alerts.
