"""Project config loading for the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


class ConfigError(RuntimeError):
    """Raised when a project config is missing, malformed, or unreadable."""


@dataclass(frozen=True)
class ProjectConfig:
    """Validated subset of `projects/<name>.yaml` needed by early milestones."""

    name: str
    repo: str
    default_branch: str
    local_path: Path
    agent_remote: str
    worker_home: Path
    raw: dict[str, Any]
    path: Path
    root: Path

    @property
    def repo_name(self) -> str:
        tail = self.repo.rstrip("/").split("/")[-1]
        return tail.removesuffix(".git")

    @property
    def implementer_model(self) -> str:
        return _agent_string(self.raw, "implementer", "model", "gpt-5.5")

    @property
    def implementer_effort(self) -> str:
        return _agent_string(self.raw, "implementer", "effort", "high")

    @property
    def reviewer_model(self) -> str:
        return _agent_string(self.raw, "reviewer", "model", "claude-opus-4-8")

    @property
    def reviewer_effort(self) -> str:
        return _agent_string(self.raw, "reviewer", "effort", "max")

    @property
    def reviewer_fallback_model(self) -> str:
        return _agent_string(self.raw, "reviewer", "fallback_model", "gpt-5.5")

    @property
    def reviewer_fallback_effort(self) -> str:
        return _agent_string(self.raw, "reviewer", "fallback_effort", "xhigh")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_project_config(project: str, root: Path | None = None) -> ProjectConfig:
    root = (root or repo_root()).resolve()
    path = root / "projects" / f"{project}.yaml"
    if not path.is_file():
        raise ConfigError(f"project config not found: {path}")

    raw = _load_yaml(path)
    if not isinstance(raw, dict):
        raise ConfigError(f"project config must be a mapping: {path}")

    project_section = _mapping(raw, "project")
    worker_section = _mapping(raw, "worker_environment")

    name = _string(project_section, "name")
    if name != project:
        raise ConfigError(
            f"project.name is {name!r}, expected {project!r} for {path.name}"
        )

    local_path = _resolve_path(_string(project_section, "local_path"), root)
    worker_home = _resolve_path(_string(worker_section, "home"), root)

    return ProjectConfig(
        name=name,
        repo=_string(project_section, "repo"),
        default_branch=_string(project_section, "default_branch"),
        local_path=local_path,
        agent_remote=_string(project_section, "agent_remote"),
        worker_home=worker_home,
        raw=raw,
        path=path,
        root=root,
    )


def _load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _load_yaml_via_ruby(path)

    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as exc:  # pragma: no cover - dependency-specific shape.
        raise ConfigError(f"failed to parse YAML {path}: {exc}") from exc


def _load_yaml_via_ruby(path: Path) -> Any:
    ruby = shutil.which("ruby")
    if not ruby:
        raise ConfigError(
            "YAML support requires PyYAML or Ruby's built-in YAML parser"
        )
    script = 'require "yaml"; require "json"; puts YAML.load_file(ARGV[0]).to_json'
    result = subprocess.run(
        [ruby, "-e", script, str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ConfigError(
            f"failed to parse YAML {path}: {result.stderr.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ruby YAML parser returned invalid JSON for {path}") from exc


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"missing or invalid mapping: {key}")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"missing or invalid string: {key}")
    return value


def _agent_string(
    raw: dict[str, Any],
    role: str,
    key: str,
    default: str,
) -> str:
    agents = raw.get("agents")
    if not isinstance(agents, dict):
        return default
    config = agents.get(role)
    if not isinstance(config, dict):
        return default
    value = config.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _resolve_path(value: str, root: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (root / expanded).resolve()


def env_token_prefix(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")
