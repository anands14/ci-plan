# Project Constitution - <PROJECT NAME>

This file lives in the target repository and defines the architecture and conventions specific to this project.
It is loaded by the pipeline alongside the agnostic process rules in the framework's `CONSTITUTION.md`.
On process, the framework constitution wins; on architecture and convention content, this file is authoritative.

This is a **protected path**: agents may propose changes but must never edit it themselves.

---

## Stack

- Language / framework:
- Target platforms:
- Package / build tool:

## Architecture invariants (MUST - deviation is escalate-and-wait)

State the load-bearing decisions that must not be violated without a human call. Examples to replace:

- State management:
- Layering and dependency direction (what may import what):
- Module boundaries / folder structure:
- Error-handling and logging policy:
- Data and persistence rules:

## Conventions (SHOULD - deviation allowed, but must be declared loudly in the PR)

- Naming:
- File and folder structure:
- Preferred patterns / idioms to match:
- Anything the codebase does deliberately that an agent might "fix" wrongly:

## Glossary (ubiquitous language)

Define the domain terms so agents and reviewers use precise, shared meaning instead of re-deriving it.

- Term:
- Term:

## Checks (the concrete commands)

These should match the target repo's `.no-mistakes.yaml`.

- build:
- test:
- lint:
- format:
- coverage floor:

## Protected paths (project-specific)

Files agents may propose changes to but never edit themselves, in addition to the framework defaults.

- This file
- CI workflow files
-

## Deviation policy

This project inherits the framework rule: deviation from a convention is allowed only if declared loudly in the PR with reasoning; deviation from an invariant is escalate-and-wait; silent deviation is never allowed.
