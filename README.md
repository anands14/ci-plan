# Agent Development Pipeline (project-agnostic)

A reusable, supervised-autonomy development pipeline you point at any repository.
Agents plan, implement, test, review, and integrate work into a daily branch unattended; a human reviews and merges one final PR to `main` in an evening session.

This repository is **the framework**.
It is deliberately app-agnostic so the same setup runs across many projects.
The code being built lives in a **separate target repository** with its own constitution, checks, and acceptance criteria.

See [PLAN.md](PLAN.md) for the full design and rationale, and [CONSTITUTION.md](CONSTITUTION.md) for the normative process rules every project inherits.

## The seam

The framework and a target project are cleanly separated.
Nothing project-specific lives here.

| Lives in this framework repo (agnostic) | Lives in each target repo (project-specific) |
| --- | --- |
| The process rules ([CONSTITUTION.md](CONSTITUTION.md)) | The codebase |
| The orchestrator, scheduler, local run ledger, and basic checklist generator | The project constitution (architecture invariants, conventions, glossary) |
| The role skills for implementer / reviewer / advisor ([skills/](skills/)) | The `.no-mistakes.yaml` check commands for that stack |
| The per-project config schema ([templates/project.config.example.yaml](templates/project.config.example.yaml)) | The acceptance criteria, in that repo's issues |
| Setup automation for the GitHub spine (later) | This repo's own `AGENTS.md`/`CLAUDE.md` redirect (see below) |

Spec-authoring isn't in either column as a pipeline role - it's an interactive session (the global `grilling` + `to-tickets` skills) that happens before any issue exists. See "How it works" below.

The bridge between the framework and a target repo is a **per-project config file** that names the target repo, which model/effort each role (implementer, reviewer, advisor) runs as, the window settings, the check commands, and the path to that project's constitution.

Entry points:

```sh
bin/orchestrator preflight --project tovi
bin/orchestrator run --project tovi          # one full tick: frontier -> claim-all -> pipeline -> integrate
bin/orchestrator run --project tovi --poll    # loop until there's nothing left to do
bin/orchestrator open-daily-pr --project tovi --post
```

`bin/orchestrator run` is what "start the automated process" means in this framework - not a chat request to an interactive coding session (see the repo-root `AGENTS.md` for why, and what to do instead if that's what you were about to do).

## How it works (in one paragraph)

Someone authors tasks interactively - a `grilling` session to shape the plan, then `to-tickets` to publish vertical-slice issues with real `Blocked by #N` edges and file-scope manifests - and applies `ready` to the ones with no open blocker.
From there the framework is unattended: it wakes from GitHub events or periodic reconciliation, promotes `blocked` issues to `ready` the moment their declared blockers close, and claims *every* currently-safe `ready` issue at once - no fixed worker-count cap, just the dependency frontier and file-scope collisions (an undeclared overlap goes to a human; a declared or in-flight one is serialized instead of run alongside).
For each claimed task, an implementer agent writes code plus tests from the acceptance criteria in an isolated leased worktree, a cheap deterministic gate runs first, and only then does a reviewer agent review the green final SHA - which can be the same model as the implementer, since no invariant forbids it (the human owns that decorrelation call consciously at the one gate where it matters, described below).
Either role may consult an on-demand advisor once, mid-turn, on a specific question instead of guessing; the orchestrator does the same automatically, once, before it would otherwise give up on a task as stuck.
Approved work is routed as `clean` or `flagged`, then a separate integration lane serially merges it into `day/YYYY-MM-DD`.
After each daily-branch merge, the branch checks run on the combined branch.
If they fail, the integration lane reverts the just-merged PR, comments with the breaking cause, and sends the task back for repair.
If they pass, the integration lane marks the task integrated and closes the GitHub issue immediately.
At the end of the day the orchestrator opens one PR from the daily branch to `main`; only the human approves and merges that final PR, optionally with a consciously different reviewer model for that one look.
The full mechanism, guardrails, and budget model are in [PLAN.md](PLAN.md).

## Runtime Dependencies

The framework calls these tools as installed CLIs.
Their source repos are not vendored here.

- `treehouse` for leased worktree isolation.
- `no-mistakes` for the local gate and PR handoff.
- `codex` and/or `claude` for the implementer, reviewer, and advisor roles - whichever CLI a role's configured model resolves to (`orchestrator/config.py:infer_tool`).
  No role is hardcoded to a specific tool; `projects/<name>.yaml` names the model, the tool follows.
- `gh` for GitHub issue, PR, and check reads.

## Registering a target project

1. Copy [templates/project.config.example.yaml](templates/project.config.example.yaml) to `projects/<name>.yaml` and fill it in - including which model runs implementer, reviewer, and advisor.
2. In the target repo, copy [templates/project-constitution.template.md](templates/project-constitution.template.md) to its constitution path and fill in the architecture invariants and conventions for that stack.
3. In the target repo, copy [templates/application-driving-contract.template.md](templates/application-driving-contract.template.md) to `docs/APP_DRIVING.md` and fill in the stable hooks, commands, fixtures, persistence assertions, simulator targets, logs, protected paths, and shared helpers that agents should use.
4. Symlink the role skills and the process constitution into the target repo, scoped to that repo (never globally): the [skills/](skills/) directories into the repo's `.claude/skills/` and the Codex skills location, and [CONSTITUTION.md](CONSTITUTION.md) where its `AGENTS.md`/`CLAUDE.md` references it.
   Symlinks keep one source of truth and add zero token cost to non-pipeline repos.
5. Add a `.no-mistakes.yaml` to the target repo with its test/lint/format commands.
6. Provision the GitHub spine on the target repo (labels, merge enforcement, the spec-issue template).
   Automation for this comes later; until then it is a documented manual checklist.
7. Author the first batch of tasks with `grilling` + `to-tickets`, publishing real `Blocked by #N` edges - that's what lets the orchestrator compute the frontier on its own instead of you hand-sequencing waves.

## Status

Designed 2026-06-27; re-evaluated 2026-06-30 and 2026-07-09 (model-agnostic roles, the advisor role, unbounded frontier-based concurrency - see [DECISIONS.md](DECISIONS.md) D8).
The orchestrator, generic role dispatch, the advisor, and the frontier/claim-all scheduler are built and tested; `bin/orchestrator run [--poll]` is the entry point.
Not yet done: a `launchd` plist for an always-on daemon (a per-machine setup step, not code this repo ships).
