from pathlib import Path
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.context_metrics import analyze_context_run


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


class ContextMetricsTests(unittest.TestCase):
    def test_analyzes_hot_files_rederived_lessons_gate_mentions_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            prompt_dir = root / ".orchestrator" / "prompts" / "sample"
            log_dir = root / ".orchestrator" / "logs" / "sample"
            result_dir = root / ".orchestrator" / "results" / "sample"
            prompt_dir.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            result_dir.mkdir(parents=True)
            (prompt_dir / "issue-7-implementer.md").write_text("abc", encoding="utf-8")
            (log_dir / "issue-7.log").write_text(
                "read today_page.dart and task_commands.dart\n"
                "rediscovered test-discipline and scrollUntilVisible\n"
                "ran melos run test:fast\n"
                '{"usage":{"output_tokens":12}}\n',
                encoding="utf-8",
            )
            (result_dir / "issue-7-implementer.json").write_text(
                '{"usage":{"completion_tokens":5}}\n',
                encoding="utf-8",
            )

            report = analyze_context_run(config)

            self.assertEqual(report.prompt_bytes_by_issue, {7: 3})
            self.assertEqual(report.output_tokens_by_issue, {7: 17})
            self.assertGreater(report.hot_file_mentions["packages/tovi_app/lib/src/tasks/today_page.dart"], 0)
            self.assertEqual(report.rederived_mentions["test-discipline"], 1)
            self.assertEqual(report.rederived_mentions["listview-scroll"], 1)
            self.assertEqual(report.full_gate_mentions, 1)


if __name__ == "__main__":
    unittest.main()
