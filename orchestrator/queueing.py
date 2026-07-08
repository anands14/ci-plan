"""Ready-issue validation and claim flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

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


def validate_ready_issue(issue: dict[str, Any]) -> ReadyValidation:
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
    has_blockers = _has_non_none_items(dependencies)
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


def _has_non_none_items(text: str) -> bool:
    items = list_items(text)
    if not items and _meaningful(text):
        items = [text.strip()]
    return any(_normalize_none(item) not in NONE_WORDS for item in items)


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
