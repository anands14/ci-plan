from pathlib import Path
import tempfile
import unittest

from orchestrator.__main__ import main
from orchestrator.config import ProjectConfig
from orchestrator.safety import is_paused, pause_path


PROJECT_YAML = """
project:
  name: sample
  repo: owner/sample
  default_branch: main
  local_path: ../sample-repo
  agent_remote: agent
worker_environment:
  home: ~/.agent-home/sample-worker
"""


class SafetyTests(unittest.TestCase):
    def test_pause_file_blocks_loop_advancing_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "projects").mkdir()
            (root / "projects" / "sample.yaml").write_text(PROJECT_YAML, encoding="utf-8")
            (root / ".orchestrator").mkdir()
            (root / ".orchestrator" / "PAUSE").write_text("stop\n", encoding="utf-8")

            code = main(["--root", str(root), "claim-next", "--project", "sample", "--dry-run"])

            self.assertEqual(code, 2)

    def test_is_paused_reads_project_pause_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = ProjectConfig(
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
            pause_path(config).parent.mkdir(parents=True)
            pause_path(config).write_text("stop\n", encoding="utf-8")

            self.assertTrue(is_paused(config))


if __name__ == "__main__":
    unittest.main()
