<!--
One issue = one task = one review-sized PR.
`ready` only after human/reviewed spec pass.

This mirrors the global `to-tickets` skill's own issue template (`What to
build`, `Acceptance criteria`, `Blocked by`) plus the sections this pipeline
additionally needs for the ready-contract and safe parallelism (`Files in
scope`, `Out of scope`, `Risk flags`, `Size estimate`, and a test-level tag
per criterion). Add those as a convention during `to-tickets`'s "quiz the
user" step - `to-tickets` itself doesn't produce them. `Goal` and
`Dependencies / blockers` are accepted as aliases of `What to build` and
`Blocked by` for issues authored before this convention.
-->
---
name: Pipeline task
about: A spec'd, review-sized task for the agent pipeline
labels: []
---

## What to build

<One sentence: what this task delivers and why, from the user's perspective.>

## Acceptance criteria

<!-- observable assertions; tag unit | widget | integration | e2e -->

- [ ] (unit) `...` returns `...` for input `...`
- [ ] (widget) tapping X with empty Y shows error Z
- [ ] (integration) ...

## Files in scope

<!-- allowed files/modules only; prefer disjoint; overlap needs shared-file risk -->

- `path/to/file`
- `path/to/module/`

## Out of scope

<!-- explicit non-goals -->

-

## Blocked by

<!-- issue numbers first (#N - auto-checked and auto-promoted when they close); other inputs second; use "None - can start immediately" when unblocked -->

- None - can start immediately

## Risk flags

<!-- protected/invariant/platform/shared-file risk, or None -->

- None

## Size estimate

<!-- target ~15 review minutes -->

- Review minutes: ~
- Priority: p2
