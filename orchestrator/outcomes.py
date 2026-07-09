"""Classify loop outcomes into continue, deferred, or stuck."""

from __future__ import annotations

from dataclasses import dataclass

from . import github
from .config import ProjectConfig
from .ledger import RunLedgerEntry, update_run_entry


STUCK_PATTERNS = (
    "dispute",
    "spec unclear",
    "spec is unclear",
    "spec wrong",
    "spec is wrong",
    "protected path",
    "architecture invariant",
    "no material diff",
    "missing external input",
    "requires human input",
    "cannot proceed without",
)
OPERATOR_BLOCKED_PATTERNS = (
    "access token",
    "api_error_status",
    "auth failed",
    "auth failure",
    "authentication",
    "could not resolve host",
    "login",
    "not logged in",
    "permission denied",
    "rate limit",
    "refresh token",
    "session limit",
    "token_expired",
    "unauthorized",
    "401",
    "429",
)
DEFERRED_PATTERNS = (
    "window share",
    "window-share",
    "fairness pause",
    "budget ceiling",
    "resume when window returns",
)


@dataclass(frozen=True)
class OutcomeClassification:
    state: str
    reason: str | None


@dataclass(frozen=True)
class ResumeResult:
    resumed: bool
    summary: str


def classify_summary(config: ProjectConfig | None, summary: str | None) -> OutcomeClassification:
    text = (summary or "").lower()
    for pattern in OPERATOR_BLOCKED_PATTERNS:
        if pattern in text:
            return OutcomeClassification("operator-blocked", _short(summary))
    for pattern in STUCK_PATTERNS:
        if pattern in text:
            return OutcomeClassification("stuck", _short(summary))
    for pattern in DEFERRED_PATTERNS:
        if pattern in text:
            return OutcomeClassification("deferred", _short(summary))
    return OutcomeClassification("continue", None)


def should_consult_advisor(summary: str | None) -> bool:
    """Use advisor tokens only where advice could plausibly change the next turn."""
    text = (summary or "").strip()
    if not text:
        return True
    classification = classify_summary(None, text)
    return classification.state in {"continue", "stuck"}


def resume_deferred(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    github_client=github,
) -> ResumeResult:
    if entry.current_step != "deferred":
        return ResumeResult(False, f"issue #{entry.issue_number} is not deferred")
    summary = "deferred task resumed; lease preserved"
    github_client.set_state(config.repo, entry.issue_number, "in-progress", ["deferred"])
    update_run_entry(
        config,
        entry,
        current_step="claimed",
        last_summary=summary,
    )
    return ResumeResult(True, summary)


def _short(text: str | None, limit: int = 240) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "..."
