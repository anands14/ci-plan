from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry
from orchestrator.validation import (
    parse_review_result,
    parse_sha,
    parse_sim_validation_status,
    run_review,
    run_sim_validation,
)


class FakeGitHub:
    def __init__(self, checks=None, heads=None):
        self.checks = checks or {"gate": "pass", "test-discipline": "pass"}
        self.heads = heads or ["b" * 40, "b" * 40]
        self.labels = []
        self.states = []

    def pr_checks(self, repo, pr):
        return self.checks, all(value == "pass" for value in self.checks.values())

    def pr_head(self, repo, pr):
        if len(self.heads) > 1:
            return self.heads.pop(0)
        return self.heads[0]

    def set_pr_labels(self, repo, pr, add, remove=None):
        self.labels.append((repo, pr, add, remove or []))

    def set_state(self, repo, number, add, remove=None):
        self.states.append((repo, number, add, remove or []))


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


def entry_for(root: Path) -> RunLedgerEntry:
    return RunLedgerEntry(
        project="sample",
        repo="owner/sample",
        issue_number=7,
        issue_title="Task",
        lease_path=str(root / "lease"),
        current_step="pr-ready",
        log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        claimed_at="2026-07-02T00:00:00+00:00",
        pr_number=42,
    )


class ValidationTests(unittest.TestCase):
    def test_parses_lane_output(self):
        self.assertEqual(parse_sim_validation_status("sim-validation: success"), "success")
        self.assertEqual(parse_sha("(sha: " + "a" * 40 + ")"), "a" * 40)
        self.assertEqual(
            parse_review_result("review verdict: approve/clean -> success"),
            ("approve", "clean", "success"),
        )

    def test_sim_validation_records_status_and_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="sim-validation platform(s): N/A  (sha: " + "c" * 40 + ")\nsim-validation: success\n",
                    stderr="",
                )

            result = run_sim_validation(config, entry, post=True, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "success")
            self.assertEqual(updated.sim_validation_status, "success")
            self.assertEqual(updated.final_head_sha, "c" * 40)

    def test_review_requires_green_deterministic_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(root)
            fake_github = FakeGitHub(checks={"gate": "fail", "test-discipline": "pass"})

            with self.assertRaisesRegex(RuntimeError, "green deterministic gates"):
                run_review(config, entry, github_client=fake_github)

    def test_review_records_clean_routing_and_approved_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            fake_github = FakeGitHub()

            def fake_runner(command, **kwargs):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="review verdict: approve/clean -> success  (model claude-opus-4-8, sha "
                    + "b" * 40
                    + ")\n",
                    stderr="",
                )

            result = run_review(
                config,
                entry,
                post=True,
                model="claude-opus-4-8",
                runner=fake_runner,
                github_client=fake_github,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "approve")
            self.assertEqual(result.routing, "clean")
            self.assertEqual(updated.review_status, "approve")
            self.assertEqual(updated.review_routing, "clean")
            self.assertEqual(fake_github.labels, [("owner/sample", 42, "clean", ["clean", "flagged"])])
            self.assertEqual(fake_github.states, [("owner/sample", 7, "approved", ["in-progress", "in-review"])])


if __name__ == "__main__":
    unittest.main()
