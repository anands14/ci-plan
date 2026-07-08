from pathlib import Path
import json
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, write_run_entry
from orchestrator.reconcile import reconcile, record_wakeup


class FakeGitHub:
    def __init__(self, labels=None, checks=None):
        self.labels = labels or []
        self.checks = checks or {}

    def issue_labels(self, repo, number):
        return self.labels

    def pr_checks(self, repo, pr):
        return self.checks, all(value == "pass" for value in self.checks.values())


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={"triggers": {"poll_interval_seconds": 123}},
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
        "current_step": "pr-ready",
        "log_path": str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        "claimed_at": "2026-07-02T00:00:00+00:00",
        "pr_number": 42,
    }
    values.update(changes)
    return RunLedgerEntry(**values)


class ReconcileTests(unittest.TestCase):
    def test_record_wakeup_writes_daemon_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)

            path = record_wakeup(config, event="labeled", issue_number=7)

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["project"], "sample")
            self.assertEqual(data["event"], "labeled")
            self.assertEqual(data["issue_number"], 7)

    def test_reconcile_reports_poll_interval_and_next_sim_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            write_run_entry(config, entry_for(root))
            fake_github = FakeGitHub(
                labels=["in-progress"],
                checks={"gate": "pass", "test-discipline": "pass"},
            )

            report = reconcile(config, github_client=fake_github)

            self.assertEqual(report.polling_seconds, 123)
            self.assertEqual(report.items[0].actions, ["run-sim-validation"])

    def test_reconcile_reports_missing_lease_and_dead_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            write_run_entry(
                config,
                entry_for(root, current_step="in-progress", worker_pid=999999999),
            )

            report = reconcile(config, github_client=FakeGitHub(labels=["in-progress"]))

            self.assertIn("recover-or-release-missing-lease", report.items[0].actions)
            self.assertIn("recover-dead-worker", report.items[0].actions)

    def test_reconcile_reports_daily_integration_when_all_contexts_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            write_run_entry(config, entry_for(root, current_step="review-passed"))
            fake_github = FakeGitHub(
                labels=["approved"],
                checks={
                    "gate": "pass",
                    "test-discipline": "pass",
                    "sim-validation": "pass",
                    "review": "pass",
                },
            )

            report = reconcile(config, github_client=fake_github)

            self.assertEqual(report.items[0].actions, ["integrate-to-daily-branch"])


if __name__ == "__main__":
    unittest.main()
