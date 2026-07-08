from pathlib import Path
import json
import os
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.heartbeat import check_heartbeat, write_heartbeat


def config_for(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="sample",
        repo="owner/sample",
        default_branch="main",
        local_path=root / "target",
        agent_remote="agent",
        worker_home=root / "home",
        raw={"triggers": {"poll_interval_seconds": 10}},
        path=root / "projects" / "sample.yaml",
        root=root,
    )


class HeartbeatTests(unittest.TestCase):
    def test_current_heartbeat_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))

            write_heartbeat(config, pid=os.getpid())
            status = check_heartbeat(config, max_age_seconds=60)

            self.assertTrue(status.ok)
            self.assertEqual(status.reason, "heartbeat ok")

    def test_dead_pid_triggers_alert_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = config_for(Path(tmp))

            write_heartbeat(config, pid=999999999)
            status = check_heartbeat(config, max_age_seconds=60)

            self.assertFalse(status.ok)
            self.assertIsNotNone(status.alert_path)
            data = json.loads(status.alert_path.read_text(encoding="utf-8"))
            self.assertIn("pid not alive", data["reason"])


if __name__ == "__main__":
    unittest.main()
