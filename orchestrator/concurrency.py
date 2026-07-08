"""Staged concurrency guardrails."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .config import ProjectConfig


STAGES = ("watched-worker", "two-plus-sim", "half-day-unattended", "scale-up")


@dataclass(frozen=True)
class ConcurrencyPolicy:
    stage: str
    implementers: int
    sim_validations: int
    reviewers: int
    max_implementers: int


def set_concurrency_stage(config: ProjectConfig, stage: str) -> Path:
    if stage not in STAGES:
        raise RuntimeError(f"unknown concurrency stage: {stage}")
    path = _stage_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_concurrency_policy(config: ProjectConfig) -> ConcurrencyPolicy:
    stage = "watched-worker"
    path = _stage_path(config)
    if path.is_file():
        stage = str(json.loads(path.read_text(encoding="utf-8")).get("stage") or stage)
    if stage not in STAGES:
        raise RuntimeError(f"unknown concurrency stage in {path}: {stage}")

    raw = config.raw.get("budget", {}).get("concurrency", {})
    start = int(raw.get("implementers_start", 2))
    max_implementers = int(raw.get("implementers_max", start))
    reviewers = int(raw.get("reviewers", 1))
    sim = int(raw.get("sim_validations", 1))

    if stage == "watched-worker":
        return ConcurrencyPolicy(stage, 1, 0, reviewers, max_implementers)
    if stage in ("two-plus-sim", "half-day-unattended"):
        return ConcurrencyPolicy(stage, min(2, max_implementers), min(1, sim), reviewers, max_implementers)
    return ConcurrencyPolicy(stage, max_implementers, sim, reviewers, max_implementers)


def _stage_path(config: ProjectConfig) -> Path:
    return config.root / ".orchestrator" / "concurrency" / f"{config.name}.json"
