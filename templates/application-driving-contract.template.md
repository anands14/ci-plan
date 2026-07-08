# Application Driving Contract

This file describes what this application exposes so the CI orchestrator and agents can drive it efficiently.
Keep it factual, compact, and current.
Agents should be able to use this file to find the right screen, hook, fixture, command, or log without scanning the whole application.

## Ownership

- Application:
- Primary repo:
- Default branch:
- Project constitution:
- Main app package or entry point:
- Primary UI framework:
- Primary backend or storage adapter:

## Required Commands

List commands from the target repo root.
Prefer commands that are deterministic and non-interactive.

| Purpose | Command | Notes |
| --- | --- | --- |
| Install dependencies |  |  |
| Format check |  |  |
| Static analysis or lint |  |  |
| Fast tests |  |  |
| Backend or storage E2E |  |  |
| UI smoke or simulator validation |  |  |
| Full nightly E2E |  |  |
| Run local app |  |  |

## Navigation Map

List the smallest stable route from app launch to each product area that agents may need to test.
Use stable selectors, keys, routes, accessibility labels, or URLs.
Do not rely on visible text when the text is product copy that may change.

| Area | Launch path | Stable hook | Expected ready state |
| --- | --- | --- | --- |
|  |  |  |  |

## Stable Automation Hooks

Every user-facing workflow that agents are expected to modify should expose stable hooks.
Hooks should be meaningful in product terms, not tied to layout or styling.

- Navigation controls:
- Create actions:
- Save or commit actions:
- Destructive actions:
- Empty states:
- Loading states:
- Error states:
- Repeated item identity:
- Modal or drawer identity:
- Canvas, editor, or board surfaces:

## Test Data And Reset

Agents need a cheap way to start from a known state.
Prefer local fixtures and temp directories over shared remote accounts.

| Need | Mechanism | Command or path |
| --- | --- | --- |
| Clean local state |  |  |
| Seed minimal data |  |  |
| Seed realistic data |  |  |
| Inspect persisted state |  |  |
| Reset simulator or browser state |  |  |

## Persistence Contract

Document where durable state lives and how tests can assert it without guessing through the UI.
Include real adapter paths, index files, database tables, or API endpoints that define success.

- Primary persisted artifacts:
- Real adapter used by backend E2E:
- Safe temp location for tests:
- Files or tables that must never be hand-edited:
- Generated files and their source:

## Validation Matrix

Describe which validation level is required for each kind of change.
This prevents agents from over-testing docs-only changes and under-testing user-facing behavior.

| Change type | Required local validation | Required real-target validation | N/A rule |
| --- | --- | --- | --- |
| Pure docs or process |  |  |  |
| Core domain logic |  |  |  |
| Storage or adapter behavior |  |  |  |
| Generic UI behavior |  |  |  |
| Platform-specific UI behavior |  |  |  |
| Performance-sensitive behavior |  |  |  |

## Simulator And Device Targets

List the cheapest credible target first.
Escalate only when the behavior is platform-specific or the issue requires it.

- Default target:
- iOS trigger paths or criteria:
- Android trigger paths or criteria:
- Web trigger paths or criteria:
- Desktop trigger paths or criteria:
- Known simulator setup command:
- Known simulator failure artifacts:

## Logs And Failure Artifacts

Agents should know where to look before asking for help.
Keep log locations deterministic and redact secrets.

- App logs:
- Test logs:
- CI logs:
- Screenshots or videos:
- Crash reports:
- State dumps:

## Protected Paths

List paths that agents must not edit without a human-approved override.
Keep this aligned with `AGENTS.md`, `CODEOWNERS`, and CI checks.

- 

## Shared Helpers

List existing helper APIs, fixtures, harnesses, and test utilities that agents should reuse.
This section prevents repeated one-off harnesses.

| Purpose | Path or API | When to use |
| --- | --- | --- |
|  |  |  |

## Known Gotchas

Keep this short.
Each item should save a future agent from repeating a known mistake.

- 

## Ready Issue Requirements

An issue is ready for autonomous implementation only when it names the user-visible behavior, acceptance criteria, validation level, likely files, protected-path risk, and any external dependency.
If those facts are missing, remove `ready` or ask for clarification before claiming the work.
