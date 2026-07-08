"""Context-efficiency measurements for orchestrated runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .config import ProjectConfig


DEFAULT_HOT_FILES = (
    "packages/tovi_app/lib/src/tasks/today_page.dart",
    "packages/tovi_core/lib/src/tasks/task_commands.dart",
)
RE_DERIVED_PATTERNS = {
    "test-discipline": re.compile(r"test-discipline|integration_test", re.I),
    "listview-scroll": re.compile(r"scrollUntilVisible|cache extent|cacheExtent", re.I),
    "current-sprint": re.compile(r"current sprint", re.I),
}
FULL_GATE_PATTERN = re.compile(r"melos run test:fast|test:fast|gate passed|gate failed", re.I)


@dataclass(frozen=True)
class ContextRunReport:
    prompt_bytes_by_issue: dict[int, int]
    output_tokens_by_issue: dict[int, int]
    hot_file_mentions: dict[str, int]
    rederived_mentions: dict[str, int]
    full_gate_mentions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_bytes_by_issue": self.prompt_bytes_by_issue,
            "output_tokens_by_issue": self.output_tokens_by_issue,
            "hot_file_mentions": self.hot_file_mentions,
            "rederived_mentions": self.rederived_mentions,
            "full_gate_mentions": self.full_gate_mentions,
        }


def analyze_context_run(
    config: ProjectConfig,
    *,
    hot_files: tuple[str, ...] = DEFAULT_HOT_FILES,
) -> ContextRunReport:
    root = config.root / ".orchestrator"
    texts = _read_texts(root / "logs" / config.name)
    texts.extend(_read_texts(root / "results" / config.name))

    hot_file_mentions = {name: 0 for name in hot_files}
    rederived_mentions = {name: 0 for name in RE_DERIVED_PATTERNS}
    full_gate_mentions = 0
    output_tokens_by_issue: dict[int, int] = {}

    for path, text in texts:
        for hot_file in hot_files:
            hot_file_mentions[hot_file] += text.count(hot_file)
            hot_file_mentions[hot_file] += text.count(Path(hot_file).name)
        for name, pattern in RE_DERIVED_PATTERNS.items():
            rederived_mentions[name] += len(pattern.findall(text))
        full_gate_mentions += len(FULL_GATE_PATTERN.findall(text))
        issue = _issue_number(path)
        if issue is not None:
            output_tokens_by_issue[issue] = output_tokens_by_issue.get(issue, 0) + _token_count(text)

    prompt_bytes_by_issue = {}
    prompt_dir = root / "prompts" / config.name
    if prompt_dir.is_dir():
        for path in prompt_dir.glob("issue-*-implementer.md"):
            issue = _issue_number(path)
            if issue is not None:
                prompt_bytes_by_issue[issue] = path.stat().st_size

    return ContextRunReport(
        prompt_bytes_by_issue=prompt_bytes_by_issue,
        output_tokens_by_issue=output_tokens_by_issue,
        hot_file_mentions=hot_file_mentions,
        rederived_mentions=rederived_mentions,
        full_gate_mentions=full_gate_mentions,
    )


def _read_texts(root: Path) -> list[tuple[Path, str]]:
    if not root.is_dir():
        return []
    texts = []
    for path in root.rglob("*"):
        if path.is_file():
            texts.append((path, path.read_text(encoding="utf-8", errors="replace")))
    return texts


def _issue_number(path: Path) -> int | None:
    match = re.search(r"issue-(\d+)", str(path))
    return int(match.group(1)) if match else None


def _token_count(text: str) -> int:
    total = 0
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += _sum_token_fields(event)
    return total


def _sum_token_fields(value: Any) -> int:
    if isinstance(value, dict):
        total = 0
        for key, child in value.items():
            if key in {"output_tokens", "completion_tokens"} and isinstance(child, int):
                total += child
            else:
                total += _sum_token_fields(child)
        return total
    if isinstance(value, list):
        return sum(_sum_token_fields(child) for child in value)
    return 0
