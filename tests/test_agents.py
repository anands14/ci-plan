from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest

from orchestrator.agents import (
    build_implementer_command,
    build_implementer_prompt,
    build_feedback_context,
    extract_session_id,
    run_advisor_once,
    run_implementer_once,
)
from orchestrator.context import handoff_log_relative_path
from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry


class FakeGitHub:
    def __init__(self):
        self.states = []

    def issue(self, repo, number):
        return {
            "number": number,
            "title": "Implement one thing",
            "body": "## Goal\n\nDo it.\n\n## Acceptance criteria\n\n- [ ] (unit) ok",
        }

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


def seed_framework(root: Path) -> None:
    (root / "CONSTITUTION.md").write_text("# Constitution\n", encoding="utf-8")
    skill_dir = root / "skills" / "pipeline-implementer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "# Pipeline role: implementer\n",
        encoding="utf-8",
    )


def entry_for(root: Path) -> RunLedgerEntry:
    return RunLedgerEntry(
        project="sample",
        repo="owner/sample",
        issue_number=7,
        issue_title="Implement one thing",
        lease_path=str(root / "lease"),
        current_step="claimed",
        log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
        claimed_at="2026-07-02T00:00:00+00:00",
    )


class AgentTests(unittest.TestCase):
    def test_prompt_injects_compact_brief_handoff_and_task(self):
        root = Path.cwd()
        config = config_for(root)

        prompt = build_implementer_prompt(
            config,
            {"number": 7, "title": "Task", "body": "## Goal\n\nDo it."},
        )

        self.assertIn("# Implementer Brief", prompt)
        self.assertIn("## Hard Rules", prompt)
        self.assertIn("## Gate", prompt)
        self.assertIn("# Handoff", prompt)
        self.assertIn("Issue #7: Task", prompt)
        self.assertIn("M2 implementer step", prompt)
        self.assertIn("do not push/open/update PR", prompt)
        self.assertIn("checkpoint stable progress", prompt)
        self.assertIn("Do not read whole docs or hot files", prompt)
        self.assertNotIn("# Process Constitution", prompt)

    def test_prompt_renders_yaml_key_value_bullets_compactly(self):
        root = Path.cwd()
        config = config_for(root)
        config.raw["context"] = {
            "techniques": [{"ListView": "scrollUntilVisible may need cache-extent movement."}],
            "scoped_tests": [{"core": "fvm dart test test/tasks/foo_test.dart"}],
        }

        prompt = build_implementer_prompt(
            config,
            {"number": 7, "title": "Task", "body": "## Goal\n\nDo it."},
        )

        self.assertIn("ListView: scrollUntilVisible", prompt)
        self.assertIn("core: fvm dart test", prompt)
        self.assertNotIn("{'ListView'", prompt)

    def test_prompt_includes_review_feedback_when_provided(self):
        root = Path.cwd()
        config = config_for(root)

        prompt = build_implementer_prompt(
            config,
            {"number": 7, "title": "Task", "body": "## Goal\n\nDo it."},
            feedback="Reviewer requested a real assertion.",
        )

        self.assertIn("# Feedback To Address", prompt)
        self.assertIn("Reviewer requested a real assertion.", prompt)

    def test_feedback_context_reads_review_request_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            log_dir = root / ".orchestrator" / "logs" / "sample" / "issue-7"
            log_dir.mkdir(parents=True)
            (log_dir / "review.log").write_text(
                "review verdict: request-changes/flagged -> failure",
                encoding="utf-8",
            )
            entry = RunLedgerEntry(
                project="sample",
                repo="owner/sample",
                issue_number=7,
                issue_title="Task",
                lease_path=str(root / "lease"),
                current_step="review-requested-changes",
                log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
                claimed_at="2026-07-02T00:00:00+00:00",
                review_summary="review request-changes/flagged -> failure",
            )

            feedback = build_feedback_context(config, entry)

            self.assertIn("The gating reviewer requested changes.", feedback)
            self.assertIn("review request-changes/flagged", feedback)
            self.assertIn("review verdict: request-changes/flagged", feedback)

    def test_feedback_context_reads_base_refresh_conflict_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            log_dir = root / ".orchestrator" / "logs" / "sample" / "issue-7"
            log_dir.mkdir(parents=True)
            (log_dir / "base-refresh.log").write_text("CONFLICT in lib/a.dart", encoding="utf-8")
            entry = RunLedgerEntry(
                project="sample",
                repo="owner/sample",
                issue_number=7,
                issue_title="Task",
                lease_path=str(root / "lease"),
                current_step="base-refresh-conflict",
                log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
                claimed_at="2026-07-02T00:00:00+00:00",
                base_summary="base refresh needs Codex conflict resolution",
            )

            feedback = build_feedback_context(config, entry)

            self.assertIn("could not be refreshed", feedback)
            self.assertIn("base refresh needs Codex", feedback)
            self.assertIn("CONFLICT in lib/a.dart", feedback)

    def test_feedback_context_does_not_resume_stuck_or_deferred(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            for step in ("stuck", "deferred"):
                entry = RunLedgerEntry(
                    project="sample",
                    repo="owner/sample",
                    issue_number=7,
                    issue_title="Task",
                    lease_path=str(root / "lease"),
                    current_step=step,
                    log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
                    claimed_at="2026-07-02T00:00:00+00:00",
                )

                self.assertIsNone(build_feedback_context(config, entry))

    def test_extract_session_id_from_nested_jsonl(self):
        jsonl = '{"type":"event","payload":{"session_id":"abc-123"}}\n'

        self.assertEqual(extract_session_id(jsonl), "abc-123")

    def test_dry_run_does_not_write_prompt_or_update_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)

            result = run_implementer_once(
                config,
                entry,
                dry_run=True,
                github_client=FakeGitHub(),
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("codex", result.command)
            self.assertIn("--model", result.command)
            self.assertEqual(result.command[result.command.index("--model") + 1], "gpt-5.5")
            self.assertIn('model_reasoning_effort="high"', result.command)
            self.assertFalse(result.prompt_path.exists())

    def test_run_records_session_summary_and_updates_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            lease = root / "lease"
            lease.mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, input, capture_output, text, env):
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(
                    '{"success": true, "summary": "implemented the task"}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout='{"session_id":"session-7"}\n',
                    stderr="",
                )

            result = run_implementer_once(
                config,
                entry,
                github_client=FakeGitHub(),
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.codex_session_id, "session-7")
            self.assertEqual(updated.codex_session_id, "session-7")
            self.assertEqual(updated.current_step, "implementer-ran")
            self.assertEqual(updated.last_summary, "implemented the task")
            self.assertTrue(Path(updated.prompt_path).is_file())
            handoff = lease / handoff_log_relative_path(config)
            self.assertTrue(handoff.is_file())
            self.assertIn("issue #7", handoff.read_text(encoding="utf-8"))
            self.assertIn("implemented the task", handoff.read_text(encoding="utf-8"))

    def test_failed_codex_run_ignores_stale_result_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            stale_result = root / ".orchestrator" / "results" / "sample" / "issue-7-implementer.json"
            stale_result.parent.mkdir(parents=True, exist_ok=True)
            stale_result.write_text('{"summary": "old success"}', encoding="utf-8")

            def fake_runner(command, input, capture_output, text, env):
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout='{"type":"error","message":"fresh auth failure"}\n',
                    stderr="",
                )

            result = run_implementer_once(
                config,
                entry,
                github_client=FakeGitHub(),
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(updated.last_summary, "fresh auth failure")
            self.assertEqual(updated.current_step, "stuck")

    def test_ambiguous_failed_run_consults_advisor_once_then_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            (root / "lease").mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            calls = {"implementer": 0, "advisor": 0}

            def fake_runner(command, *args, **kwargs):
                if command[0].endswith("bin/advise"):
                    calls["advisor"] += 1
                    return subprocess.CompletedProcess(command, 0, stdout="Retry with narrower context.", stderr="")
                calls["implementer"] += 1
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                if calls["implementer"] == 1:
                    Path(command[result_index]).write_text(
                        '{"success": false, "summary": "tool exited without a clear reason"}',
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
                Path(command[result_index]).write_text(
                    '{"success": true, "summary": "recovered after advisor guidance"}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = run_implementer_once(
                config,
                entry,
                github_client=FakeGitHub(),
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(calls, {"implementer": 2, "advisor": 1})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(updated.current_step, "implementer-ran")
            self.assertEqual(updated.last_summary, "recovered after advisor guidance")

    def test_codex_runs_share_worker_home_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            (root / "lease-7").mkdir()
            (root / "lease-8").mkdir()
            config = config_for(root)
            entry_7 = entry_for(root)
            entry_8 = RunLedgerEntry(
                project="sample",
                repo="owner/sample",
                issue_number=8,
                issue_title="Implement another thing",
                lease_path=str(root / "lease-8"),
                current_step="claimed",
                log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-8.log"),
                claimed_at="2026-07-02T00:00:00+00:00",
            )
            entry_7 = RunLedgerEntry(**{**entry_7.__dict__, "lease_path": str(root / "lease-7")})
            write_run_entry(config, entry_7)
            write_run_entry(config, entry_8)
            active = 0
            max_active = 0
            observed_lock = threading.Lock()

            def fake_runner(command, input, capture_output, text, env):
                nonlocal active, max_active
                with observed_lock:
                    active += 1
                    max_active = max(max_active, active)
                time.sleep(0.05)
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(
                    '{"success": true, "summary": "done"}',
                    encoding="utf-8",
                )
                with observed_lock:
                    active -= 1
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            threads = [
                threading.Thread(
                    target=run_implementer_once,
                    args=(config, entry),
                    kwargs={"github_client": FakeGitHub(), "runner": fake_runner},
                )
                for entry in (entry_7, entry_8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(max_active, 1)

    def test_successful_run_with_uncommitted_work_creates_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            lease = root / "lease"
            lease.mkdir()
            subprocess.run(["git", "init"], cwd=lease, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=lease,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=lease,
                check=True,
                capture_output=True,
            )
            (lease / "base.txt").write_text("base", encoding="utf-8")
            subprocess.run(["git", "add", "base.txt"], cwd=lease, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=lease, check=True, capture_output=True)
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)

            def fake_runner(command, input, capture_output, text, env):
                (lease / "changed.txt").write_text("work", encoding="utf-8")
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(
                    '{"success": true, "summary": "changed files"}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout='{"session_id":"session-8"}\n',
                    stderr="",
                )

            result = run_implementer_once(
                config,
                entry,
                github_client=FakeGitHub(),
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(updated.current_step, "implementer-ran")
            self.assertIn("Checkpoint commit", updated.last_summary)
            self.assertNotEqual(updated.head_before, updated.head_after)

    def test_failed_run_consults_advisor_once_then_marks_true_stuck(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            lease = root / "lease"
            lease.mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            fake_github = FakeGitHub()
            advisor_calls = []

            def fake_runner(command, *args, **kwargs):
                if command[0].endswith("bin/advise"):
                    advisor_calls.append(command)
                    return subprocess.CompletedProcess(command, 0, stdout="Escalate to the human.", stderr="")
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(
                    '{"success": false, "summary": "Spec is unclear; requires human input."}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

            result = run_implementer_once(
                config,
                entry,
                github_client=fake_github,
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(len(advisor_calls), 1)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(updated.current_step, "stuck")
            self.assertEqual(updated.advisor_summary, "Escalate to the human.")
            self.assertEqual(fake_github.states, [("owner/sample", 7, "stuck", ["in-progress", "in-review"])])

    def test_failed_run_marks_deferred_for_window_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            lease = root / "lease"
            lease.mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            fake_github = FakeGitHub()

            def fake_runner(command, input, capture_output, text, env):
                result_index = command.index("--output-last-message") + 1
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(
                    '{"success": false, "summary": "Window share ceiling reached; resume when window returns."}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

            run_implementer_once(
                config,
                entry,
                github_client=fake_github,
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(updated.current_step, "deferred")
            self.assertEqual(fake_github.states, [("owner/sample", 7, "deferred", ["in-progress", "in-review"])])

    def test_implementer_command_dispatches_generically_by_tool(self):
        root = Path.cwd()
        codex_config = config_for(root)
        claude_config = ProjectConfig(
            name="sample",
            repo="owner/sample",
            default_branch="main",
            local_path=root / "target",
            agent_remote="agent",
            worker_home=root / "home",
            raw={"agents": {"implementer": {"model": "claude-sonnet-5"}}},
            path=root / "projects" / "sample.yaml",
            root=root,
        )

        codex_command = build_implementer_command(codex_config, root / "lease", root / "result.json")
        claude_command = build_implementer_command(claude_config, root / "lease", root / "result.json")

        self.assertEqual(codex_command[0], "codex")
        self.assertIn("--cd", codex_command)
        self.assertEqual(claude_command[0], "claude")
        self.assertIn("--model", claude_command)
        self.assertEqual(claude_command[claude_command.index("--model") + 1], "claude-sonnet-5")
        self.assertNotIn("--cd", claude_command)

    def test_proactive_advisor_request_consults_once_then_retries_implementer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_framework(root)
            lease = root / "lease"
            lease.mkdir()
            config = config_for(root)
            entry = entry_for(root)
            write_run_entry(config, entry)
            fake_github = FakeGitHub()
            calls = {"implementer": 0, "advisor": 0}

            def fake_runner(command, *args, **kwargs):
                if command[0].endswith("bin/advise"):
                    calls["advisor"] += 1
                    self.assertIn("--question", command)
                    self.assertEqual(command[command.index("--question") + 1], "which store wins?")
                    return subprocess.CompletedProcess(command, 0, stdout="Use the file store.", stderr="")
                calls["implementer"] += 1
                result_index = command.index("--output-last-message") + 1
                if calls["implementer"] == 1:
                    payload = (
                        '{"success": false, "summary": "need input",'
                        ' "advisor_request": {"question": "which store wins?", "context": "two stores disagree"}}'
                    )
                else:
                    payload = '{"success": true, "summary": "used the file store as advised"}'
                Path(command[result_index]).parent.mkdir(parents=True, exist_ok=True)
                Path(command[result_index]).write_text(payload, encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = run_implementer_once(
                config,
                entry,
                github_client=fake_github,
                runner=fake_runner,
            )

            updated = read_run_entry(config, 7)
            self.assertEqual(calls["advisor"], 1)
            self.assertEqual(calls["implementer"], 2)
            self.assertEqual(result.summary, "used the file store as advised")
            self.assertEqual(updated.last_summary, "used the file store as advised")
            self.assertEqual(fake_github.states, [])

    def test_run_advisor_once_writes_context_file_and_returns_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            seen = {}

            def fake_runner(command, **kwargs):
                seen["command"] = command
                return subprocess.CompletedProcess(command, 0, stdout="do the simple thing\n", stderr="")

            result = run_advisor_once(
                config,
                question="which approach?",
                context="option A vs option B",
                context_path=root / "context.md",
                runner=fake_runner,
            )

            self.assertEqual(result.answer, "do the simple thing")
            self.assertTrue((root / "context.md").is_file())
            self.assertEqual((root / "context.md").read_text(), "option A vs option B")
            self.assertIn("--question", seen["command"])
            self.assertIn("--context-file", seen["command"])


if __name__ == "__main__":
    unittest.main()
