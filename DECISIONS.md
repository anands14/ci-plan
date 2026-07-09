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

## D8 - 2026-07-09 re-evaluation: model-agnostic roles, an advisor role, unbounded frontier-based concurrency

**Decision.** Grilled and built four changes together, since each depended on the others holding: (1) every role (implementer, reviewer, advisor) resolves its CLI generically from its configured model, with no role hardcoded to Codex or Claude; (2) the "reviewer must be a different model family" invariant is gone, not relaxed - same-model implement/review is allowed, and the human owns decorrelation consciously at the daily-branch-to-main gate instead, which stays a manual step, not a built lane; (3) a new **advisor** role - an on-demand, bounded consult, not a standing gate - invoked proactively via a structured `advisor_request` field or reactively as a one-time backstop before a task is marked `stuck`; it folds in what used to be a separate "advisory checker" role; (4) `implementers_max` is gone as a fixed worker-count cap - concurrency is bounded only by the dependency frontier (`Blocked by #N` edges, auto-advanced as they close) and file-scope collisions (undeclared overlap -> a human; declared or in-flight overlap -> serialize, don't reject).

**Why.** The user wanted to point different models at different roles without code changes, noticed the pipeline had no "ask a smarter model when stuck" mechanism, and wanted agents to parallelize freely across however many issues are actually safe to run at once rather than a fixed worker count. Cost analysis (current published pricing) confirmed a live LLM-in-the-loop scheduler would run ~$100-500/month for near-zero marginal decision value over deterministic frontier/collision math, so the scheduler itself stayed deterministic; the advisor covers the genuinely hard cases instead, on demand only.

**Spec-authoring dropped as a pipeline role.** `pipeline-spec-author` is deleted. The user's actual practice is a `grilling` session to shape a plan, then the global `to-tickets` skill to publish vertical-slice issues with real blocking edges and a "quiz the user" step - better than the old headless, no-human batch generator, and it's what makes the frontier computable without a hand-written wave-plan. The automated loop's scope now starts at "claim a `ready` issue."

**Skills consolidated.** `pipeline-implementer` wraps the global `implement` skill (overriding only self-review and final-commit, which don't fit a gated pipeline); `pipeline-reviewer` wraps the global `code-review` skill (its Spec/Standards axes cover criteria-correctness and constitution-conformance; test-honesty and routing stay pipeline-specific); `pipeline-advisor` (new, replacing `pipeline-advisory-checker`) leans on `diagnosing-bugs` and `codebase-design` instead of inventing its own method.

**Consequence.** `CONSTITUTION.md`, `PLAN.md`, `ORCHESTRATOR.md`, and `README.md` were rewritten to match: role descriptions are model-agnostic, the per-task loop includes the advisor consult and unbounded claiming, the budget model is windows-per-tool instead of "Codex window / Claude window," and the entry point is `bin/orchestrator run [--poll]` - built, tested, not yet wired into a `launchd` daemon (that's a per-machine setup step). `projects/humanmind.yaml` and the config template gained an `agents.advisor` block and a `windows:` map keyed by tool.

**Reverse.** Set an explicit `tool:` override per role in `projects/<name>.yaml` to pin a CLI regardless of model-name inference. Re-add a per-project `implementers_max` read in `queueing.claim_all_ready` if a hard ceiling is ever wanted again; the deterministic scheduler and the advisor's one-round-trip cap are otherwise unaffected. `pipeline-advisory-checker` and `pipeline-spec-author` are recoverable from git history if a narrower checker role or a headless batch spec-author is ever wanted again.

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
