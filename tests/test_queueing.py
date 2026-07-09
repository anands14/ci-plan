from pathlib import Path
import tempfile
import unittest

from orchestrator.config import ProjectConfig
from orchestrator.ledger import make_run_entry, write_run_entry
from orchestrator.queueing import (
    advance_ready_frontier,
    claim_all_ready,
    claim_next_ready,
    make_blocker_resolver,
    parse_blocker_refs,
    validate_ready_issue,
)


VALID_BODY = """
## Goal

Deliver a small thing.

## Acceptance criteria

- [ ] (unit) `A` returns `B`
- [ ] (backend-e2e) data persists through the adapter

## Files in scope

- `lib/a.dart`

## Out of scope

- UI work

## Dependencies / blockers

- None

## Risk flags

- None

## Size estimate

- Review minutes: ~15
- Priority: p2
"""


class FakeGitHub:
    def __init__(self, issues=None, *, by_label=None, closed_numbers=None):
        self.issues = issues or []
        self.by_label = by_label or {}
        self.closed_numbers = set(closed_numbers or [])
        self.states = []

    def ready_issues(self, repo):
        return self.issues

    def issues_with_label(self, repo, label):
        if label == "ready":
            return self.issues
        return self.by_label.get(label, [])

    def issue_closed(self, repo, number):
        return number in self.closed_numbers

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


class ReadyValidationTests(unittest.TestCase):
    def test_accepts_valid_ready_issue(self):
        result = validate_ready_issue({"body": VALID_BODY})

        self.assertTrue(result.valid)
        self.assertEqual(result.reasons, [])

    def test_rejects_missing_scope_as_needs_human(self):
        body = VALID_BODY.replace("- `lib/a.dart`", "")

        result = validate_ready_issue({"body": body})

        self.assertFalse(result.valid)
        self.assertEqual(result.route_label, "needs-human")
        self.assertIn(
            "files in scope must include at least one file or module",
            result.reasons,
        )

    def test_routes_non_none_blockers_to_blocked(self):
        body = VALID_BODY.replace(
            "## Dependencies / blockers\n\n- None",
            "## Dependencies / blockers\n\n- #123",
        )

        result = validate_ready_issue({"body": body})

        self.assertFalse(result.valid)
        self.assertEqual(result.route_label, "blocked")

    def test_rejects_unlabeled_acceptance_criterion(self):
        body = VALID_BODY.replace(
            "- [ ] (unit) `A` returns `B`",
            "- [ ] `A` returns `B`",
        )

        result = validate_ready_issue({"body": body})

        self.assertFalse(result.valid)
        self.assertTrue(
            any("lacks a recognized test level" in reason for reason in result.reasons)
        )


def body_with_scope(scope: str, risk: str = "None") -> str:
    return VALID_BODY.replace("- `lib/a.dart`", f"- `{scope}`").replace(
        "## Risk flags\n\n- None",
        f"## Risk flags\n\n- {risk}",
    )


class ClaimNextTests(unittest.TestCase):
    def test_rejects_invalid_issues_then_claims_one_valid_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            invalid = {"number": 1, "title": "bad", "body": "## Goal\n\nx"}
            valid = {"number": 2, "title": "good", "body": VALID_BODY}
            fake_github = FakeGitHub([invalid, valid])

            result = claim_next_ready(
                config,
                github_client=fake_github,
                lease_func=lambda _config, _number: root / "lease",
            )

            self.assertTrue(result.claimed)
            self.assertEqual(result.issue_number, 2)
            self.assertEqual(
                fake_github.states[0],
                ("owner/sample", 1, "needs-human", ["ready"]),
            )
            self.assertEqual(
                fake_github.states[1],
                ("owner/sample", 2, "in-progress", ["ready"]),
            )
            self.assertTrue(
                (root / ".orchestrator" / "runs" / "sample-issue-2.json").is_file()
            )

    def test_dry_run_does_not_mutate_or_write_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            fake_github = FakeGitHub(
                [{"number": 2, "title": "good", "body": VALID_BODY}]
            )

            result = claim_next_ready(config, dry_run=True, github_client=fake_github)

            self.assertTrue(result.claimed)
            self.assertEqual(fake_github.states, [])
            self.assertFalse((root / ".orchestrator").exists())

    def test_rejects_ready_issues_with_undeclared_shared_file_contention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            fake_github = FakeGitHub(
                [
                    {"number": 1, "title": "one", "body": body_with_scope("lib/a.dart")},
                    {"number": 2, "title": "two", "body": body_with_scope("lib/a.dart")},
                ]
            )

            result = claim_next_ready(config, dry_run=True, github_client=fake_github)

            self.assertFalse(result.claimed)
            self.assertEqual(len(result.rejected), 2)
            self.assertTrue(
                all("overlap ready issue" in reasons[0] for _number, _label, reasons in result.rejected)
            )

    def test_allows_shared_file_contention_when_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            fake_github = FakeGitHub(
                [
                    {
                        "number": 1,
                        "title": "one",
                        "body": body_with_scope("lib/a.dart", "Shared-file risk with #2"),
                    },
                    {
                        "number": 2,
                        "title": "two",
                        "body": body_with_scope("lib/a.dart", "Shared-file risk with #1"),
                    },
                ]
            )

            result = claim_next_ready(config, dry_run=True, github_client=fake_github)

            self.assertTrue(result.claimed)
            self.assertEqual(result.issue_number, 1)
            self.assertEqual(result.rejected, [])

    def test_ledger_entry_records_claim_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            issue = {"number": 7, "title": "Task"}

            entry = make_run_entry(config, issue, root / "lease")
            path = write_run_entry(config, entry)

            self.assertTrue(path.is_file())
            self.assertIn("sample-issue-7.json", str(path))


class BlockerParsingTests(unittest.TestCase):
    def test_parse_blocker_refs_extracts_issue_numbers(self):
        self.assertEqual(parse_blocker_refs("- #88, blocked on #91 too"), [88, 91])
        self.assertEqual(parse_blocker_refs("None"), [])

    def test_resolver_resolves_only_when_every_referenced_issue_is_closed(self):
        github_client = FakeGitHub(closed_numbers=[88])
        resolver = make_blocker_resolver(github_client, "owner/sample")

        self.assertTrue(resolver("#88"))
        self.assertFalse(resolver("#88, #91"))
        self.assertFalse(resolver("waiting on design sign-off"))


def blocked_body(blocker: str) -> str:
    return VALID_BODY.replace("## Dependencies / blockers\n\n- None", f"## Dependencies / blockers\n\n- {blocker}")


class AdvanceFrontierTests(unittest.TestCase):
    def test_promotes_blocked_issue_once_every_referenced_blocker_is_closed(self):
        github_client = FakeGitHub(
            by_label={"blocked": [{"number": 5, "title": "waits on 88", "body": blocked_body("#88")}]},
            closed_numbers=[88],
        )

        promoted = advance_ready_frontier(config_for(Path("/tmp")), github_client=github_client)

        self.assertEqual(promoted, [5])
        self.assertEqual(github_client.states, [("owner/sample", 5, "ready", ["blocked"])])

    def test_leaves_issue_blocked_while_its_blocker_is_still_open(self):
        github_client = FakeGitHub(
            by_label={"blocked": [{"number": 5, "title": "waits on 88", "body": blocked_body("#88")}]},
            closed_numbers=[],
        )

        promoted = advance_ready_frontier(config_for(Path("/tmp")), github_client=github_client)

        self.assertEqual(promoted, [])
        self.assertEqual(github_client.states, [])


class ClaimAllReadyTests(unittest.TestCase):
    def test_claims_every_disjoint_ready_candidate_no_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [
                    {"number": 1, "title": "one", "body": body_with_scope("lib/a.dart")},
                    {"number": 2, "title": "two", "body": body_with_scope("lib/b.dart")},
                    {"number": 3, "title": "three", "body": body_with_scope("lib/c.dart")},
                ]
            )

            result = claim_all_ready(config, dry_run=True, github_client=github_client)

            self.assertEqual({c.issue_number for c in result.claimed}, {1, 2, 3})
            self.assertEqual(result.deferred, [])
            self.assertEqual(result.rejected, [])

    def test_defers_ready_candidate_whose_scope_overlaps_in_flight_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [{"number": 2, "title": "two", "body": body_with_scope("lib/a.dart")}],
                by_label={
                    "in-progress": [
                        {"number": 1, "title": "one", "body": body_with_scope("lib/a.dart")}
                    ]
                },
            )

            result = claim_all_ready(config, dry_run=True, github_client=github_client)

            self.assertEqual(result.claimed, [])
            self.assertEqual(result.deferred, [2])
            self.assertEqual(result.rejected, [])

    def test_serializes_declared_shared_file_overlap_within_one_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [
                    {
                        "number": 1,
                        "title": "one",
                        "body": body_with_scope("lib/a.dart", "Shared-file risk with #2"),
                    },
                    {
                        "number": 2,
                        "title": "two",
                        "body": body_with_scope("lib/a.dart", "Shared-file risk with #1"),
                    },
                ]
            )

            result = claim_all_ready(config, dry_run=True, github_client=github_client)

            self.assertEqual([c.issue_number for c in result.claimed], [1])
            self.assertEqual(result.deferred, [2])
            self.assertEqual(result.rejected, [])

    def test_still_rejects_undeclared_scope_overlap_to_needs_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = config_for(root)
            github_client = FakeGitHub(
                [
                    {"number": 1, "title": "one", "body": body_with_scope("lib/a.dart")},
                    {"number": 2, "title": "two", "body": body_with_scope("lib/a.dart")},
                ]
            )

            result = claim_all_ready(config, dry_run=True, github_client=github_client)

            self.assertEqual(result.claimed, [])
            self.assertEqual(len(result.rejected), 2)


if __name__ == "__main__":
    unittest.main()
