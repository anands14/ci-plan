"""Compact agent context and cross-agent handoff memory."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import ProjectConfig


DEFAULT_HANDOFF_LOG = "AGENT_HANDOFF.md"
DEFAULT_MAP_PATHS = (
    "AGENT_CONTEXT.md",
    "packages/tovi_app/lib/src/tasks/AGENT_CONTEXT.md",
    "packages/tovi_core/lib/src/tasks/AGENT_CONTEXT.md",
)
HANDOFF_EXCERPT_LIMIT = 4000
HANDOFF_ITEM_LIMIT = 12

PROCESS_INVARIANTS = (
    "human merges default branch",
    "criteria -> tests; never weaken/skip/delete/ignore tests",
    "scope manifest is hard; escalate before extra files",
    "protected paths need explicit issue risk + human approval",
    "user-facing change needs declared e2e or e2e-exempt reason",
    "code/tests > notes; handoff is pointer, not truth",
)

REUSABLE_TECHNIQUES = (
    "rg -> symbol -> narrow slice; no cold full-file reads",
    "maps before directories/hot files",
    "ListView: scrollUntilVisible may need cache-extent movement",
    "files-truth: assert vault/durable store, not only UI/return",
)

GOTCHAS = (
    "use project tool prefix, usually fvm",
    "macOS sim flaky foreground -> configured iOS fallback; record it",
    "shared id/clock fixtures can make tests order-sensitive",
)


def build_compact_brief(config: ProjectConfig) -> str:
    """Return the stable, issue-independent implementer prompt prefix."""
    return "\n".join(
        [
            "# Implementer Brief",
            "",
            "tight loop: criteria -> red -> scoped fix -> scoped prove -> JSON.",
            "load: issue/scope + handoff tail + maps; rg -> narrow slices. Do not read whole docs or hot files.",
            "",
            "## Hard Rules",
            _bullets(PROCESS_INVARIANTS),
            "",
            "## Gate",
            _gate_rules(config),
            "",
            "## Tactics",
            _bullets(_configured_list(config, "techniques", REUSABLE_TECHNIQUES)),
            "",
            "## Gotchas",
            _bullets(_configured_list(config, "gotchas", GOTCHAS)),
            "",
            "## Maps",
            _bullets(_map_paths(config)),
            "",
            "## Scoped Tests",
            _scoped_test_guidance(config),
            "",
            "## JSON",
            "return keys: success, summary, key_changes, tests_added, tests_run, touched_files, new_apis, decisions, gotchas, deviations, uncertainties, escalation.",
        ]
    )


def handoff_log_relative_path(config: ProjectConfig) -> str:
    context = config.raw.get("context", {})
    if isinstance(context, dict):
        value = context.get("handoff_log")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_HANDOFF_LOG


def read_handoff_excerpt(
    config: ProjectConfig,
    worktree: Path,
    limit: int = HANDOFF_EXCERPT_LIMIT,
) -> str:
    path = worktree / handoff_log_relative_path(config)
    if not path.is_file():
        return "_No handoff entries found yet._"
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return "_Handoff log exists but is empty._"
    if len(text) <= limit:
        return text
    return "[older entries truncated]\n" + text[-limit:]


def append_handoff_entry(
    config: ProjectConfig,
    worktree: Path,
    issue: dict[str, Any],
    *,
    final_text: str,
    summary: str,
    head_after: str | None,
) -> Path:
    """Append the implementer result to the target repo handoff log."""
    path = worktree / handoff_log_relative_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    parsed = _maybe_json(final_text)
    issue_number = issue.get("number")
    issue_title = issue.get("title") or ""
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = [
        "",
        f"## {timestamp} issue #{issue_number}: {issue_title}",
        "",
        f"- h: {head_after or 'unknown'}",
        f"- s: {_one_line(_json_string(parsed, 'summary') or summary)}",
    ]
    for key, label in (
        ("key_changes", "chg"),
        ("tests_added", "test+"),
        ("tests_run", "run"),
        ("touched_files", "files"),
        ("new_apis", "api"),
        ("decisions", "dec"),
        ("gotchas", "got"),
        ("deviations", "dev"),
        ("uncertainties", "unk"),
    ):
        values = _json_items(parsed, key)
        if values:
            entry.append(f"- {label}: " + "; ".join(_compact_items(values)))
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")
    return path


def _gate_rules(config: ProjectConfig) -> str:
    gate = config.raw.get("gate", {})
    commands = gate.get("commands", {}) if isinstance(gate, dict) else {}
    lines = [
        "- inner loop: scoped tests only",
        "- before handoff: orchestrator runs full gate once",
        "- test-discipline red: add integration_test or e2e-exempt reason",
    ]
    if isinstance(commands, dict) and commands:
        for name in ("format", "lint", "test"):
            command = commands.get(name)
            if command:
                lines.append(f"- gate.{name}: `{command}`")
    return "\n".join(lines)


def _scoped_test_guidance(config: ProjectConfig) -> str:
    context = config.raw.get("context", {})
    scoped = context.get("scoped_tests") if isinstance(context, dict) else None
    if isinstance(scoped, list) and scoped:
        return _bullets(_context_item(item) for item in scoped)
    return _bullets(
        (
            "run smallest criterion test before wider work",
            "core: from package, `fvm dart test test/tasks/<file>_test.dart`",
            "Flutter UI: focused widget test, use `--plain-name` when possible",
            "record commands in `tests_run`",
        )
    )


def _map_paths(config: ProjectConfig) -> tuple[str, ...]:
    context = config.raw.get("context", {})
    configured = context.get("map_paths") if isinstance(context, dict) else None
    if isinstance(configured, list) and configured:
        return tuple(str(item) for item in configured if str(item).strip())
    return DEFAULT_MAP_PATHS


def _configured_list(config: ProjectConfig, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    context = config.raw.get("context", {})
    configured = context.get(key) if isinstance(context, dict) else None
    if isinstance(configured, list) and configured:
        return tuple(item for item in (_context_item(item) for item in configured) if item.strip())
    return fallback


def _context_item(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _bullets(items: Any) -> str:
    return "\n".join(f"- {item}" for item in items)


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _json_string(value: Any, key: str) -> str | None:
    if isinstance(value, dict) and isinstance(value.get(key), str):
        return value[key]
    return None


def _json_items(value: Any, key: str) -> list[str]:
    if not isinstance(value, dict):
        return []
    raw = value.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        items = []
        for item in raw:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict):
                items.append(", ".join(f"{k}={v}" for k, v in item.items()))
            else:
                items.append(str(item))
        return items
    if isinstance(raw, dict):
        return [", ".join(f"{k}={v}" for k, v in raw.items())]
    return [str(raw)]


def _one_line(value: str) -> str:
    return " ".join(value.split())[:300]


def _compact_items(values: list[str]) -> list[str]:
    items = [_one_line(value) for value in values[:HANDOFF_ITEM_LIMIT]]
    if len(values) > HANDOFF_ITEM_LIMIT:
        items.append(f"+{len(values) - HANDOFF_ITEM_LIMIT} more")
    return items
