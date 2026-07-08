"""Wrappers for deterministic local tools used by the orchestrator."""

from __future__ import annotations

from pathlib import Path
import subprocess

from .config import ProjectConfig


class ToolError(RuntimeError):
    """Raised when a required local tool command fails."""


def acquire_treehouse_lease(config: ProjectConfig, issue_number: int) -> Path:
    holder = f"{config.name}-issue-{issue_number}"
    result = subprocess.run(
        ["treehouse", "get", "--lease", "--lease-holder", holder],
        cwd=config.local_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ToolError(f"treehouse lease failed: {detail}")

    path_text = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    lease_path = Path(path_text)
    if not lease_path.is_absolute():
        raise ToolError(f"treehouse returned a non-absolute lease path: {path_text!r}")
    return lease_path


def release_treehouse_lease(path: Path) -> None:
    result = subprocess.run(
        ["treehouse", "return", str(path), "--force"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ToolError(f"treehouse return failed for {path}: {detail}")
