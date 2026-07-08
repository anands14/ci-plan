from pathlib import Path
import tempfile
import unittest

from orchestrator.concurrency import read_concurrency_policy, set_concurrency_stage
from orchestrator.config import ProjectConfig


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={
            "budget": {
                "concurrency": {
                    "implementers_start": 2,
                    "implementers_max": 5,
                    "reviewers": 1,
                    "sim_validations": 1,
                }
            }
        },
        path=root / "projects" / "sample.yaml",
        root=root,
    )


class ConcurrencyTests(unittest.TestCase):
    def test_defaults_to_one_watched_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = read_concurrency_policy(config_for(Path(tmp)))

            self.assertEqual(policy.stage, "watched-worker")
            self.assertEqual(policy.implementers, 1)
            self.assertEqual(policy.sim_validations, 0)

    def test_two_plus_sim_stage_allows_two_implementers_and_one_sim(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            set_concurrency_stage(config, "two-plus-sim")

            policy = read_concurrency_policy(config)

            self.assertEqual(policy.stage, "two-plus-sim")
            self.assertEqual(policy.implementers, 2)
            self.assertEqual(policy.sim_validations, 1)

    def test_scale_up_uses_configured_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))
            set_concurrency_stage(config, "scale-up")

            policy = read_concurrency_policy(config)

            self.assertEqual(policy.implementers, 5)
            self.assertEqual(policy.max_implementers, 5)


if __name__ == "__main__":
    unittest.main()
