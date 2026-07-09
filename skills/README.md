# Pipeline role skills - how they are delivered

Three skills - `pipeline-implementer`, `pipeline-reviewer`, `pipeline-advisor` - are the role wiring the orchestrator hands to an agent. They are **not** symlinked into the global skill set, and that is deliberate.

Spec-authoring is not a fourth pipeline role. It happens interactively, before any issue exists, using the global `grilling` and `to-tickets` skills - see [PLAN.md](../PLAN.md) section 2 and [README.md](../README.md).

## Why not global symlinks

The global skill set (`~/.config/ai/skills/` → both agents) is for *generally useful* capabilities - `tdd`, `code-review`, `codebase-design`, `domain-modeling`, `diagnosing-bugs`, `grilling`, `to-tickets`. Those earn their always-on description cost because they help in any repo.

The pipeline role skills are the opposite: they are useful *only* during a pipeline run, and only to the agent currently assigned that role. Symlinking them globally would put always-on descriptions in every unrelated coding session for zero benefit there. Inspection also confirmed Codex discovers skills only at the global level (`~/.codex/skills/`), so "scope them per-project for Codex" is not available the way it is for Claude.

## How they are delivered instead: orchestrator injection

The orchestrator owns control flow and drives the agents through one generic dispatcher (`orchestrator/config.py:infer_tool` resolves the CLI from whichever model a role is configured with - no role is hardcoded to Codex or Claude).
It assigns a role by **injecting that role skill's body into the invocation prompt** for the one task at hand.
This is:

- **Zero-cost everywhere else** - nothing is always-on; the role text exists only inside the one run that uses it.
- **Tool-agnostic** - the same markdown injects regardless of which CLI a role resolves to; no dependency on per-tool skill discovery.
- **Consistent with the architecture** - agents think, skills instruct, tools execute, and the orchestrator does the wiring.

The role skills delegate to *capability* skills wherever one already exists, rather than restating it:

- `pipeline-implementer` wraps the global `implement` skill (which pulls in `tdd`), overriding only the self-review and final-commit steps that don't fit a gated pipeline.
- `pipeline-reviewer` wraps the global `code-review` skill (its Spec axis is criteria-correctness, its Standards axis is constitution-conformance and architecture) and adds only the pipeline-specific test-honesty audit and routing/JSON contract.
- `pipeline-advisor` leans on `diagnosing-bugs` and `codebase-design` rather than inventing its own diagnostic method.

Those capability skills resolve because they are globally discoverable to both agents already.

## The advisor: a third role, not a bigger reviewer

`pipeline-advisor` is an on-demand consult, not a gate. It is invoked two ways, both bounded to one round-trip:

- **Proactively** - the implementer or reviewer sets `advisor_request: {question, context}` in its structured JSON output instead of guessing or escalating straight to a human.
- **Reactively** - the orchestrator's deterministic stuck-classifier (`orchestrator/outcomes.py`) consults the advisor once, automatically, right before it would otherwise mark a task `stuck` - see `orchestrator/agents.py:_consult_advisor_and_retry`.

Either way, the advisor never gates, never reviews a diff end to end, and is never itself the reviewer - it answers one question and hands control back.

## Manual hand-run (Phase 0b)

Inject by hand for a single step, e.g.:

```sh
codex exec --model gpt-5.5 -c 'model_reasoning_effort="high"' "$(cat skills/pipeline-implementer/SKILL.md)

Task: <issue link or acceptance criteria>"
```

For Claude specifically, you may instead symlink a single role skill into one project's `.claude/skills/` to get `/pipeline-implementer` invocation in that repo only - but never globally.

## Reversal

If you prefer native discovery over injection, symlink `skills/pipeline-*` into `~/.config/ai/skills/` and both agent dirs using your standard per-skill pattern (preserving Codex's `.system/`), and keep the descriptions tight since they become always-on. See [DECISIONS.md](../DECISIONS.md) decision D1.
