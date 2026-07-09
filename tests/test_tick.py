from pathlib import Path
import tempfile
import threading
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.tick import run_tick


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={},
        path=root / "projects" / "sample.yaml",
        root=root,
    )


VALID_BODY = """
## Goal

Deliver a small thing.

## Acceptance criteria

- [ ] (unit) `A` returns `B`

## Files in scope

- `lib/{name}.dart`

## Out of scope

- UI work

## Dependencies / blockers

- None

## Risk flags

- None

## Size estimate

- Review minutes: ~15
- Priority: p2
"""


def body_for(name: str) -> str:
    return VALID_BODY.format(name=name)


class FakeGitHub:
    def __init__(self, issues):
        self.issues = issues
        self.states = []

    def ready_issues(self, repo):
        return self.issues

    def issues_with_label(self, repo, label):
        if label == "ready":
            return self.issues
        return []

    def issue_closed(self, repo, number):
        return True

    def set_state(self, repo, number, add, remove=None):
        self.states.append((repo, number, add, remove or []))

    def approved_prs(self, repo, branch):
        return []


class RunTickTests(unittest.TestCase):
    def test_claims_and_dispatches_every_disjoint_issue_in_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [
                    {"number": 1, "title": "one", "body": body_for("a")},
                    {"number": 2, "title": "two", "body": body_for("b")},
                ]
            )
            seen_numbers = []
            barrier = threading.Barrier(2, timeout=5)

            def fake_pipeline(config, issue_number, *, github_client=None):
                seen_numbers.append(issue_number)
                barrier.wait()  # only passes if both ran concurrently
                return _result(issue_number)

            def fake_lease(config, number):
                path = root / f"lease-{number}"
                path.mkdir(parents=True, exist_ok=True)
                return path

            result = run_tick(
                config,
                github_client=github_client,
                pipeline_runner=fake_pipeline,
                lease_func=fake_lease,
                release_func=lambda path: None,
            )

            self.assertEqual(sorted(result.claimed), [1, 2])
            self.assertEqual({r.issue_number for r in result.pipeline_results}, {1, 2})
            self.assertEqual(result.integrated, [])

    def test_dry_run_claims_nothing_and_skips_pipeline_and_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub([{"number": 1, "title": "one", "body": body_for("a")}])
            calls = []

            def fake_pipeline(config, issue_number, *, github_client=None):
                calls.append(issue_number)
                return _result(issue_number)

            result = run_tick(
                config,
                dry_run=True,
                github_client=github_client,
                pipeline_runner=fake_pipeline,
            )

            self.assertEqual(result.claimed, [1])
            self.assertEqual(calls, [])
            self.assertEqual(result.pipeline_results, [])
            self.assertEqual(result.integrated, [])

    def test_pipeline_exception_is_reported_per_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [
                    {"number": 1, "title": "one", "body": body_for("a")},
                    {"number": 2, "title": "two", "body": body_for("b")},
                ]
            )

            def fake_pipeline(config, issue_number, *, github_client=None):
                if issue_number == 1:
                    raise RuntimeError("agent crashed")
                return _result(issue_number)

            def fake_lease(config, number):
                path = root / f"lease-{number}"
                path.mkdir(parents=True, exist_ok=True)
                return path

            result = run_tick(
                config,
                github_client=github_client,
                pipeline_runner=fake_pipeline,
                lease_func=fake_lease,
                release_func=lambda path: None,
            )

            summaries = {item.issue_number: item.summary for item in result.pipeline_results}
            self.assertIn("agent crashed", summaries[1])
            self.assertEqual(summaries[2], "ok")


def _result(issue_number):
    from orchestrator.tick import IssuePipelineResult

    return IssuePipelineResult(issue_number, "review", "ok")


if __name__ == "__main__":
    unittest.main()
