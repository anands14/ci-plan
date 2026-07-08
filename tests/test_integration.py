from datetime import date
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import ANY

from orchestrator.config import ProjectConfig
from orchestrator.integration import (
    build_daily_pr_body,
    daily_branch_name,
    integrate_pr,
    open_daily_pr,
)
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry


class FakeGitHub:
    def __init__(self, *, branch_checks=None):
        self.pr_labels = []
        self.issue_states = []
        self.comments = []
        self.branch_checks_value = branch_checks or {"gate": "pass", "test-discipline": "pass"}
        self.created_prs = []
        self.updated_bodies = []

    def pr_details(self, repo, pr):
        return {
            "number": pr,
            "title": "Task",
            "baseRefName": "day/2026-07-06",
            "headRefName": "feat/task",
            "headRefOid": "a" * 40,
            "isDraft": False,
            "labels": [{"name": "approved"}, {"name": "clean"}],
        }

    def pr_head(self, repo, pr):
        return "a" * 40

    def pr_checks(self, repo, pr):
        checks = {
            "gate": "pass",
            "test-discipline": "pass",
            "sim-validation": "pass",
            "review": "pass",
        }
        return checks, True

    def branch_checks(self, repo, branch):
        return self.branch_checks_value, all(value == "pass" for value in self.branch_checks_value.values())

    def branch_head(self, repo, branch):
        return "b" * 40

    def set_pr_labels(self, repo, pr, add, remove=None):
        self.pr_labels.append((repo, pr, add, remove or []))

    def set_state(self, repo, number, add, remove=None):
        self.issue_states.append((repo, number, add, remove or []))

    def comment_pr(self, repo, pr, body):
        self.comments.append(("pr", pr, body))

    def comment_issue(self, repo, issue, body):
        self.comments.append(("issue", issue, body))

    def find_pr(self, repo, *, base, head):
        return None

    def create_pr(self, repo, *, base, head, title, body_path):
        self.created_prs.append((repo, base, head, title, body_path))
        return {"number": 99, "url": "https://github.com/owner/sample/pull/99"}

    def update_pr_body(self, repo, pr, body):
        self.updated_bodies.append((repo, pr, body))


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={"integration": {"post_merge_poll_attempts": 0}},
        path=root / "projects" / "sample.yaml",
        root=root,
    )


def entry_for(root: Path, **changes) -> RunLedgerEntry:
    values = {
        "project": "sample",
        "repo": "owner/sample",
        "issue_number": 7,
        "issue_title": "Task",
        "lease_path": str(root / "lease"),
        "current_step": "review-passed",
        "log_path": str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        "claimed_at": "2026-07-02T00:00:00+00:00",
        "pr_number": 42,
        "review_routing": "clean",
        "review_summary": "review approve/clean",
    }
    values.update(changes)
    return RunLedgerEntry(**values)


class IntegrationTests(unittest.TestCase):
    def test_daily_branch_name_uses_configured_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)

            self.assertEqual(daily_branch_name(config, date(2026, 7, 6)), "day/2026-07-06")

    def test_integrate_pr_merges_and_records_integrated_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                if command[:3] == ["gh", "pr", "merge"]:
                    return subprocess.CompletedProcess(command, 0, stdout="merged", stderr="")
                raise AssertionError(command)

            fake_github = FakeGitHub()
            result = integrate_pr(
                config,
                entry,
                branch="day/2026-07-06",
                runner=fake_runner,
                github_client=fake_github,
                sleeper=lambda _seconds: None,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "passed")
            self.assertEqual(updated.current_step, "integrated")
            self.assertEqual(updated.integration_status, "passed")
            self.assertIn(["gh", "pr", "merge", "42", "-R", "owner/sample", "--squash"], calls)
            self.assertIn(("owner/sample", 7, "integrated", ANY), fake_github.issue_states)

    def test_integrate_pr_reverts_and_notifies_when_branch_checks_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                if command[:3] == ["gh", "pr", "merge"]:
                    return subprocess.CompletedProcess(command, 0, stdout="merged", stderr="")
                if command[:4] == ["git", "-C", str(config.local_path), "fetch"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command[:5] == ["git", "-C", str(config.local_path), "worktree", "add"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command[:3] == ["git", "revert", "--no-edit"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command[:3] == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, stdout="c" * 40 + "\n", stderr="")
                if command[:3] == ["git", "push", "origin"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command[:5] == ["git", "-C", str(config.local_path), "worktree", "remove"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError(command)

            fake_github = FakeGitHub(branch_checks={"gate": "fail", "test-discipline": "pass"})
            result = integrate_pr(
                config,
                entry,
                branch="day/2026-07-06",
                runner=fake_runner,
                github_client=fake_github,
                sleeper=lambda _seconds: None,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "reverted")
            self.assertTrue(result.reverted)
            self.assertEqual(updated.current_step, "integration-failed")
            self.assertEqual(updated.integration_status, "reverted")
            self.assertTrue(any(comment[0] == "pr" for comment in fake_github.comments))

    def test_open_daily_pr_builds_body_and_posts_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = entry_for(
                root,
                current_step="integrated",
                integration_branch="day/2026-07-06",
                integration_status="passed",
                integration_summary="integrated",
            )
            write_run_entry(config, entry)
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                return subprocess.CompletedProcess(command, 0, stdout="posted", stderr="")

            fake_github = FakeGitHub()
            result = open_daily_pr(
                config,
                branch="day/2026-07-06",
                post=True,
                runner=fake_runner,
                github_client=fake_github,
            )

            body = result.body_path.read_text(encoding="utf-8")
            self.assertEqual(result.status, "created")
            self.assertIn("Daily integration branch `day/2026-07-06` into `main`.", body)
            self.assertIn("Closes #7", body)
            self.assertIn("--context", calls[0])
            self.assertIn("daily-integration", calls[0])

    def test_build_daily_pr_body_surfaces_flagged_entries(self):
        entry = entry_for(
            Path("/tmp"),
            current_step="integrated",
            integration_branch="day/2026-07-06",
            integration_status="passed",
            review_routing="flagged",
            review_summary="needs real attention",
        )
        body = build_daily_pr_body(config_for(Path("/tmp")), "day/2026-07-06", [entry])

        self.assertIn("## Needs Human Attention", body)
        self.assertIn("needs real attention", body)


if __name__ == "__main__":
    unittest.main()
