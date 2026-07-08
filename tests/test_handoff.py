from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.handoff import build_pr_body, parse_pr_number, parse_pr_url, run_pr_handoff
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry


class FakeGitHub:
    def __init__(self):
        self.updated_body = None
        self.base_updates = []

    def issue(self, repo, number):
        return {
            "number": number,
            "title": "Add labels",
            "body": "\n".join(
                [
                    "## Acceptance criteria",
                    "",
                    "- [ ] (unit) ok",
                    "",
                    "## Files in scope",
                    "",
                    "- `packages/tovi_core/lib/src/tasks/task.dart`",
                    "",
                    "## Risk flags",
                    "",
                    "- None",
                ]
            ),
        }

    def pr_head(self, repo, number):
        return "a" * 40

    def pr_body(self, repo, number):
        return "## Pipeline\n\nexisting no-mistakes details"

    def update_pr_body(self, repo, number, body):
        self.updated_body = body

    def update_pr_base(self, repo, number, base):
        self.base_updates.append((repo, number, base))


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


def integration_config_for(root: Path) -> ProjectConfig:
    config = config_for(root)
    return ProjectConfig(
        name=config.name,
        repo=config.repo,
        default_branch=config.default_branch,
        local_path=config.local_path,
        agent_remote=config.agent_remote,
        worker_home=config.worker_home,
        raw={"integration": {"daily_branch_prefix": "day"}},
        path=config.path,
        root=config.root,
    )


def entry_for(root: Path) -> RunLedgerEntry:
    return RunLedgerEntry(
        project="sample",
        repo="owner/sample",
        issue_number=7,
        issue_title="Add labels",
        lease_path=str(root / "lease"),
        current_step="gate-passed",
        log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        claimed_at="2026-07-02T00:00:00+00:00",
        gate_status="passed",
    )


class HandoffTests(unittest.TestCase):
    def test_parses_pr_url_and_number(self):
        url = parse_pr_url('pr: "https://github.com/owner/sample/pull/42"')

        self.assertEqual(url, "https://github.com/owner/sample/pull/42")
        self.assertEqual(parse_pr_number(url), 42)

    def test_handoff_pushes_agent_remote_and_records_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            calls = []

            def fake_runner(command, **kwargs):
                calls.append(command)
                if command[:4] == ["git", "push", "--dry-run", "origin"]:
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        stdout="",
                        stderr="fatal: could not read Username for 'https://github.com': terminal prompts disabled",
                    )
                if command[:3] == ["git", "push", "agent"]:
                    return subprocess.CompletedProcess(command, 0, stdout="pushed\n", stderr="")
                if command[:3] == ["no-mistakes", "axi", "run"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout='pr: "https://github.com/owner/sample/pull/42"\noutcome: checks-passed\n',
                        stderr="",
                    )
                raise AssertionError(command)

            fake_github = FakeGitHub()
            result = run_pr_handoff(
                config,
                entry,
                runner=fake_runner,
                github_client=fake_github,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.pr_number, 42)
            self.assertEqual(updated.pr_number, 42)
            self.assertEqual(updated.final_head_sha, "a" * 40)
            self.assertIn("## Criteria coverage", fake_github.updated_body)
            self.assertIn("- [x] (unit) ok -> task-scoped tests", fake_github.updated_body)
            self.assertIn("- [x] E2E written/updated", fake_github.updated_body)
            self.assertIn("existing no-mistakes details", fake_github.updated_body)
            self.assertIn(["git", "push", "agent", "HEAD:refs/heads/feat/issue-7-add-labels"], calls)

    def test_handoff_retargets_pr_to_daily_branch_when_integration_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = integration_config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, **kwargs):
                if command[:4] == ["git", "push", "--dry-run", "origin"]:
                    return subprocess.CompletedProcess(
                        command,
                        1,
                        stdout="",
                        stderr="fatal: could not read Username for 'https://github.com': terminal prompts disabled",
                    )
                if command[:3] == ["git", "push", "agent"]:
                    return subprocess.CompletedProcess(command, 0, stdout="pushed\n", stderr="")
                if command[:3] == ["no-mistakes", "axi", "run"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout='pr: "https://github.com/owner/sample/pull/42"\noutcome: checks-passed\n',
                        stderr="",
                    )
                raise AssertionError(command)

            fake_github = FakeGitHub()
            run_pr_handoff(config, entry, runner=fake_runner, github_client=fake_github)

            self.assertEqual(len(fake_github.base_updates), 1)
            self.assertEqual(fake_github.base_updates[0][0:2], ("owner/sample", 42))
            self.assertTrue(fake_github.base_updates[0][2].startswith("day/"))

    def test_handoff_refuses_when_worker_can_push_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)

            def fake_runner(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, stdout="would push\n", stderr="")

            with self.assertRaisesRegex(RuntimeError, "worker can push origin"):
                run_pr_handoff(config, entry, runner=fake_runner, github_client=FakeGitHub())

    def test_handoff_refuses_before_deterministic_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            entry = RunLedgerEntry(
                **{
                    **entry.__dict__,
                    "current_step": "implementer-ran",
                    "gate_status": None,
                }
            )

            def fake_runner(command, **kwargs):
                raise AssertionError("handoff should stop before shell commands")

            with self.assertRaisesRegex(RuntimeError, "deterministic gate passes"):
                run_pr_handoff(config, entry, runner=fake_runner, github_client=FakeGitHub())

    def test_build_pr_body_preserves_pipeline_and_marks_core_e2e_na(self):
        issue = FakeGitHub().issue("owner/sample", 7)
        entry = entry_for(Path("/tmp"))

        body = build_pr_body(issue, entry, "## Pipeline\n\npipeline details")

        self.assertIn("Closes #7", body)
        self.assertIn("pure tovi_core change; no app UI behavior changed", body)
        self.assertIn("## Pipeline\n\npipeline details", body)


if __name__ == "__main__":
    unittest.main()
