"""Ready-issue validation and claim flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable

from . import github
from .config import ProjectConfig
from .ledger import make_run_entry, write_run_entry
from .tools import acquire_treehouse_lease, release_treehouse_lease


LIFECYCLE_LABELS = [
    "ready",
    "in-progress",
    "in-review",
    "approved",
    "integrated",
    "integration-failed",
    "deferred",
    "stuck",
]
REQUIRED_SECTIONS = {
    "goal": "Goal",
    "acceptance criteria": "Acceptance criteria",
    "files in scope": "Files in scope",
    "out of scope": "Out of scope",
    "dependencies / blockers": "Dependencies / blockers",
    "risk flags": "Risk flags",
    "size estimate": "Size estimate",
}
TEST_LEVELS = {
    "unit",
    "widget",
    "integration",
    "e2e",
    "backend-e2e",
    "backend e2e",
}
NONE_WORDS = {"none", "n/a", "na", "no blockers", "unblocked"}
PROTECTED_PATH_HINTS = (
    "docs/CONSTITUTION.md",
    ".github/",
    ".github/workflows/",
    ".no-mistakes.yaml",
    "AGENTS.md",
    "CLAUDE.md",
)


@dataclass(frozen=True)
class ReadyValidation:
    valid: bool
    route_label: str | None
    reasons: list[str]


@dataclass(frozen=True)
class ClaimResult:
    claimed: bool
    issue_number: int | None
    lease_path: Path | None
    ledger_path: Path | None
    actions: list[str]
    rejected: list[tuple[int, str, list[str]]]


@dataclass(frozen=True)
class BatchClaimResult:
    """Every issue claimed this round, plus what was deferred, why, and any rejections."""

    claimed: list[ClaimResult]
    deferred: list[int]
    actions: list[str]
    rejected: list[tuple[int, str, list[str]]]


BlockerResolver = Callable[[str], bool]


def validate_ready_issue(
    issue: dict[str, Any], *, blocker_resolver: BlockerResolver | None = None
) -> ReadyValidation:
    """Check a `ready`-contract candidate.

    `blocker_resolver`, when given, lets a numbered blocker (`#123`) count as
    resolved once its referenced issue is closed - this is what lets
    `advance_ready_frontier` promote a `blocked` issue without requiring the
    body to literally say `None`. Omit it (the default) to keep the strict
    behavior used when validating an issue already claiming to be `ready`.
    """
    body = str(issue.get("body") or "")
    sections = parse_sections(body)
    reasons: list[str] = []

    for key, label in REQUIRED_SECTIONS.items():
        if not _meaningful(sections.get(key, "")):
            reasons.append(f"missing or empty section: {label}")

    criteria = acceptance_criteria(sections.get("acceptance criteria", ""))
    if not criteria:
        reasons.append("acceptance criteria must include at least one checkbox item")
    else:
        for criterion in criteria:
            if not criterion_has_test_level(criterion):
                reasons.append(
                    f"acceptance criterion lacks a recognized test level: {criterion}"
                )

    scope = list_items(sections.get("files in scope", ""))
    if not scope:
        reasons.append("files in scope must include at least one file or module")

    size = sections.get("size estimate", "")
    if _meaningful(size):
        if "review minutes" not in size.lower():
            reasons.append("size estimate must include review minutes")
        if "priority" not in size.lower():
            reasons.append("size estimate must include priority")

    dependencies = sections.get("dependencies / blockers", "")
    has_blockers = _has_non_none_items(dependencies, blocker_resolver)
    if has_blockers:
        reasons.append("dependencies or blockers are not clear")
    risk_flags = sections.get("risk flags", "")
    if _scope_has_protected_path(scope) and _section_is_none(risk_flags):
        reasons.append("protected-path scope requires a non-None risk flag")

    if not reasons:
        return ReadyValidation(valid=True, route_label=None, reasons=[])
    return ReadyValidation(
        valid=False,
        route_label="blocked" if has_blockers else "needs-human",
        reasons=reasons,
    )


def parse_blocker_refs(text: str) -> list[int]:
    """Issue numbers a blocker item references, e.g. `#88` -> `[88]`."""
    return [int(match) for match in re.findall(r"#(\d+)", text)]


def claim_next_ready(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    github_client: Any = github,
    lease_func: Any = acquire_treehouse_lease,
    release_func: Any = release_treehouse_lease,
    write_entry_func: Any = write_run_entry,
) -> ClaimResult:
    actions: list[str] = []
    rejected: list[tuple[int, str, list[str]]] = []
    candidates: list[dict[str, Any]] = []

    issues = github_client.ready_issues(config.repo)
    actions.append(f"read {len(issues)} ready issue(s)")

    for issue in issues:
        validation = validate_ready_issue(issue)
        if validation.valid:
            candidates.append(issue)
            continue

        number = int(issue["number"])
        label = validation.route_label or "needs-human"
        rejected.append((number, label, validation.reasons))
        actions.append(f"reject issue #{number}: remove ready, add {label}")
        if not dry_run:
            github_client.set_state(config.repo, number, label, remove=["ready"])

    contention = _shared_scope_contention(candidates)
    claimable = []
    for issue in candidates:
        number = int(issue["number"])
        reasons = contention.get(number, [])
        if reasons:
            rejected.append((number, "needs-human", reasons))
            actions.append(f"reject issue #{number}: remove ready, add needs-human")
            if not dry_run:
                github_client.set_state(config.repo, number, "needs-human", remove=["ready"])
        else:
            claimable.append(issue)

    candidate = claimable[0] if claimable else None
    if candidate is None:
        actions.append("no valid ready issue to claim")
        return ClaimResult(False, None, None, None, actions, rejected)

    number = int(candidate["number"])
    actions.append(f"claim issue #{number}: ready -> in-progress")
    if dry_run:
        actions.append(f"would acquire treehouse lease for issue #{number}")
        actions.append(f"would write ledger entry for issue #{number}")
        return ClaimResult(True, number, None, None, actions, rejected)

    github_client.set_state(config.repo, number, "in-progress", remove=["ready"])
    lease_path: Path | None = None
    try:
        lease_path = lease_func(config, number)
        actions.append(f"acquired treehouse lease: {lease_path}")
        entry = make_run_entry(config, candidate, lease_path)
        ledger_path = write_entry_func(config, entry)
        actions.append(f"wrote run ledger: {ledger_path}")
        return ClaimResult(True, number, lease_path, ledger_path, actions, rejected)
    except Exception:
        if lease_path is not None:
            release_func(lease_path)
        github_client.set_state(config.repo, number, "ready", remove=["in-progress"])
        raise


def make_blocker_resolver(github_client: Any, repo: str) -> BlockerResolver:
    """A resolver backed by real GitHub issue state, one lookup per referenced number."""
    closed_cache: dict[int, bool] = {}

    def resolver(item: str) -> bool:
        refs = parse_blocker_refs(item)
        if not refs:
            return False
        for number in refs:
            if number not in closed_cache:
                closed_cache[number] = bool(github_client.issue_closed(repo, number))
            if not closed_cache[number]:
                return False
        return True

    return resolver


def advance_ready_frontier(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    github_client: Any = github,
) -> list[int]:
    """Promote `blocked` issues to `ready` the moment every `#N` blocker closes.

    This is what lets waves advance on their own: nobody hand-relabels the
    next batch once the issues already declare their real blocking edges.
    """
    resolver = make_blocker_resolver(github_client, config.repo)
    promoted: list[int] = []
    for issue in github_client.issues_with_label(config.repo, "blocked"):
        validation = validate_ready_issue(issue, blocker_resolver=resolver)
        if not validation.valid:
            continue
        number = int(issue["number"])
        if not dry_run:
            github_client.set_state(config.repo, number, "ready", remove=["blocked"])
        promoted.append(number)
    return promoted


def _issue_scope(issue: dict[str, Any]) -> list[str]:
    sections = parse_sections(str(issue.get("body") or ""))
    return list_items(sections.get("files in scope", ""))


def claim_all_ready(
    config: ProjectConfig,
    *,
    dry_run: bool = False,
    github_client: Any = github,
    lease_func: Any = acquire_treehouse_lease,
    release_func: Any = release_treehouse_lease,
    write_entry_func: Any = write_run_entry,
) -> BatchClaimResult:
    """Claim every currently-safe `ready` issue - no fixed worker-count cap.

    Concurrency is bounded only by the dependency frontier and file-scope
    collisions: an undeclared overlap between two ready candidates is rejected
    to `needs-human` (a slicing problem), same as `claim_next_ready`; a
    declared or in-flight overlap is serialized instead - claim one this
    round, leave the other `ready` and unclaimed for the next round once the
    first integrates.
    """
    actions: list[str] = []
    rejected: list[tuple[int, str, list[str]]] = []
    deferred: list[int] = []
    candidates: list[dict[str, Any]] = []

    issues = github_client.ready_issues(config.repo)
    actions.append(f"read {len(issues)} ready issue(s)")

    for issue in issues:
        validation = validate_ready_issue(issue)
        if validation.valid:
            candidates.append(issue)
            continue
        number = int(issue["number"])
        label = validation.route_label or "needs-human"
        rejected.append((number, label, validation.reasons))
        actions.append(f"reject issue #{number}: remove ready, add {label}")
        if not dry_run:
            github_client.set_state(config.repo, number, label, remove=["ready"])

    contention = _shared_scope_contention(candidates)
    survivors: list[dict[str, Any]] = []
    for issue in candidates:
        number = int(issue["number"])
        reasons = contention.get(number, [])
        if reasons:
            rejected.append((number, "needs-human", reasons))
            actions.append(f"reject issue #{number}: remove ready, add needs-human")
            if not dry_run:
                github_client.set_state(config.repo, number, "needs-human", remove=["ready"])
        else:
            survivors.append(issue)

    claimed_scope: list[str] = []
    for other in github_client.issues_with_label(config.repo, "in-progress"):
        claimed_scope.extend(_issue_scope(other))

    claimed: list[ClaimResult] = []
    for issue in survivors:
        number = int(issue["number"])
        scope = _issue_scope(issue)
        if _scope_overlap(scope, claimed_scope):
            deferred.append(number)
            actions.append(
                f"defer issue #{number}: scope overlaps in-flight or already-claimed work this round"
            )
            continue

        actions.append(f"claim issue #{number}: ready -> in-progress")
        if dry_run:
            actions.append(f"would acquire treehouse lease for issue #{number}")
            actions.append(f"would write ledger entry for issue #{number}")
            claimed.append(ClaimResult(True, number, None, None, [], []))
            claimed_scope.extend(scope)
            continue

        github_client.set_state(config.repo, number, "in-progress", remove=["ready"])
        lease_path: Path | None = None
        try:
            lease_path = lease_func(config, number)
            entry = make_run_entry(config, issue, lease_path)
            ledger_path = write_entry_func(config, entry)
            claimed.append(ClaimResult(True, number, lease_path, ledger_path, [], []))
            claimed_scope.extend(scope)
        except Exception:
            if lease_path is not None:
                release_func(lease_path)
            github_client.set_state(config.repo, number, "ready", remove=["in-progress"])
            raise

    return BatchClaimResult(claimed=claimed, deferred=deferred, actions=actions, rejected=rejected)


def parse_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def acceptance_criteria(text: str) -> list[str]:
    items = []
    for line in _strip_comments(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            items.append(stripped)
    return items


def criterion_has_test_level(text: str) -> bool:
    match = re.search(r"\(([^)]+)\)", text)
    return bool(match and match.group(1).strip().lower() in TEST_LEVELS)


def list_items(text: str) -> list[str]:
    items = []
    for line in _strip_comments(text).splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip().strip("`")
        if _meaningful(item):
            items.append(item)
    return items


def _meaningful(text: str) -> bool:
    stripped = _strip_comments(text).strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in {"-", "~", "..."}:
        return False
    if stripped.startswith("<") and stripped.endswith(">"):
        return False
    return True


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _has_non_none_items(text: str, resolver: BlockerResolver | None = None) -> bool:
    items = list_items(text)
    if not items and _meaningful(text):
        items = [text.strip()]
    for item in items:
        if _normalize_none(item) in NONE_WORDS:
            continue
        if resolver is not None and resolver(item):
            continue
        return True
    return False


def _section_is_none(text: str) -> bool:
    items = list_items(text)
    if not items and _meaningful(text):
        items = [text.strip()]
    return bool(items) and all(_normalize_none(item) in NONE_WORDS for item in items)


def _normalize_none(text: str) -> str:
    return text.strip().strip(".").lower()


def _scope_has_protected_path(scope: list[str]) -> bool:
    return any(
        any(item.startswith(hint) or hint in item for hint in PROTECTED_PATH_HINTS)
        for item in scope
    )


def _shared_scope_contention(issues: list[dict[str, Any]]) -> dict[int, list[str]]:
    scoped = []
    for issue in issues:
        sections = parse_sections(str(issue.get("body") or ""))
        scope = list_items(sections.get("files in scope", ""))
        risk_flags = list_items(sections.get("risk flags", ""))
        scoped.append((issue, scope, risk_flags))

    reasons: dict[int, list[str]] = {}
    for index, (issue, scope, risk_flags) in enumerate(scoped):
        declares_risk = _declares_shared_file_risk(risk_flags)
        for other, other_scope, other_risk_flags in scoped[index + 1 :]:
            overlap = _scope_overlap(scope, other_scope)
            if not overlap:
                continue
            other_declares_risk = _declares_shared_file_risk(other_risk_flags)
            if declares_risk and other_declares_risk:
                continue
            number = int(issue["number"])
            other_number = int(other["number"])
            if not declares_risk:
                reason = (
                    f"files in scope overlap ready issue #{other_number} at {overlap}; "
                    "split for file-disjointness or declare shared-file risk"
                )
                reasons.setdefault(number, []).append(reason)
            if not other_declares_risk:
                other_reason = (
                    f"files in scope overlap ready issue #{number} at {overlap}; "
                    "split for file-disjointness or declare shared-file risk"
                )
                reasons.setdefault(other_number, []).append(other_reason)
    return reasons


def _scope_overlap(left: list[str], right: list[str]) -> str | None:
    for left_item in left:
        for right_item in right:
            if _scope_items_overlap(left_item, right_item):
                return left_item if len(left_item) <= len(right_item) else right_item
    return None


def _scope_items_overlap(left: str, right: str) -> bool:
    left_norm = _normalize_scope(left)
    right_norm = _normalize_scope(right)
    return (
        left_norm == right_norm
        or left_norm.startswith(right_norm + "/")
        or right_norm.startswith(left_norm + "/")
    )


def _normalize_scope(item: str) -> str:
    return item.strip().strip("`").strip("/").replace("\\", "/")


def _declares_shared_file_risk(risk_flags: list[str]) -> bool:
    text = " ".join(risk_flags).lower()
    return "shared-file" in text or "shared file" in text or "overlap" in text
