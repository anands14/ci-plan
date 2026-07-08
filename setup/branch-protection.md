# Merge enforcement - keeping "only a human merges to main, and only green daily PRs reach main" true

This is what makes the merge gate real rather than a request agents are trusted to honor.
How it is enforced depends on the repo's GitHub plan.

## Reality check: branch protection needs a paid plan on private repos

On a **private repo on the GitHub Free plan, branch protection and required status checks are unavailable** - the API returns `403: Upgrade to GitHub Pro or make this repository public`.
The first project (`anands14/tovi`) is private and chose **no Pro**, so its final `main` merge gate is **orchestrator-enforced**, not platform-enforced.
The platform-enforced version (for any repo with Pro/Team/Enterprise, or a public repo) is in the appendix.

## Private Free model (default; no branch protection)

Two things must hold: no agent merges to `main`, and only *green* daily PRs merge to `main`.

- **Nothing auto-merges to main.** The integration lane may squash-merge approved agent PRs into `day/YYYY-MM-DD`.
  The orchestrator and agents must never merge a PR whose base is the default branch.
  This cannot be enforced by token scope alone (see the firewall note), so it rests on the orchestrator code routing merges only through the daily branch and on the human using `bin/merge` for the final PR.
- **Agents cannot push origin.** The unattended default is an agent-owned fork or agent-owned remote.
  Workers must not be able to push directly to origin.
  The orchestrator preflight refuses to start unattended workers if origin is writable from the worker environment.
- **Only green daily branches advance.** The integration lane re-reads the real required pre-integration contexts on each agent PR - `gate`, `test-discipline`, `sim-validation`, and `review` - and refuses unless all are green.
  After it squash-merges one PR into the daily branch, it runs the configured post-merge checks on the combined branch.
  If those checks fail, it reverts that PR and asks the owning agent to fix and raise again.
- **Only green final PRs reach main.** The human merges with a **`merge <pr>` command**, not the web-UI button.
  It refuses unless the PR base is the default branch, the PR head is a daily branch, and the final contexts `gate`, `test-discipline`, and `daily-integration` are green.
  The final PR uses a merge commit so the daily branch's per-agent squash commits remain visible.
  This turns discipline into a locally-enforced gate.
- **Residual hole (accepted):** the human can still bypass via the web UI.
  That is now a self-discipline boundary, not a wall - the price of no Pro.

## The token firewall - what scope CAN and CANNOT enforce

Two firewalls, and on the Free plan they are not equal:

- **Status firewall - holds.** "Commit statuses" is a distinct fine-grained permission.
  An agent token *without* it cannot post `sim-validation`, `review`, or `daily-integration`.
  The thing being judged never holds the pen.
  **Real boundary.**
- **Merge firewall - does NOT hold without branch protection.** "Merge a PR" is not a separate permission; it needs **Contents: write**, the same permission the agent needs to push branches.
  You cannot grant push-but-not-merge.
  So "agents never merge to main" is enforced by the orchestrator + the `merge` command, not by scope.

For unattended operation, use a fork workflow or equivalent agent-owned remote: the agent gets write access only to its fork/remote and read-only access to the origin repository.
It can open PRs against origin, but it cannot merge or push origin branches.
The same-repo degraded model is weaker and is allowed only for supervised hand-runs.

### Token checklist

- **Agent token** (codex / the implementer) - fine-grained PAT, repository access = **write only to the agent fork/remote** and read-only to origin:
  - Contents: **Read and write** on the agent fork/remote; read-only on origin
  - Pull requests: **Read and write** (open PRs)
  - Issues: **Read and write** (claim / label tasks)
  - Metadata: **Read** (required)
  - Commit statuses: **none** <- the status firewall
- **Orchestrator token** (posts statuses and runs the daily integration lane; never passed to workers) - separate token:
  - Commit statuses: **Read and write** <- the only token that may attest
  - Contents / Pull requests: **Read and write** for the canonical repo if this identity performs daily-branch merges and reverts
  - Issues: **Read and write** if this identity comments on integration failures
- **Human credentials** - the only identity that runs the final `gh pr merge` to `main` through `bin/merge`.

## Worker credential preflight

Before unattended mode, the orchestrator must verify:

- worker env has no human `GH_TOKEN`;
- worker env has no orchestrator status token;
- worker env has no SSH agent socket that can push origin;
- worker `HOME` is the dedicated agent home;
- `git push origin` cannot succeed from the worker context;
- the configured agent remote/fork can accept branch pushes.

## CODEOWNERS

Add `CODEOWNERS` making the human the owner of the protected paths.
Note: without branch protection, CODEOWNERS **requests** review but cannot **require** it - so on the Free plan it is routing, not enforcement (the `merge` command is the enforcement).
It becomes enforcing the moment branch protection is enabled.

```
# .github/CODEOWNERS
*                          @anands14
docs/CONSTITUTION.md       @anands14
/.github/                  @anands14
/.no-mistakes.yaml         @anands14
```

## Appendix - platform-enforced model (repo has Pro/Team/Enterprise, or is public)

If you upgrade or make the repo public, enable branch protection on the default branch; the gate becomes platform-enforced - stronger, and it closes the web-UI bypass:

- Require a pull request before merging; no direct pushes, including by the framework's own credentials.
- Require status checks to pass on the final PR: `gate`, `test-discipline`, `daily-integration`.
- Require review from `CODEOWNERS`; the agent tokens have no approval/merge permission, so the approval can only be the human's.
- Require conversation resolution; require branches up to date before merging.
- Do not allow force pushes; do not allow deletions.
- Include administrators only if you want the rule to bind you too; otherwise the human merges as admin.

With this on, the `merge <pr>` command becomes a convenience rather than the enforcement.
