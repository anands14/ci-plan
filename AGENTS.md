# Standing instructions for any agent working in this repo

This is the **framework** repo for a supervised-autonomy development pipeline (see [README.md](README.md) and [PLAN.md](PLAN.md)). It is not a place to freelance implementation work on a target project.

## If asked to implement GitHub issues for a registered project

**Do not implement them yourself.** Invoke the orchestrator instead:

```sh
bin/orchestrator preflight --project <name>
bin/orchestrator run --project <name>          # one tick: frontier -> claim-all -> pipeline -> integrate
bin/orchestrator run --project <name> --poll    # loop until nothing is left to do
```

`bin/orchestrator run` claims every currently-safe `ready` issue on its own — computed from the dependency frontier (`Blocked by #N` edges) and file-scope collisions already declared on the issues, not from a wave-plan you write by hand — then drives each through implement → gate → handoff → sim-validate → review → integrate.

If someone asks you (an interactive session) to "implement issues 55 to 60" or similar, the correct response is to run the commands above against the registered project, not to open the target repo and start writing code directly. That bypasses the gate this framework exists to provide: a cheap deterministic check before a cross-model review before anything merges.

For a single hand-run step instead of the full loop (debugging, or before the orchestrator existed), see [setup/hand-run.md](setup/hand-run.md).

## If asked to author specs or break down a plan into issues

That's not an automated pipeline role either — do it interactively, in this session, using the `grilling` and `to-tickets` skills. Publish real `Blocked by #N` edges and file-scope manifests; that's what lets `bin/orchestrator run` compute safe parallelism on its own afterward.

## Everything else

Normal software-engineering conventions apply: read before editing, run the test suite (`python3 -m unittest discover -s tests`) after changes to `orchestrator/`, and see [CONSTITUTION.md](CONSTITUTION.md) for the process rules this framework enforces on every managed project.
