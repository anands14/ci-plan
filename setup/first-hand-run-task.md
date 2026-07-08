## Goal

Allow the pure-Dart task command core to create tasks with optional tags and persist those tags through the real file-backed vault adapter.

## Acceptance criteria

- [ ] (unit) `TaskCommands.createTask('Buy milk', tags: ['home', 'errand'])` returns `Ok<Task>` with `title == 'Buy milk'`, `status == TaskStatus.todo`, and `tags == ['home', 'errand']`.
- [ ] (unit) `TaskCommands.createTask('Buy milk', tags: [' home ', '', 'errand '])` trims surrounding whitespace from tags, drops blank tags, and preserves the remaining tag order as `['home', 'errand']`.
- [ ] (unit) `TaskCommands.createTask('Buy milk')` keeps the current default behavior and returns a task with an empty `tags` list.
- [ ] (backend-e2e) Creating a tagged task through `TaskCommands` backed by `FileTaskStore` writes the tags into the real vault Markdown frontmatter and a fresh `FileTaskStore` instance loads the same tags.

## Files in scope

- `packages/tovi_core/lib/src/tasks/task_commands.dart`
- `packages/tovi_core/test/tasks/task_commands_test.dart`
- `packages/tovi_core/test/tasks/task_lifecycle_backend_e2e_test.dart`

## Out of scope

- UI changes in `packages/tovi_app/**`.
- Agent daemon changes in `packages/tovi_agent/**`.
- SQLite index work.
- Changes to protected paths, CI, no-mistakes config, or project constitution.

## Size estimate

- Review minutes: ~15
- Priority: p2

## Protected path risk

None expected.

## Notes for the hand-run

This is the first Phase 0b proof task.
It is intentionally pure core work so the first hand-run proves the acceptance-criteria-as-tests loop, backend E2E gate, PR handoff, and cross-model review without simulator or UI noise.
