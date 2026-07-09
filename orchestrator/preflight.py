"""M0 preflight checks for unattended orchestrator readiness."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Iterable

from .config import ProjectConfig, env_token_prefix


REQUIRED_TOOLS = ("treehouse", "no-mistakes", "gh", "codex", "claude")
HUMAN_GITHUB_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT")
ORIGIN_BLOCKED_PATTERNS = (
    "authentication failed",
    "could not read username",
    "terminal prompts disabled",
    "permission denied",
    "write access to repository not granted",
    "403",
    "401",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def build_worker_env(
    worker_home: Path,
    base: dict[str, str] | None = None,
    *,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the env used for worker safety probes.

    Keep only non-secret process basics, force the dedicated HOME, and disable
    interactive credential prompts so push probes cannot borrow human auth.
    `extra` carries the narrow set of secrets a specific tool invocation
    needs (e.g. a headless CLI's own long-lived token) - never pulled from
    ambient `os.environ`, only from a caller that read it from `.env` itself.
    """

    base = dict(base or os.environ)
    env: dict[str, str] = {}
    for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "SHELL", "TERM", "TMPDIR"):
        if key in base:
            env[key] = base[key]
    env["HOME"] = str(worker_home)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    if extra:
        env.update(extra)
    return env


def read_dotenv(root: Path) -> dict[str, str]:
    """Parse the repo-root `.env` the same simple way `bin/post-status` sources
    it: flat `KEY=value` lines, blank/comment lines ignored, no quoting or
    escaping rules. Missing file returns an empty mapping.
    """

    path = root / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def orchestrator_token_names(config: ProjectConfig) -> set[str]:
    prefixes = {
        "ORCHESTRATOR",
        env_token_prefix(config.name),
        env_token_prefix(config.repo_name),
    }
    names = {"ORCHESTRATOR_GH_TOKEN", "GH_ORCHESTRATOR_TOKEN"}
    names.update(f"{prefix}_ORCHESTRATOR_GH_TOKEN" for prefix in prefixes if prefix)
    return names


def run_preflight(config: ProjectConfig) -> list[CheckResult]:
    runner = _Preflight(config)
    return runner.run()


def format_results(results: Iterable[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"{result.status:4} {result.name} - {result.detail}")
    return "\n".join(lines)


def failed(results: Iterable[CheckResult]) -> bool:
    return any(result.status == "FAIL" for result in results)


def origin_failure_proves_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in ORIGIN_BLOCKED_PATTERNS)


class _Preflight:
    def __init__(self, config: ProjectConfig):
        self.config = config
        self.worker_env = build_worker_env(config.worker_home)

    def run(self) -> list[CheckResult]:
        results = [
            self._pass(
                "load project config",
                f"{self.config.path} for {self.config.repo}",
            ),
            self._target_repo(),
            *self._tools(),
            self._worker_home(),
            self._orchestrator_token_hidden(),
            self._human_gh_auth_hidden(),
            self._origin_push_blocked(),
            self._agent_remote_push_allowed(),
        ]
        return results

    def _target_repo(self) -> CheckResult:
        path = self.config.local_path
        if not path.exists():
            return self._fail("target repo exists locally", f"{path} does not exist")
        result = self._run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"])
        if result.returncode != 0 or result.stdout.strip() != "true":
            return self._fail(
                "target repo exists locally",
                f"{path} is not a git worktree",
            )
        return self._pass("target repo exists locally", str(path))

    def _tools(self) -> list[CheckResult]:
        results = []
        for tool in REQUIRED_TOOLS:
            found = shutil.which(tool)
            if found:
                results.append(self._pass(f"{tool} discoverable", found))
            else:
                results.append(self._fail(f"{tool} discoverable", "not found on PATH"))
        return results

    def _worker_home(self) -> CheckResult:
        home = self.config.worker_home
        if not home.is_dir():
            return self._fail("worker HOME is dedicated", f"{home} is not a directory")
        if self.worker_env.get("HOME") != str(home):
            return self._fail(
                "worker HOME is dedicated",
                f"worker env HOME={self.worker_env.get('HOME')!r}",
            )
        return self._pass("worker HOME is dedicated", str(home))

    def _orchestrator_token_hidden(self) -> CheckResult:
        names = orchestrator_token_names(self.config)
        leaked = sorted(name for name in names if name in self.worker_env)
        leaked.extend(
            sorted(
                key
                for key in self.worker_env
                if "ORCHESTRATOR" in key and "TOKEN" in key and key not in leaked
            )
        )
        if leaked:
            return self._fail(
                "worker cannot see orchestrator status token",
                f"worker env exposes {', '.join(leaked)}",
            )
        return self._pass(
            "worker cannot see orchestrator status token",
            "no orchestrator token env vars in worker env",
        )

    def _human_gh_auth_hidden(self) -> CheckResult:
        leaked_env = [name for name in HUMAN_GITHUB_ENV if name in self.worker_env]
        if leaked_env:
            return self._fail(
                "worker cannot see human GitHub auth",
                f"worker env exposes {', '.join(leaked_env)}",
            )
        gh = shutil.which("gh")
        if not gh:
            return self._fail(
                "worker cannot see human GitHub auth",
                "gh unavailable, cannot inspect worker auth",
            )
        result = self._run([gh, "auth", "status"], env=self.worker_env, timeout=15)
        if result.returncode == 0:
            return self._fail(
                "worker cannot see human GitHub auth",
                "gh auth status succeeds under worker HOME",
            )
        return self._pass(
            "worker cannot see human GitHub auth",
            "no gh auth under worker HOME and no GitHub token env vars",
        )

    def _origin_push_blocked(self) -> CheckResult:
        result = self._push_probe("origin")
        if result.returncode == 0:
            return self._fail(
                "worker cannot push directly to origin",
                "git push --dry-run origin succeeded",
            )
        output = self._combined_output(result)
        if not origin_failure_proves_blocked(output):
            return self._fail(
                "worker cannot push directly to origin",
                f"origin push probe failed for a non-auth reason: {self._short_text(output)}",
            )
        return self._pass(
            "worker cannot push directly to origin",
            self._short_text(output),
        )

    def _agent_remote_push_allowed(self) -> CheckResult:
        remote = self.config.agent_remote
        remote_check = self._run(
            ["git", "-C", str(self.config.local_path), "remote", "get-url", "--push", remote],
            env=self.worker_env,
        )
        if remote_check.returncode != 0:
            return self._fail(
                "agent remote accepts branch push",
                f"remote {remote!r} is not configured",
            )
        result = self._push_probe(remote)
        if result.returncode == 0:
            return self._pass(
                "agent remote accepts branch push",
                f"dry-run push to {remote} succeeded",
            )
        return self._fail("agent remote accepts branch push", self._short_failure(result))

    def _push_probe(self, remote: str) -> subprocess.CompletedProcess[str]:
        branch = f"refs/heads/orchestrator-preflight-{os.getpid()}"
        return self._run(
            [
                "git",
                "-C",
                str(self.config.local_path),
                "push",
                "--dry-run",
                remote,
                f"HEAD:{branch}",
            ],
            env=self.worker_env,
            timeout=30,
        )

    def _run(
        self,
        args: list[str],
        env: dict[str, str] | None = None,
        timeout: int = 10,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stderr = "\n".join(
                part
                for part in (
                    stderr,
                    f"timed out after {timeout}s: {' '.join(args)}",
                )
                if part
            )
            return subprocess.CompletedProcess(args, 124, stdout, stderr)

    def _short_failure(self, result: subprocess.CompletedProcess[str]) -> str:
        text = self._combined_output(result)
        if not text:
            return f"command exited {result.returncode}"
        return self._short_text(text)

    def _combined_output(self, result: subprocess.CompletedProcess[str]) -> str:
        return "\n".join(part for part in (result.stderr, result.stdout) if part).strip()

    def _short_text(self, text: str) -> str:
        if not text:
            return "no command output"
        return text.splitlines()[-1]

    def _pass(self, name: str, detail: str) -> CheckResult:
        return CheckResult(name, "PASS", detail)

    def _fail(self, name: str, detail: str) -> CheckResult:
        return CheckResult(name, "FAIL", detail)
