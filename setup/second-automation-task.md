## Goal

Add stable human-facing labels for `TaskStatus` values in the pure-Dart core so UI and agent surfaces can display the same status text without duplicating string mappings.

## Acceptance criteria

- [ ] (unit) `TaskStatus.todo.label` returns `To do`.
- [ ] (unit) `TaskStatus.doing.label` returns `Doing`.
- [ ] (unit) `TaskStatus.done.label` returns `Done`.
- [ ] (unit) `TaskStatus.fromWire('todo')`, `TaskStatus.fromWire('doing')`, and `TaskStatus.fromWire('done')` still parse the existing storage wire values.

## Files in scope

- `packages/tovi_core/lib/src/tasks/task.dart`
- `packages/tovi_core/test/tasks/task_test.dart`

## Out of scope

- UI changes in `packages/tovi_app/**`.
- Agent daemon changes in `packages/tovi_agent/**`.
- Storage format changes.
- Changes to task command behavior.
- Changes to protected paths, CI, no-mistakes config, or project constitution.

## Dependencies / blockers

- None

## Risk flags

- None

## Size estimate

- Review minutes: ~10
- Priority: p2
