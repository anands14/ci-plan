---
name: pipeline-spec-author
description: Pipeline-only spec author loop.
disable-model-invocation: true
---

# Pipeline Spec Author

Goal: rough intent -> observable, disjoint, review-sized issues.

## Loop

For each task:

1. Frame.
   One objective, source intent, relevant backlog/stuck context.
   Done when it is one PR, not a bundle.
2. Criteria.
   Concrete assertions only.
   Tag each `unit`, `widget`, `integration`, or `e2e`.
   Done when every promised behavior is testable.
3. Scope.
   Add files-in-scope, out-of-scope, dependencies, risk flags.
   Prefer file-disjoint issues.
   Shared files need explicit unavoidable risk.
   Hot file wanted? split or sequence around map/module first.
   Done when implementer/reviewer/orchestrator can all decide allowed work.
4. Language.
   Use `domain-modeling` for glossary terms.
   Use `grilling` when ambiguity remains.
   Done when fuzzy verbs became observable behavior.
5. Size.
   Aim around 15 human-review minutes.
   Split sprawl or undeclared scope collision.
   Done when each output can become one small PR.

Queue about 9-10 drafts when asked for a run batch.

## JSON

```json
{
  "tasks": [{
    "title": "...",
    "criteria": [{ "text": "...", "test_level": "unit" }],
    "scope_files": [],
    "out_of_scope": [],
    "dependencies": [],
    "risk_flags": [],
    "size_estimate": "review minutes"
  }]
}
```

## Hard Rules

- draft only; separate gate marks `ready`
- spec WHAT/done, not HOW
- one task = one review-sized PR
- file-disjointness is quality bar
