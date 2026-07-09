from pathlib import Path
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, write_run_entry
from orchestrator.reporting import evening_report, watch_report


class FakeGitHub:
    def __init__(self):
        self.labels = {
            1: ["approved", "clean"],
            2: ["approved", "flagged"],
            3: ["stuck"],
            4: ["deferred"],
        }

    def issue_labels(self, repo, number):
        return self.labels[number]

    def pr_checks(self, repo, pr):
        return {
            "gate": "pass",
            "test-discipline": "pass",
            "sim-validation": "pass",
            "review": "pass",
        }, True


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


def write_entry(root: Path, number: int, step: str, **changes) -> None:
    values = {
        "project": "sample",
        "repo": "owner/sample",
        "issue_number": number,
        "issue_title": "Task",
        "lease_path": str(root / f"lease-{number}"),
        "current_step": step,
        "log_path": str(root / ".orchestrator" / "logs" / "sample" / f"issue-{number}.log"),
        "claimed_at": "2026-07-02T00:00:00+00:00",
        "pr_number": number + 40,
        "last_summary": "short reason",
    }
    values.update(changes)
    write_run_entry(config_for(root), RunLedgerEntry(**values))


class ReportingTests(unittest.TestCase):
    def test_evening_report_emits_expected_buckets_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            write_entry(root, 1, "approved", review_routing="clean", review_summary="approved clean")
            write_entry(root, 2, "approved", review_routing="flagged", review_summary="approved flagged")
            write_entry(root, 3, "stuck", last_summary="blocked on external input")
            write_entry(root, 4, "deferred", last_summary="window share reached")

            report = evening_report(config, github_client=FakeGitHub())

            self.assertIn("## clean PRs", report)
            self.assertIn("issue #1; PR #41; checks=gate:pass", report)
            self.assertIn("routing=clean", report)
            self.assertIn("## flagged PRs", report)
            self.assertIn("routing=flagged", report)
            self.assertIn("## stuck tasks", report)
            self.assertIn("blocked on external input", report)
            self.assertIn("## deferred tasks", report)
            self.assertIn("window share reached", report)

    def test_watch_report_emits_local_run_table_without_github(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            config.raw["agents"] = {"implementer": {"model": "gpt-5.5"}}
            write_entry(root, 7, "implementer-failed", pr_number=None, last_summary="auth failed")
            write_entry(root, 8, "review-passed", review_summary="review approve/clean")

            report = watch_report(config)

            self.assertIn("Issue", report)
            self.assertIn("#7", report)
            self.assertIn("implementer-failed", report)
            self.assertIn("gpt-5.5", report)
            self.assertIn("auth failed", report)
            self.assertIn("#8", report)
            self.assertIn("reviewer", report)
            self.assertIn("review approve/clean", report)


if __name__ == "__main__":
    unittest.main()
