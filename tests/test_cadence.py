from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from orchestrator.cadence import nightly_targets, run_nightly_e2e, weekly_metrics
from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, write_run_entry


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={
            "gate": {"commands": {"build": "fvm flutter build apk --debug"}},
            "tests": {
                "nightly_e2e": {
                    "linux": ["build-apk", "android"],
                    "mac": ["ios", "macos"],
                },
                "flake_firewall": {"retries": 2},
            },
        },
        path=root / "projects" / "sample.yaml",
        root=root,
    )


class CadenceTests(unittest.TestCase):
    def test_nightly_targets_include_configured_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            targets = nightly_targets(config_for(Path(tmp)))

            self.assertEqual([target.name for target in targets], [
                "linux:build-apk",
                "linux:android",
                "mac:ios",
                "mac:macos",
            ])

    def test_nightly_flake_firewall_marks_retry_success_as_flaky(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "target").mkdir()
            config = config_for(root)
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                code = 1 if len(calls) == 1 else 0
                return subprocess.CompletedProcess(command, code, stdout="", stderr="")

            result = run_nightly_e2e(config, runner=fake_runner)

            self.assertEqual(result.results[0].status, "flaky")
            self.assertIsNotNone(result.record_path)

    def test_weekly_metrics_track_required_rates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            write_run_entry(
                config,
                RunLedgerEntry(
                    project="sample",
                    repo="owner/sample",
                    issue_number=1,
                    issue_title="Task",
                    lease_path=str(root / "lease"),
                    current_step="stuck",
                    log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-1.log"),
                    claimed_at="2026-07-02T00:00:00+00:00",
                    gate_status="failed",
                    last_summary="conformance failure",
                ),
            )
            nightly_dir = root / ".orchestrator" / "nightly"
            nightly_dir.mkdir(parents=True)
            (nightly_dir / "sample-20260702T000000Z.json").write_text(
                json.dumps({"results": [{"status": "flaky"}, {"status": "passed"}]}),
                encoding="utf-8",
            )
            metrics_dir = root / ".orchestrator" / "metrics"
            metrics_dir.mkdir(parents=True)
            (metrics_dir / "reviewer_false_approvals.json").write_text(
                json.dumps([{"pr": 1}]),
                encoding="utf-8",
            )

            metrics = weekly_metrics(config)

            self.assertEqual(metrics["bounce_back_rate"], "1/1")
            self.assertEqual(metrics["escalation_rate"], "1/1")
            self.assertEqual(metrics["flake_rate"], "1/2")
            self.assertEqual(metrics["conformance_fail_rate"], "1/1")
            self.assertEqual(metrics["reviewer_false_approvals"], "1")


if __name__ == "__main__":
    unittest.main()
