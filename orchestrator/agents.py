"""Agent drivers and prompt injection helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any

from . import github
from .config import ProjectConfig
from .context import (
    append_handoff_entry,
    build_compact_brief,
    handoff_log_relative_path,
    read_handoff_excerpt,
)
from .ledger import RunLedgerEntry, update_run_entry
from .outcomes import classify_summary
from .preflight import build_worker_env


@dataclass(frozen=True)
class ImplementerRun:
    command: list[str]
    prompt_path: Path
    result_path: Path
    log_path: Path
    head_before: str | None
    head_after: str | None
    codex_session_id: str | None
    summary: str
    returncode: int


@dataclass(frozen=True)
class CheckpointResult:
    created: bool
    message: str
    head_before: str | None
    head_after: str | None


def build_implementer_prompt(
    config: ProjectConfig,
    issue: dict[str, Any],
    *,
    lease_path: Path | None = None,
    feedback: str | None = None,
) -> str:
    handoff = (
        read_handoff_excerpt(config, lease_path)
        if lease_path is not None
        else "_No worktree handoff excerpt available in this dry prompt build._"
    )

    return f"""{build_compact_brief(config)}

---

# Handoff

file: `{handoff_log_relative_path(config)}`
use as pointer only; code/tests are truth.

{handoff}

---

# Task

Issue #{issue["number"]}: {issue["title"]}

{issue.get("body") or ""}

---

# Run Rules

- cwd is leased worktree only.
- M2 implementer step: do not push/open/update PR or run handoff.
- checkpoint stable progress; if unsafe/blocked, escalate in JSON.
- return JSON only.
{_feedback_section(feedback)}
"""


def run_implementer_once(
    config: ProjectConfig,
    entry: RunLedgerEntry,
    *,
    dry_run: bool = False,
    github_client: Any = github,
    runner: Any = subprocess.run,
) -> ImplementerRun:
    issue = github_client.issue(config.repo, entry.issue_number)
    prompt = build_implementer_prompt(
        config,
        issue,
        lease_path=Path(entry.lease_path),
        feedback=build_feedback_context(config, entry),
    )
    prompt_path = _prompt_path(config, entry.issue_number)
    result_path = _result_path(config, entry.issue_number)
    log_path = Path(entry.log_path)
    lease_path = Path(entry.lease_path)
    command = [
        "codex",
        "exec",
        "--model",
        config.implementer_model,
        "-c",
        f'model_reasoning_effort="{config.implementer_effort}"',
        "--cd",
        str(lease_path),
        "--json",
        "--output-last-message",
        str(result_path),
        "-",
    ]

    head_before = _git_head(lease_path)
    if dry_run:
        return ImplementerRun(
            command=command,
            prompt_path=prompt_path,
            result_path=result_path,
            log_path=log_path,
            head_before=head_before,
            head_after=head_before,
            codex_session_id=None,
            summary=f"would run codex with {len(prompt)} bytes of prompt",
            returncode=0,
        )

    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    result = runner(
        command,
        input=prompt,
        capture_output=True,
        text=True,
        env=build_worker_env(config.worker_home),
    )
    log_path.write_text(result.stdout, encoding="utf-8")
    if result.stderr:
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n--- stderr ---\n")
            f.write(result.stderr)

    head_after = _git_head(lease_path)
    session_id = extract_session_id(result.stdout)
    final_text = result_path.read_text(encoding="utf-8") if result_path.is_file() else ""
    summary = compact_summary(final_text, result.stdout, result.returncode)
    returncode = result.returncode
    current_step = "implementer-ran" if result.returncode == 0 else "implementer-failed"
    if result.returncode != 0:
        classification = classify_summary(config, summary)
        if classification.state in {"stuck", "deferred"}:
            current_step = classification.state
            github_client.set_state(
                config.repo,
                entry.issue_number,
                classification.state,
                ["in-progress", "in-review"],
            )
    if result.returncode == 0:
        append_handoff_entry(
            config,
            lease_path,
            issue,
            final_text=final_text,
            summary=summary,
            head_after=head_after,
        )
    if result.returncode == 0 and _git_dirty(lease_path):
        checkpoint = create_checkpoint_commit(lease_path, entry.issue_number, entry.issue_title)
        if checkpoint.created:
            head_after = checkpoint.head_after
            summary = f"{summary} Checkpoint commit: {checkpoint.head_after}."
        else:
            current_step = "checkpoint-required"
            returncode = 1
            summary = checkpoint.message
    update_run_entry(
        config,
        entry,
        current_step=current_step,
        codex_session_id=session_id,
        prompt_path=str(prompt_path),
        result_path=str(result_path),
        head_before=head_before,
        head_after=head_after,
        last_summary=summary,
    )

    return ImplementerRun(
        command=command,
        prompt_path=prompt_path,
        result_path=result_path,
        log_path=log_path,
        head_before=head_before,
        head_after=head_after,
        codex_session_id=session_id,
        summary=summary,
        returncode=returncode,
    )


def checkpoint_entry(config: ProjectConfig, entry: RunLedgerEntry) -> CheckpointResult:
    lease_path = Path(entry.lease_path)
    result = create_checkpoint_commit(lease_path, entry.issue_number, entry.issue_title)
    if result.created:
        update_run_entry(
            config,
            entry,
            current_step="implementer-ran",
            head_before=entry.head_before or result.head_before,
            head_after=result.head_after,
            last_summary=f"Checkpoint commit: {result.head_after}.",
        )
    return result


def create_checkpoint_commit(
    lease_path: Path,
    issue_number: int,
    issue_title: str,
) -> CheckpointResult:
    head_before = _git_head(lease_path)
    if not _git_dirty(lease_path):
        return CheckpointResult(False, "no dirty worktree changes to checkpoint", head_before, head_before)

    check = subprocess.run(
        ["git", "diff", "--check"],
        cwd=lease_path,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        detail = (check.stderr or check.stdout).strip()
        return CheckpointResult(
            False,
            f"checkpoint blocked by git diff --check: {detail}",
            head_before,
            head_before,
        )

    add = subprocess.run(
        ["git", "add", "--all"],
        cwd=lease_path,
        capture_output=True,
        text=True,
    )
    if add.returncode != 0:
        detail = (add.stderr or add.stdout).strip()
        return CheckpointResult(False, f"checkpoint git add failed: {detail}", head_before, head_before)

    commit = subprocess.run(
        ["git", "commit", "-m", _checkpoint_message(issue_number, issue_title)],
        cwd=lease_path,
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout).strip()
        return CheckpointResult(False, f"checkpoint git commit failed: {detail}", head_before, head_before)

    head_after = _git_head(lease_path)
    return CheckpointResult(True, f"checkpoint commit created: {head_after}", head_before, head_after)


def extract_session_id(jsonl: str) -> str | None:
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        found = _find_key(event, {"session_id", "sessionId"})
        if isinstance(found, str) and found:
            return found
    return None


def compact_summary(final_text: str, jsonl: str, returncode: int) -> str:
    parsed = _maybe_json(final_text)
    if isinstance(parsed, dict) and isinstance(parsed.get("summary"), str):
        return parsed["summary"][:1000]
    text = final_text.strip()
    if not text:
        text = f"codex exec exited with status {returncode}"
    return " ".join(text.split())[:1000]


def build_feedback_context(config: ProjectConfig, entry: RunLedgerEntry) -> str | None:
    if entry.current_step == "gate-failed":
        return _join_feedback(
            "The previous deterministic gate failed.",
            entry.gate_summary,
            _tail_gate_logs(config, entry),
        )
    if entry.current_step == "review-requested-changes":
        return _join_feedback(
            "The gating reviewer requested changes.",
            entry.review_summary,
            _tail_file(
                config.root
                / ".orchestrator"
                / "logs"
                / config.name
                / f"issue-{entry.issue_number}"
                / "review.log"
            ),
        )
    if entry.current_step == "base-refresh-conflict":
        return _join_feedback(
            "The branch could not be refreshed onto the latest base automatically.",
            entry.base_summary,
            _tail_file(
                config.root
                / ".orchestrator"
                / "logs"
                / config.name
                / f"issue-{entry.issue_number}"
                / "base-refresh.log"
            ),
        )
    return None


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_key(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if key in value:
                return value[key]
        for child in value.values():
            found = _find_key(child, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_key(child, keys)
            if found is not None:
                return found
    return None


def _feedback_section(feedback: str | None) -> str:
    if not feedback:
        return ""
    return f"""

---

# Feedback To Address

{feedback}

Do not relitigate accepted acceptance criteria or reviewer findings.
Make the smallest material fix that satisfies this feedback, then checkpoint again.
"""


def _join_feedback(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def _tail_gate_logs(config: ProjectConfig, entry: RunLedgerEntry) -> str | None:
    log_dir = (
        config.root
        / ".orchestrator"
        / "logs"
        / config.name
        / f"issue-{entry.issue_number}"
        / "gate"
    )
    if not log_dir.is_dir():
        return None
    parts = []
    for path in sorted(log_dir.glob("*.log")):
        parts.append(f"## {path.name}\n\n{_tail_file(path) or ''}")
    return "\n\n".join(parts) if parts else None


def _tail_file(path: Path, limit: int = 12000) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text
    return "[truncated]\n" + text[-limit:]


def _git_head(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_dirty(path: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _checkpoint_message(issue_number: int, issue_title: str) -> str:
    words = re_sub_non_words(issue_title).strip().lower()
    suffix = f": {words}" if words else ""
    return f"checkpoint: issue #{issue_number}{suffix}"[:72]


def re_sub_non_words(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", text))


def _prompt_path(config: ProjectConfig, issue_number: int) -> Path:
    return (
        config.root
        / ".orchestrator"
        / "prompts"
        / config.name
        / f"issue-{issue_number}-implementer.md"
    )


def _result_path(config: ProjectConfig, issue_number: int) -> Path:
    return (
        config.root
        / ".orchestrator"
        / "results"
        / config.name
        / f"issue-{issue_number}-implementer.json"
    )
