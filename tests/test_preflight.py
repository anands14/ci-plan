from pathlib import Path
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.preflight import (
    build_worker_env,
    orchestrator_token_names,
    origin_failure_proves_blocked,
)


class PreflightTests(unittest.TestCase):
    def test_worker_env_sets_home_and_scrubs_auth(self):
        env = build_worker_env(
            Path("/tmp/agent-home"),
            base={
                "PATH": "/bin",
                "HOME": "/Users/human",
                "GH_TOKEN": "human",
                "GITHUB_TOKEN": "human",
                "SSH_AUTH_SOCK": "/tmp/ssh.sock",
                "GIT_ASKPASS": "ask",
            },
        )

        self.assertEqual(env["HOME"], "/tmp/agent-home")
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertNotIn("GIT_ASKPASS", env)

    def test_orchestrator_token_names_include_project_and_repo(self):
        config = ProjectConfig(
            name="humanmind",
            repo="anands14/tovi",
            default_branch="main",
            local_path=Path("/repo"),
            agent_remote="agent",
            worker_home=Path("/home"),
            raw={},
            path=Path("/config"),
            root=Path("/root"),
        )

        names = orchestrator_token_names(config)

        self.assertIn("HUMANMIND_ORCHESTRATOR_GH_TOKEN", names)
        self.assertIn("TOVI_ORCHESTRATOR_GH_TOKEN", names)
        self.assertIn("ORCHESTRATOR_GH_TOKEN", names)

    def test_origin_push_blocked_requires_auth_or_permission_denial(self):
        self.assertTrue(
            origin_failure_proves_blocked(
                "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
            )
        )
        self.assertFalse(
            origin_failure_proves_blocked(
                "fatal: unable to access 'https://github.com/x/y.git/': Could not resolve host: github.com"
            )
        )


if __name__ == "__main__":
    unittest.main()
