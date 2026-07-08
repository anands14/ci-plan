from pathlib import Path
import tempfile
import unittest

from orchestrator.config import ConfigError, env_token_prefix, load_project_config


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


class ConfigTests(unittest.TestCase):
    def test_loads_project_config_and_resolves_paths_from_framework_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "projects").mkdir()
            (root / "projects" / "sample.yaml").write_text(PROJECT_YAML)

            config = load_project_config("sample", root=root)

            self.assertEqual(config.name, "sample")
            self.assertEqual(config.repo, "owner/sample")
            self.assertEqual(config.repo_name, "sample")
            self.assertEqual(config.local_path, (root / "../sample-repo").resolve())
            self.assertTrue(str(config.worker_home).endswith(".agent-home/sample-worker"))

    def test_rejects_filename_project_name_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "projects").mkdir()
            (root / "projects" / "other.yaml").write_text(PROJECT_YAML)

            with self.assertRaises(ConfigError):
                load_project_config("other", root=root)

    def test_env_token_prefix_is_uppercase_identifier(self):
        self.assertEqual(env_token_prefix("anands14/tovi.git"), "ANANDS14_TOVI_GIT")


if __name__ == "__main__":
    unittest.main()
