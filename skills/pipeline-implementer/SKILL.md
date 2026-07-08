---
name: pipeline-implementer
description: Pipeline-only implementer loop.
disable-model-invocation: true
---

# Pipeline Implementer

Stable context comes from the orchestrator brief.
This file only defines the loop.

## Loop

1. Account.
   Read issue criteria, test tags, scope, risk.
   Done when every criterion has a planned test or escalation.
2. Red.
   Use `tdd` for criteria-derived failing tests.
   Done when failures are intentional or untestable criteria are escalated.
3. Fix.
   Edit only scope files.
   Use `codebase-design` when boundary/interface choice matters.
   Done when touched files are in scope or escalated.
4. Prove.
   Run scoped tests while iterating.
   User-facing behavior needs declared e2e/real-target run or e2e-exempt reason.
   Done when commands and coverage are in JSON.
5. Return.
   No PR work unless the current orchestrator command asks for it.
   Done when JSON is valid.

## Hard Rules

- tests from criteria; never weaken/skip/delete/ignore tests
- scope manifest is hard
- protected paths need issue risk + human approval
- invariant conflict, unclear spec, no material diff, or missing input => escalate

## JSON

```json
{
  "success": true,
  "summary": "...",
  "key_changes": [],
  "tests_added": [],
  "tests_run": [],
  "touched_files": [],
  "new_apis": [],
  "decisions": [],
  "gotchas": [],
  "deviations": [],
  "uncertainties": [],
  "escalation": null
}
```
