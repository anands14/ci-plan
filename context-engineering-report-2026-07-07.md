# Context-engineering report: the Tovi Plan-issues run (2026-07-06/07)

A review of how the 13-issue Tovi Plan flow actually consumed context, why every agent cost about the same regardless of issue size, and a plan to make context acquisition fast and pre-digested instead of re-derived cold each time.

Evidence comes from the 18 subagent transcripts under the run's workflow directory, parsed for tool calls, file reads, and re-derived lessons.

> Revision note (2026-07-07, v2): the first draft mapped every finding to a fix but had holes the user caught on review.
> This version corrects five things: it adds a home for reusable *techniques* (not just decisions/locations), elevates god-file decomposition from a band-aid to a real lever, separates *inject* from *retrieve*, adds a measurement loop, and corrects the assumption that agents will use skills on their own (they will not - measured below).
> The biggest correction is one the first draft missed entirely: the highest-leverage lever is upstream, at issue-decomposition time, not at agent-prompt time.

## TL;DR

The user's instinct is correct and measurable.
Every implementation agent landed in a narrow ~180-290K output-token band regardless of whether the issue was large (#28 sprints) or small (#24 board moves), because a large **fixed context-acquisition cost dominated the small variable per-issue cost**.

Three re-derivation costs drove it:

1. **Same-content re-reads.** The central files were read over and over by nearly every agent - `today_page.dart` was read **99 times across 17 agents**, `task_commands.dart` **45 times across 17 agents**. These files grew to 3,550 and 2,119 lines, so a single full read late in the run was ~40-46K tokens.
2. **Re-derived lessons.** Knowledge one agent worked out, the next re-worked from scratch: **13 of 18 agents** independently dealt with the `test-discipline` CI path-guard (several by failing CI first), **12** independently re-invented the ListView cache-extent `scrollUntilVisible` fix, **5** re-settled the "current sprint" definition.
3. **Gate thrash (wall-clock, not tokens).** Agents ran the full local gate - including `test:fast`, which recompiles the Flutter app - **15 to 24 times each**, which is most of the 12-28 minute per-issue wall-clock.

None of this is a correctness problem - the work is done and doubly reviewed.
It is pure overhead, and it is the overhead the user asked to remove.

The single deepest cause is structural: **13 issues all edited the same 2-3 core files.**
Fix that upstream and most of the rest shrinks on its own.

## What we ran (so this report stands alone)

- One Workflow processed issues #22-#34 **sequentially** (they share core files, so parallel branches would conflict), each on a fresh `git reset --hard` of the day branch.
- Each agent's prompt told it to "Read these files IN FULL before writing any code" (AGENTS.md, CONSTITUTION.md, tasks-plan-issues.md) and to run `gh issue view N`.
- Each agent then implemented TDD, self-reviewed, ran the local gate, opened a PR, and self-merged into `day/2026-07-06`.
- The run hit the Sonnet session limit twice and was resumed; the same run directory holds 18 transcripts (13 issues + integration + review + a few duplicated/partial agents from resumes).

The key structural fact: **each agent started cold with zero memory of any prior agent.**
The only thing carried forward was the merged code - which is exactly why they re-read the growing code to recover what predecessors knew.

## Measured current behavior

### 1. Why every agent cost about the same

Per-agent output tokens ranged 27K-82K and tool calls 95-241, but the *floor* was high and roughly constant because every agent paid the same entry toll:

| Fixed cost paid by nearly every agent | Rough size |
| --- | --- |
| Re-read CONSTITUTION.md | ~3,450 tok |
| Re-read tasks-plan-issues.md | ~2,100 tok |
| Re-read AGENTS.md + PR template + CONTEXT.md glossary | ~1,300 tok |
| `gh issue view N` (1-4x per agent) | ~0.6-2.5K tok |
| Re-read the growing central source files to learn prior work | **tens of thousands of tok** |
| Re-run the full gate 15-24x to converge | wall-clock, not tokens |

The doc re-reads are small (~7K tok).
The **codebase re-reads are the expensive part**, and they grew as the branch grew.

### 2. Same-content re-reads (the dominant cost)

Files read by the most distinct agents:

| # distinct agents | total reads | file |
| --- | --- | --- |
| 17 | 99 | `tovi_app/lib/src/tasks/today_page.dart` |
| 17 | 45 | `tovi_core/lib/src/tasks/task_commands.dart` |
| 17 | 34 | `tovi_app/lib/src/tasks/tasks_controller.dart` |
| 14 | 69 | `tovi_app/test/today_page_test.dart` |
| 13 | 16 | `tovi_core/lib/src/tasks/project.dart` |
| 12 | 15 | `tovi_core/lib/src/tasks/task.dart` |
| 12 | 13 | `tovi_core/lib/src/tasks/plan.dart` |
| 10 | 12 | `tovi_core/lib/src/tasks/sprint.dart` |

The four hot files alone account for ~247 reads.
Every agent adding a widget re-read the whole 2,000-3,500 line `today_page.dart` to find where; every agent adding a command re-read `task_commands.dart`.

### 3. Independently re-derived lessons (redundant work)

| # agents | Re-derived lesson | Type |
| --- | --- | --- |
| 13 | `test-discipline` path-guard: a `tovi_app/lib/**` change must ship an `integration_test/**` file | rule |
| 12 | Widget-test ListView virtualization -> must `scrollUntilVisible` past the cache extent | technique |
| 5 | The working definition of "current sprint" | decision |
| 3 | macOS sim could not foreground -> fall back to the iOS sim | gotcha |

Note the **Type** column - it matters for the plan below.
These are four *different kinds* of knowledge (a rule, a technique, a decision, a gotcha), and a plan that only captures "decisions" and "locations" leaves the technique and the rule to be re-derived.

### 4. Gate thrash

`test:fast` recompiles the Flutter app.
Agents invoked the gate 15-24 times each while iterating - most of the 12-28 min per-issue wall-clock, independent of the token story.

### 5. Agents did not use skills on their own (measured)

Across all 18 subagents and ~2,900 tool calls, the `Skill` tool was invoked **exactly once**, and the word "skill" appears in **zero** of their reasoning texts.
Tool usage was: Bash 1526, Read 470, Edit 240, Write 56, everything else in the single digits.
This is the load-bearing fact for how any of the fixes below get *delivered* - see "Delivery".

## Root causes (all in the orchestration, all fixable)

1. **Issues were not sliced for file-disjointness.** 13 issues editing the same 2-3 files is the deepest cause of both the re-reads and the forced-serial execution.
2. **The prompt forced full cold re-reads.** "Read these files IN FULL" plus a per-agent `gh issue view` re-paid the doc toll every time, though the orchestrator already had the issue body at planning time.
3. **No pre-digested map, and god-files to navigate.** Agents re-derived "where does a widget go" by reading 3,500-line files end to end.
4. **No cross-agent memory.** Clean-checkout isolation is right for *code* but threw away *knowledge*, so lessons were re-learned.
5. **No prompt-cache alignment.** Bespoke per-agent prompts could not share the Anthropic prompt cache.
6. **Gate run as a mid-iteration monolith** instead of a final check.

## The plan

### Guiding principle: push the stable-small, pull the large-variable, and cut redundancy at the source

Two failure modes to avoid.
Injecting too little forces agents to re-derive (what happened here).
Injecting too much bloats every prompt with context that is irrelevant to most agents.
The rule: **inject** the small and always-relevant (invariants, the gate/CI rules, gotchas, techniques, the one issue's body); **let agents retrieve** the large and variable (the codebase, a map) on demand; and **remove** whole categories of re-work upstream so they never need context at all.

The levers below are ordered by true leverage, highest first.

### Lever 0 - Slice issues for file-disjointness (upstream, highest leverage)

The question the first draft never asked: *why did 13 issues all touch the same 2-3 files?*
Because they were sliced by feature-story, not by file-ownership.
If issues are cut as true vertical slices that touch mostly disjoint files (the `to-issues` "independently-grabbable slice" idea), then:

- the same-content re-read problem largely evaporates (each agent's files are mostly its own), and
- safe parallelism becomes possible for free (disjoint files do not conflict - see the parallelization decision in the handoff doc).

This is a change to how specs are authored, not to the orchestrator loop, and it is the one change that fixes context bloat and unlocks parallelism at the same time.
Some shared-core coupling is irreducible (a new field on `Task` touches the core), so this reduces the problem, it does not delete it - which is why the levers below still matter.

### Lever 1 - Decompose the god-files (structural, not a band-aid)

`today_page.dart` at 3,550 lines and `task_commands.dart` at 2,119 lines are the reason a "quick" read costs 40K tokens.
Split them by feature slice (per-tab widget files; per-slice command files) so an agent reads only the slice it touches.
This is a genuine `codebase-design` / `improve-codebase-architecture` task, and it makes Lever 4 (the map) far smaller because there is less to map.
The first draft filed this under a parenthetical "add section anchors"; anchors help navigation but do not cut the read size - decomposition does.

### Lever 2 - Inject a compact brief (the biggest cheap win)

Replace "read three whole docs + `gh issue view`" with one brief the orchestrator pastes into every prompt, containing exactly four buckets - matching the four *types* of re-derived knowledge measured above:

- **Invariants** - the ~15 lines that actually bite (pure-core, files-are-truth, command-core-only, no silent test edits, protected paths), distilled from CONSTITUTION.md, not the whole 183-line file.
- **Rules** - the exact gate and CI commands verbatim, including the `test-discipline` path-guard and the `e2e-exempt` escape, so no agent rediscovers the rule that 13 agents rediscovered.
- **Techniques** - reusable engineering patterns this codebase needs, e.g. the ListView `scrollUntilVisible` fix that 12 agents rediscovered. This bucket is the fix for the "technique" row the first draft had no home for.
- **Gotchas + the inlined issue body** - `fvm` prefix, macOS-foreground -> iOS fallback, the shared id/clock counter caveat, plus the issue's title/what-to-build/acceptance-criteria (the orchestrator already fetched it; agents should not re-run `gh issue view`).

All four are small and relevant to every agent, so they are injected, not retrieved.

### Lever 3 - A cross-agent handoff / decisions log (the "handoff skill" idea, delivered correctly)

An append-only file in the target repo that each implementer writes on finish and reads on start: `{what it built, new public APIs as file:symbol, decisions made, gotchas hit}`.
This is cross-*agent* memory (distinct from the `/handoff` session-to-session doc).
It carries *decisions* (the "current sprint" definition) and *locations* forward so they are read cheaply, not re-derived.
Two hard constraints: it must be append-only and verifiable, and agents must still trust the code over the note for exact signatures (a stale note is worse than none); and parallel agents cannot see each other's not-yet-merged entries, which bounds how much it helps under Lever 0 parallelism.

### Lever 4 - A retrievable codebase map (pull, not push)

A short "where things live" file the agent greps on demand - not injected into every prompt.
Once Lever 1 shrinks the files, this map is small.
Keep it a retrieval target so a prompt does not carry map lines irrelevant to the current issue.

### Lever 5 - Prompt-cache alignment

Put Lever 2's brief as a byte-identical prefix at the top of every agent prompt, per-issue tail last.
The Anthropic prompt cache keys on shared prefixes, so subsequent agents in a window pay near-zero for the shared preamble.
Free once Lever 2 exists.

### Lever 6 - Cut the gate thrash

Iterate with the **scoped** test for the file under work; run the **full** four-command gate **once** before the PR.
Split fast checks (`format`/`analyze`) from the slow Flutter compile (`test:fast`).
Biggest wall-clock win; does not touch tokens.

### Delivery: skills will not self-activate - this changes how every lever ships

Measured above: agents used `Skill` once in ~2,900 tool calls.
Skills fire either by model-selection (description-matched, unreliable) or explicit invocation, and the `handoff` skill even carries `disable-model-invocation: true`, so it cannot self-fire.
For a *reliable* pipeline you cannot depend on a headless subagent choosing a skill.
Therefore:

- Deliver a skill's *content* by **inlining it into the injected brief** (Lever 2) wherever the knowledge is what matters - there is then nothing to "invoke".
- Reserve actual skill **invocation** for the few steps where the orchestrator **explicitly commands it** in the prompt (e.g. tell the dedicated merge agent to run `resolving-merge-conflicts`).
- Treat skills mainly as *sources of content and standardized procedure*, not as behavior the agent will opt into.

This is why Lever 2 (orchestrator-owned injection), not "adopt skills", is the backbone.

### On the two ideas the user named

- **Glossary:** a domain glossary already exists (CONTEXT.md). It was not the bottleneck - no agent struggled with what a "sprint" means. The missing glossary is of *code locations and decisions* (Levers 3/4).
- **Handoff skill:** right as a *pattern* (Lever 3), but no dedicated handoff skill is installed and, per Delivery, it must ship as an orchestrator-baked read/write step, not a skill the agent is trusted to invoke.

## How we will know it worked (the measurement loop)

"Cut substantially" is not verifiable, so instrument the next run and compare against this baseline by re-running the same transcript parse:

| Metric | This run (baseline) | Target next run |
| --- | --- | --- |
| Distinct agents that re-read `today_page.dart` | 17 (99 reads) | sharply down after Levers 1/4 |
| Instances of a re-derived rule/technique (test-discipline, ListView) | 13 and 12 | near zero after Lever 2 |
| Full-gate runs per agent | 15-24 | single digits after Lever 6 |
| Per-agent token spread | clustered ~180-290K | should start to **vary with issue size** |

That last row is the real proof: once the fixed overhead is gone, cost should track actual issue complexity instead of clustering.
If it still clusters, the overhead is not gone.

## Recommended sequence

1. **Lever 2 + Lever 6** first - pure prompt/process changes, no repo edits, immediate token and wall-clock win, and Lever 2 is where skill *content* gets inlined.
2. **Lever 3** - the handoff log, as an orchestrator-baked step (not a skill).
3. **Lever 0** - fold file-disjointness into the spec-authoring step for the next feature; this also unlocks the parallelization decision (see the handoff doc's Task 3).
4. **Lever 1** - decompose the god-files as its own reviewed change; Levers 4 and 5 fall out cheaply afterward.
5. Instrument the run per the measurement loop and compare.

This plan is app-agnostic and belongs in the framework repo's orchestration contract, so every future managed project inherits it - not just Tovi.
