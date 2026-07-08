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
| The orchestrator, scheduler, local run ledger, and basic checklist generator (later) | The project constitution (architecture invariants, conventions, glossary) |
| The role skills for implementer / reviewer / checker / spec-author ([skills/](skills/)) | The `.no-mistakes.yaml` check commands for that stack |
| The per-project config schema ([templates/project.config.example.yaml](templates/project.config.example.yaml)) | The CI workflows for that stack |
| Setup automation for the GitHub spine (later) | The acceptance criteria, in that repo's issues |

The bridge between them is a **per-project config file** that names the target repo, the agents to use, the window settings, the check commands, and the path to that project's constitution.

Current Phase 0c entry points:

```sh
bin/orchestrator preflight --project humanmind
bin/orchestrator integrate-next --project humanmind
bin/orchestrator open-daily-pr --project humanmind --post
```

## How it works (in one paragraph)

The framework reads a project config, wakes from GitHub events or periodic reconciliation, and keeps worker slots filled from strict `ready` issues.
For each task, an implementer agent writes code plus tests from the acceptance criteria in an isolated leased worktree, a cheap deterministic gate runs first, and only then does a different-model reviewer agent review the green final SHA.
Approved work is routed as `clean` or `flagged`, then a separate integration lane serially merges it into `day/YYYY-MM-DD`.
After each daily-branch merge, the branch checks run on the combined branch.
If they fail, the integration lane reverts the just-merged PR, comments with the breaking cause, and sends the task back for repair.
At the end of the day the orchestrator opens one PR from the daily branch to `main`; only the human approves and merges that final PR.
The full mechanism, guardrails, and budget model are in [PLAN.md](PLAN.md).

## Registering a target project

1. Copy [templates/project.config.example.yaml](templates/project.config.example.yaml) to `projects/<name>.yaml` and fill it in.
2. In the target repo, copy [templates/project-constitution.template.md](templates/project-constitution.template.md) to its constitution path and fill in the architecture invariants and conventions for that stack.
3. In the target repo, copy [templates/application-driving-contract.template.md](templates/application-driving-contract.template.md) to `docs/APP_DRIVING.md` and fill in the stable hooks, commands, fixtures, persistence assertions, simulator targets, logs, protected paths, and shared helpers that agents should use.
4. Symlink the role skills and the process constitution into the target repo, scoped to that repo (never globally): the [skills/](skills/) directories into the repo's `.claude/skills/` and the Codex skills location, and [CONSTITUTION.md](CONSTITUTION.md) where its `AGENTS.md`/`CLAUDE.md` references it.
   Symlinks keep one source of truth and add zero token cost to non-pipeline repos.
5. Add a `.no-mistakes.yaml` to the target repo with its test/lint/format commands.
6. Provision the GitHub spine on the target repo (labels, merge enforcement, the spec-issue template).
   Automation for this comes in Phase 0c; until then it is a documented manual checklist.

## Status

Designed 2026-06-27.
Building the app-independent substrate through thin, runnable Phase 0c slices.
See [PLAN.md](PLAN.md) section 11 for the build sequence.
