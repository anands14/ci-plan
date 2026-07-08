from pathlib import Path
import json
import os
import stat
import subprocess
import tempfile
import unittest


GREEN_CHECKS = [
    {"name": "gate", "bucket": "pass", "state": "SUCCESS", "link": ""},
    {"name": "test-discipline", "bucket": "pass", "state": "SUCCESS", "link": ""},
    {"name": "daily-integration", "bucket": "pass", "state": "SUCCESS", "link": ""},
]
GREEN_WITH_SKIPPED_OPTIONAL = [
    *GREEN_CHECKS,
    {"name": "nightly", "bucket": "skipping", "state": "SKIPPED", "link": ""},
]


class MergeGateTests(unittest.TestCase):
    def test_orchestrator_python_only_merges_through_daily_integration_lane(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in (root / "orchestrator").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "gh pr merge" in text or '["gh", "pr", "merge"' in text or '"pr", "merge"' in text:
                if path.name != "integration.py":
                    offenders.append(path.name)

        self.assertEqual(offenders, [])

    def test_dry_run_accepts_only_when_required_contexts_are_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_env(Path(tmp), GREEN_WITH_SKIPPED_OPTIONAL)

            result = subprocess.run(
                ["bash", "bin/merge", "10", "--repo", "owner/sample", "--dry-run"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("would merge daily PR #10 to main", result.stdout)
            self.assertFalse((Path(tmp) / "merge.log").exists())

    def test_refuses_missing_required_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = [check for check in GREEN_CHECKS if check["name"] != "daily-integration"]
            env = self.fake_env(Path(tmp), checks)

            result = subprocess.run(
                ["bash", "bin/merge", "10", "--repo", "owner/sample", "--dry-run"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("required check 'daily-integration' is missing or not green", result.stderr)

    def test_refuses_non_daily_head_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self.fake_env(Path(tmp), GREEN_CHECKS, head_branch="feat/task")

            result = subprocess.run(
                ["bash", "bin/merge", "10", "--repo", "owner/sample", "--dry-run"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("is not a daily branch", result.stderr)

    def test_merge_uses_merge_commit_after_green_final_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self.fake_env(root, GREEN_CHECKS)

            result = subprocess.run(
                ["bash", "bin/merge", "10", "--repo", "owner/sample"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--merge", (root / "merge.log").read_text(encoding="utf-8"))

    def fake_env(self, root: Path, checks: list[dict], head_branch: str = "day/2026-07-06") -> dict[str, str]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        checks_path = root / "checks.json"
        checks_path.write_text(json.dumps(checks), encoding="utf-8")
        pr_path = root / "pr.json"
        pr_path.write_text(
            json.dumps(
                {
                    "headRefOid": "abc123",
                    "headRefName": head_branch,
                    "baseRefName": "main",
                }
            ),
            encoding="utf-8",
        )
        gh_path = bin_dir / "gh"
        gh_path.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  if printf '%s\n' "$*" | grep -q 'headRefName'; then
    cat "$FAKE_PR"
    exit 0
  fi
  echo "${FAKE_HEAD_SHA:-abc123}"
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "checks" ]; then
  cat "$FAKE_CHECKS"
  exit 0
fi
if [ "$1" = "pr" ] && [ "$2" = "merge" ]; then
  printf '%s\n' "$*" >> "$FAKE_MERGE_LOG"
  exit 0
fi
echo "unexpected gh args: $*" >&2
exit 2
""",
            encoding="utf-8",
        )
        gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        env["FAKE_CHECKS"] = str(checks_path)
        env["FAKE_MERGE_LOG"] = str(root / "merge.log")
        env["FAKE_PR"] = str(pr_path)
        env["FAKE_HEAD_SHA"] = "abc123"
        return env


if __name__ == "__main__":
    unittest.main()
