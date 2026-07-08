from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.freshness import run_base_refresh
from orchestrator.gate import GateRunResult
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry


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
    }
    values.update(changes)
    return RunLedgerEntry(**values)


class FreshnessTests(unittest.TestCase):
    def test_reports_current_when_merge_base_matches_origin_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, **kwargs):
                if command[:3] == ["git", "fetch", "origin"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, stdout="head\n", stderr="")
                if command == ["git", "rev-parse", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="base\n", stderr="")
                if command == ["git", "merge-base", "HEAD", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="base\n", stderr="")
                raise AssertionError(command)

            result = run_base_refresh(config, entry, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "current")
            self.assertEqual(updated.base_status, "current")

    def test_clean_refresh_reruns_gate_and_carries_review_when_diff_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root, review_status="approve")
            write_run_entry(config, entry)

            def fake_runner(command, **kwargs):
                if command[:3] == ["git", "fetch", "origin"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, stdout="old\n", stderr="")
                if command == ["git", "rev-parse", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="base\n", stderr="")
                if command == ["git", "merge-base", "HEAD", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="older-base\n", stderr="")
                if command[:3] == ["git", "diff", "--find-renames"]:
                    return subprocess.CompletedProcess(command, 0, stdout=" lib/a.dart | 1 +\n", stderr="")
                if command == ["git", "rebase", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="rebased\n", stderr="")
                raise AssertionError(command)

            def fake_gate(config, entry):
                return GateRunResult(True, "gate passed", [])

            result = run_base_refresh(
                config,
                entry,
                runner=fake_runner,
                gate_func=fake_gate,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "refreshed")
            self.assertEqual(result.review_action, "carry-forward-review")
            self.assertEqual(updated.base_status, "refreshed")
            self.assertEqual(updated.final_head_sha, "old")

    def test_conflict_routes_to_codex_without_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, **kwargs):
                if command[:3] == ["git", "fetch", "origin"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if command == ["git", "rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(command, 0, stdout="old\n", stderr="")
                if command == ["git", "rev-parse", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="base\n", stderr="")
                if command == ["git", "merge-base", "HEAD", "origin/main"]:
                    return subprocess.CompletedProcess(command, 0, stdout="older-base\n", stderr="")
                if command[:3] == ["git", "diff", "--find-renames"]:
                    return subprocess.CompletedProcess(command, 0, stdout="diff\n", stderr="")
                if command == ["git", "rebase", "origin/main"]:
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="conflict\n")
                if command == ["git", "rebase", "--abort"]:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError(command)

            result = run_base_refresh(config, entry, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.review_action, "wake-codex")
            self.assertEqual(updated.current_step, "base-refresh-conflict")


if __name__ == "__main__":
    unittest.main()
