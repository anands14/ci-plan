# Decisions log

Decisions I made autonomously on 2026-06-27 while you were away, finishing the app-independent framework.
Each notes why and how to reverse.
Nothing here touches HumanMind beyond the existing stub, and nothing was committed, pushed, or symlinked into your global environment.

---

## D1 - Role skills are injected, not globally symlinked (reverses our earlier plan)

**Decision.** The four `pipeline-*` role skills are delivered by the orchestrator injecting their body into each invocation, not by symlinking them into `~/.config/ai/skills/` and the agent dirs.
See [skills/README.md](skills/README.md).

**Why.** Inspecting your setup confirmed skills are discovered globally and Codex only at `~/.codex/skills/`.
The global set is for *generally useful* capabilities (`tdd`, `grilling`, ...); the role skills are pipeline-only, so symlinking them globally would pay an always-on description cost in every unrelated session for no benefit there - exactly the token cost you flagged.
Injection is zero-cost elsewhere, tool-agnostic, and matches "the orchestrator owns control flow."

**Consequence.** No new global skill dir was created, so **this Claude session needs no restart and there is nothing for Codex to re-discover.** The capability skills you already have (confirmed present and symlinked to both agents) are what the role skills reference.

**Reverse.** If you prefer native `/pipeline-implementer` discovery, symlink `skills/pipeline-*` into `~/.config/ai/skills/` + both agent dirs with your per-skill pattern (preserve Codex `.system/`), keeping descriptions tight.
Then restart Claude and confirm Codex discovery.

## D2 - no-mistakes `ci_autofix` defaults off

**Decision.** Project configs set `gate.ci_autofix: off`.

**Why.** The spike found no-mistakes' CI auto-fix is bounded by an idle timeout, not by our stuck/deferred rules, so left on it could burn a subscription window.
Our fix loop lives in the orchestrator.
Reverse by setting it on per project if you ever want it, tightly bounded.

## D3 - Orchestrator designed, not yet runnable

**Decision.** Wrote [ORCHESTRATOR.md](ORCHESTRATOR.md) (a full blueprint) instead of building the runnable orchestrator.
The existing `orchestrator/github.py` helper is only a small GitHub wrapper stub, not the daemon or task loop.

**Why.** Two reasons.
First, our own Phase 0 rule: automate the proven process *last*, after the hand-run on a real project - which we do together.
Building it now would automate an unproven loop against a target that does not exist yet.
Second, it is untestable in this environment (no `go`, no `codex`/`claude` CLIs here).
Shipping untested orchestration would be the opposite of best work.
The blueprint and helper stub make Phase 0c a short, eyes-open build.

**Reverse.** Nothing to undo; it is a design doc.
If you wanted code now, tell me and we will scope a testable slice.

## D4 - Built the GitHub-spine substrate

**Decision.** Added [setup/](setup/): the label state machine ([labels.yaml](setup/labels.yaml)), [branch-protection.md](setup/branch-protection.md), the [spec-issue](setup/templates/spec-issue.md) and [PR](setup/templates/pull-request.md) templates, and the [register-project.md](setup/register-project.md) checklist.
All app-independent.

**Why.** It is the last app-independent substrate before a run, and it makes registration a checklist.
Label names, colors, and the branch-protection specifics are my choices - adjust freely.

## D5 - `.gitignore` added; clones left in place; no `git init`

**Decision.** Added [.gitignore](.gitignore) excluding the four reference clones (kept where they are, per your earlier wish) and scratch files.
I did **not** run `git init` or commit anything.

**Why.** A framework repo will want version control, but how and when to initialize (and whether to create the GitHub repo first) is your call and your remote/identity.
The `.gitignore` is ready for whenever you init.
Reverse by deleting it.

## D6 - HumanMind left as a stub

**Decision.** [projects/humanmind.yaml](projects/humanmind.yaml) stays a stub with stack-dependent fields as TODO.
I did not create its constitution, `.no-mistakes.yaml`, or any code.

**Why.** You said HumanMind we do together, and its stack is pending a grill session.
Nothing to reverse.

## D7 - 2026-06-30 re-evaluation: private Mac daemon, strict ready queue, and agent-owned remote

**Decision.** Keep the repo private and build a deterministic Mac-local orchestrator instead of adopting Sandcastle or making the repo public for platform-enforced gates.
The orchestrator is persistent, but LLM workers are invoked only for concrete task steps.
GitHub events wake the daemon, while periodic reconciliation remains the safety net.
Only the orchestrator claims `ready` issues.
Workers write only to an agent-owned fork or remote, not directly to origin.

**Why.** The user wants 4-5 parallel task loops eventually, but without paying GitHub Pro or exposing the repo.
A persistent ordinary-code daemon has trivial token cost while idle.
The expensive parts are only Codex implementation, Claude review, optional advisory checks, and conflicted/non-trivial fixes.
Strict `ready` preflight protects token budget by keeping vague issues out of the queue.

**Consequence.** Fixed attempt caps are replaced by progress-based `stuck` and fairness-based `deferred`.
Same failing test or same reviewer objection is not automatically stuck if Codex accepts the premise and keeps making material diffs.
`clean` and `flagged` labels route human review depth.
The evening report is token-free and basic.

**Reverse.** If you later buy GitHub Pro or make the repo public, enable platform branch protection and required checks.
If Sandcastle later fits better, treat it as a runner dependency under our state machine rather than replacing the GitHub-label lifecycle model.

---

## What I deliberately did NOT do

- No global symlinks, so no environment change and no session restart needed (D1).
- No runnable orchestrator daemon or task loop (D3).
- No `git init`, commit, or push (D5).
- Nothing inside the HumanMind folder (D6).

## Suggested next steps (for when you're back)

1. Skim [CONSTITUTION.md](CONSTITUTION.md) and the four [skills/](skills/) - they are load-bearing.
2. Decide D1 (injection vs global symlinks) and D5 (`git init` now or later).
3. Run the HumanMind tech-stack grill together; it unblocks `humanmind.yaml`, HumanMind's constitution, and its `.no-mistakes.yaml` in one pass.
