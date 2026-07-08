"""Safety gates shared by orchestrator commands."""

from __future__ import annotations

from pathlib import Path

from .config import ProjectConfig


ADVANCING_COMMANDS = {
    "claim-next",
    "run-implementer",
    "checkpoint",
    "gate",
    "handoff",
    "sim-validation",
    "review",
    "ensure-daily-branch",
    "integrate-pr",
    "integrate-next",
    "open-daily-pr",
    "base-refresh",
    "resume-deferred",
    "nightly-e2e",
}


def pause_path(config: ProjectConfig) -> Path:
    return config.root / ".orchestrator" / "PAUSE"


def is_paused(config: ProjectConfig) -> bool:
    return pause_path(config).exists()


def pause_message(config: ProjectConfig) -> str:
    return f"PAUSED: remove {pause_path(config)} to resume loop-advancing commands"
