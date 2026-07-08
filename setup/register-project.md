# Registering a target project

The checklist to bring a repository under pipeline management.
Manual for now; the orchestrator's `setup` command automates it later (see [ORCHESTRATOR.md](../ORCHESTRATOR.md)).
Nothing here is stack-specific until step 3.

## In the framework repo

1. **Config.** Copy [templates/project.config.example.yaml](../templates/project.config.example.yaml) to `projects/<name>.yaml` and fill it in: target repo, agent remote/fork, agents, worker environment, loop controls, concurrency, wakeups, review routing, daily integration, and validation rules.

## In the target repo

2. **Project constitution.** Copy [templates/project-constitution.template.md](../templates/project-constitution.template.md) to the path named in the config (e.g. `docs/CONSTITUTION.md`) and fill in the architecture invariants, conventions, glossary, and check commands for this stack.
   Reference it (and note the agnostic process rules) from `AGENTS.md` / `CLAUDE.md` so both tools auto-load it, cached.

3. **Application driving contract.** Copy [templates/application-driving-contract.template.md](../templates/application-driving-contract.template.md) into the target repo, usually as `docs/APP_DRIVING.md`, and fill in the stable navigation hooks, selectors, fixtures, reset commands, validation matrix, simulator targets, persistence contract, logs, protected paths, and shared helpers.
   Reference it from `AGENTS.md` / `CLAUDE.md` next to the project constitution.
   This is the reusable target-app contract that keeps future apps from requiring Tovi-specific rediscovery.

4. **Gate.** Add `.no-mistakes.yaml` with this stack's `commands.{build,test,lint,format}`.
   Keep `ci_autofix` off (decision D2), because the orchestrator-owned Codex loop is the only fix loop.
   `no-mistakes init` sets up the local gate remote.

5. **Spine.**
   - Labels: provision the set in [labels.yaml](labels.yaml) (`gh label create ...`).
   - Branch protection + `CODEOWNERS`: apply [branch-protection.md](branch-protection.md).
   - Issue + PR templates: copy [templates/spec-issue.md](templates/spec-issue.md) to `.github/ISSUE_TEMPLATE/task.md` and [templates/pull-request.md](templates/pull-request.md) to `.github/pull_request_template.md`.

6. **Credentials.** Create the tokens from [branch-protection.md](branch-protection.md): an **agent token** that can write only to the agent fork/remote and has no Commit statuses permission, and an **orchestrator token** that can post statuses and operate the daily integration branch.
   Human `gh` auth remains the only identity that runs `bin/merge` for the final PR to `main`.

7. **Worker environment.** Create the dedicated worker `HOME`, configure the agent remote/fork, and verify the worker env does not expose human GitHub auth, the orchestrator token, or an SSH agent socket that can push origin.

## Role skills

No global symlink step.
Role skills are injected by the orchestrator (decision D1); for a hand-run, inject by hand per [skills/README.md](../skills/README.md).

## Verify before the first run

- A test push to the gate opens a PR and does **not** merge it.
- The `ready` label exists and the implementer claims only `ready` issues.
- The orchestrator rejects malformed `ready` issues before claim.
- `docs/APP_DRIVING.md` exists in the target repo and names stable hooks for the first workflows agents will drive.
- The agent token cannot post `sim-validation`, `review`, or `daily-integration` statuses.
- The worker cannot push to origin.
- The worker can push to the configured agent remote/fork.
- The integration lane refuses an approved PR with missing required contexts.
- The integration lane reverts a just-merged PR if the daily branch checks fail.
- The `merge <pr>` command refuses non-daily heads, wrong bases, missing final contexts, and red checks.
