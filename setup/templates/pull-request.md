<!--
PR template.
Copy to a target repo at .github/pull_request_template.md.
Filled by the implementer.
Mirrors the pipeline-implementer output contract.
The reviewer reads this first, and the final daily PR summary pulls from it, so make it honest and scannable.
-->

## What changed

<One paragraph: what and why.>

Closes #<issue>

## Criteria coverage

<!-- One line per acceptance criterion, and the test that exercises it. -->

- [ ] criterion -> `test name`
- [ ] criterion -> `test name`

## Testing

<!-- The orchestrator posts real-target sim-validation as a status.
     Declare E2E coverage and backend/source-of-truth assertions here. -->

- [ ] E2E written/updated for the user-facing behavior - or N/A: <reason>
- Backend assertion: <which source-of-truth file / index state / command result this PR's tests assert, or N/A>

## Risk flags

<!-- Copy issue risk flags and add any discovered while implementing.
     If none, write "none". -->

- none

## Reviewer routing

<!-- Filled by reviewer or orchestrator after review. -->

- pending

## Deviations (loud, never silent)

<!-- Any convention you deviated from, with the reason.
     If none, write "none".
     Invariant deviations are not allowed here - those are escalate-and-wait. -->

- none

## Uncertainties

<!-- Anything you are unsure about.
     The final daily PR should surface these first.
     If none, write "none". -->

- none

## Self-check

- [ ] Tests derive from the acceptance criteria (not reverse-engineered from the code).
- [ ] No test was weakened, skipped, or deleted to make a check pass.
- [ ] No protected path edited.
- [ ] Scope manifest respected.
- [ ] Build, lint, and tests pass locally.
