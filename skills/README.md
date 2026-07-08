# Pipeline role skills - how they are delivered

These four skills (`pipeline-implementer`, `pipeline-reviewer`, `pipeline-advisory-checker`, `pipeline-spec-author`) are the role wiring the orchestrator hands to an agent. They are **not** symlinked into the global skill set, and that is deliberate.

## Why not global symlinks

The global skill set (`~/.config/ai/skills/` → both agents) is for *generally useful* capabilities - `tdd`, `codebase-design`, `domain-modeling`, `grilling`. Those earn their always-on description cost because they help in any repo.

The pipeline role skills are the opposite: they are useful *only* during a pipeline run, and only to the agent currently assigned that role. Symlinking them globally would put always-on descriptions in every unrelated coding session for zero benefit there. Inspection also confirmed Codex discovers skills only at the global level (`~/.codex/skills/`), so "scope them per-project for Codex" is not available the way it is for Claude.

## How they are delivered instead: orchestrator injection

The orchestrator owns control flow and drives the agents (`codex exec`, `claude -p --model claude-opus-4-8`).
It assigns a role by **injecting that role skill's body into the invocation prompt** for the one task at hand.
This is:

- **Zero-cost everywhere else** - nothing is always-on; the role text exists only inside the one run that uses it.
- **Tool-agnostic** - the same markdown injects into Codex or Claude; no dependency on per-tool skill discovery.
- **Consistent with the architecture** - agents think, skills instruct, tools execute, and the orchestrator does the wiring.

The role skills reference the *capability* skills by name (`use the tdd skill`). Those resolve because the capabilities are globally discoverable to both agents already.

## Manual hand-run (Phase 0b, before the orchestrator exists)

Until the orchestrator is built, inject by hand. For example:

```sh
codex exec "$(cat skills/pipeline-implementer/SKILL.md)

Task: <issue link or acceptance criteria>"
```

For Claude specifically, you may instead symlink a single role skill into one project's `.claude/skills/` to get `/pipeline-implementer` invocation in that repo only - but never globally.

## Reversal

If you prefer native discovery over injection, symlink `skills/pipeline-*` into `~/.config/ai/skills/` and both agent dirs using your standard per-skill pattern (preserving Codex's `.system/`), and keep the descriptions tight since they become always-on. See [DECISIONS.md](../DECISIONS.md) decision D1.
