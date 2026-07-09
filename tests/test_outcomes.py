from pathlib import Path
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.ledger import RunLedgerEntry, read_run_entry, write_run_entry
from orchestrator.outcomes import classify_summary, resume_deferred, should_consult_advisor


class FakeGitHub:
    def __init__(self):
        self.states = []

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


class OutcomeTests(unittest.TestCase):
    def test_classifies_stuck_and_deferred(self):
        config = config_for(Path("/tmp"))

        self.assertEqual(classify_summary(config, "Spec is unclear").state, "stuck")
        self.assertEqual(classify_summary(config, "Window share ceiling reached").state, "deferred")
        self.assertEqual(classify_summary(config, "Provided authentication token is expired").state, "operator-blocked")

    def test_advisor_consult_skips_operator_and_deferred_failures(self):
        self.assertTrue(should_consult_advisor("tool exited without a clear reason"))
        self.assertTrue(should_consult_advisor("Spec is unclear"))
        self.assertFalse(should_consult_advisor("Window share ceiling reached"))
        self.assertFalse(should_consult_advisor("Your access token could not be refreshed"))

    def test_resume_deferred_preserves_lease_and_sets_in_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            entry = RunLedgerEntry(
                project="sample",
                repo="owner/sample",
                issue_number=7,
                issue_title="Task",
                lease_path=str(root / "lease"),
                current_step="deferred",
                log_path=str(root / ".orchestrator" / "logs" / "sample" / "issue-7.log"),
                claimed_at="2026-07-02T00:00:00+00:00",
            )
            write_run_entry(config, entry)
            fake_github = FakeGitHub()

            result = resume_deferred(config, entry, github_client=fake_github)

            updated = read_run_entry(config, 7)
            self.assertTrue(result.resumed)
            self.assertEqual(updated.current_step, "claimed")
            self.assertEqual(updated.lease_path, str(root / "lease"))
            self.assertEqual(fake_github.states, [("owner/sample", 7, "in-progress", ["deferred"])])


if __name__ == "__main__":
    unittest.main()
