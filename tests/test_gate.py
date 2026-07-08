from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.gate import gate_env, protected_path_changes, run_gate
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={
            "gate": {
                "ci_autofix": "off",
                "commands": {
                    "format": "format-cmd",
                    "lint": "lint-cmd",
                    "test": "test-cmd",
                },
            }
        },
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
        current_step="implementer-ran",
        log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        claimed_at="2026-07-02T00:00:00+00:00",
    )


class GateTests(unittest.TestCase):
    def test_gate_env_scrubs_secret_like_values(self):
        env = gate_env(
            {
                "PATH": "/bin",
                "HOME": "/home/me",
                "GH_TOKEN": "x",
                "GITHUB_TOKEN": "x",
                "SSH_AUTH_SOCK": "/tmp/ssh",
                "OTHER_SECRET": "x",
            }
        )

        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["HOME"], "/home/me")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertNotIn("OTHER_SECRET", env)

    def test_run_gate_stops_on_first_failure_and_updates_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            calls = []

            def fake_runner(command, cwd, capture_output, text, env):
                calls.append(command[-1])
                code = 1 if command[-1] == "lint-cmd" else 0
                return subprocess.CompletedProcess(command, code, stdout="out", stderr="")

            result = run_gate(config, entry, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertFalse(result.passed)
            self.assertEqual(calls, ["format-cmd", "lint-cmd"])
            self.assertEqual(updated.current_step, "gate-failed")
            self.assertEqual(updated.gate_status, "failed")

    def test_run_gate_passes_all_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, cwd, capture_output, text, env):
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

            result = run_gate(config, entry, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertTrue(result.passed)
            self.assertEqual(updated.current_step, "gate-passed")
            self.assertEqual(updated.gate_status, "passed")

    def test_yaml_boolean_false_counts_as_autofix_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            config.raw["gate"]["ci_autofix"] = False
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, cwd, capture_output, text, env):
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

            result = run_gate(config, entry, runner=fake_runner)

            self.assertTrue(result.passed)

    def test_gate_blocks_protected_path_changes_before_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lease = root / "lease"
            lease.mkdir()
            subprocess.run(["git", "init"], cwd=lease, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=lease, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=lease, check=True)
            (lease / "base.txt").write_text("base", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=lease, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=lease, check=True, capture_output=True)
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                cwd=lease,
                check=True,
                capture_output=True,
            )
            (lease / ".no-mistakes.yaml").write_text("commands: {}\n", encoding="utf-8")
            subprocess.run(["git", "add", ".no-mistakes.yaml"], cwd=lease, check=True)
            subprocess.run(
                ["git", "commit", "-m", "protected"],
                cwd=lease,
                check=True,
                capture_output=True,
            )
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, cwd, capture_output, text, env):
                raise AssertionError("gate command should not run after protected edit")

            result = run_gate(config, entry, runner=fake_runner)

            updated = read_run_entry(config, 7)
            self.assertFalse(result.passed)
            self.assertEqual(protected_path_changes(lease), [".no-mistakes.yaml"])
            self.assertEqual(updated.current_step, "stuck")
            self.assertIn("protected-path edit blocked", updated.last_summary)


if __name__ == "__main__":
    unittest.main()
