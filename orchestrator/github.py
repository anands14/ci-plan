"""GitHub lifecycle state helpers for the orchestrator.

Issues are the queue, labels are the public lifecycle state, and PR checks are
the gate surface.
Operational state belongs in the local run ledger, so resume reconciles GitHub
state with the ledger, worktree leases, and live worker PIDs.
These are thin wrappers over `gh`.
Writes that need the firewall (commit statuses) go through bin/post-status, not
here - the read/label path never holds the attesting token.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote


def _gh(args: list[str], repo: str) -> str:
    r = subprocess.run(
        ["gh", *args, "-R", repo], capture_output=True, text=True
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def ready_issues(repo: str) -> list[dict]:
    """Open issues labelled `ready` (eligible to claim).

    Small-wins ordering is applied by the scheduler; here we just return the
    queue.
    """
    out = _gh(
        ["issue", "list", "--label", "ready", "--state", "open",
         "--json", "number,title,body,labels", "--limit", "50"],
        repo,
    )
    return json.loads(out)


def issue_labels(repo: str, number: int) -> list[str]:
    out = _gh(["issue", "view", str(number), "--json", "labels"], repo)
    return [l["name"] for l in json.loads(out)["labels"]]


def issue(repo: str, number: int) -> dict:
    out = _gh(
        ["issue", "view", str(number), "--json", "number,title,body,labels"],
        repo,
    )
    return json.loads(out)


def set_state(repo: str, number: int, add: str, remove: list[str] | None = None) -> None:
    """Move a task along the label state machine.

    The lifecycle labels are mutually exclusive; pass the ones to clear in
    `remove`.
    """
    args = ["issue", "edit", str(number), "--add-label", add]
    for r in remove or []:
        args += ["--remove-label", r]
    _gh(args, repo)


def pr_head(repo: str, pr: int) -> str:
    out = _gh(["pr", "view", str(pr), "--json", "headRefOid"], repo)
    return str(json.loads(out)["headRefOid"])


def pr_body(repo: str, pr: int) -> str:
    out = _gh(["pr", "view", str(pr), "--json", "body"], repo)
    return str(json.loads(out).get("body") or "")


def pr_details(repo: str, pr: int) -> dict:
    out = _gh(
        [
            "pr",
            "view",
            str(pr),
            "--json",
            "number,title,body,baseRefName,headRefName,headRefOid,isDraft,labels,url",
        ],
        repo,
    )
    return json.loads(out)


def update_pr_body(repo: str, pr: int, body: str) -> None:
    _gh(["pr", "edit", str(pr), "--body", body], repo)


def update_pr_base(repo: str, pr: int, base: str) -> None:
    _gh(["pr", "edit", str(pr), "--base", base], repo)


def set_pr_labels(repo: str, pr: int, add: str, remove: list[str] | None = None) -> None:
    args = ["pr", "edit", str(pr), "--add-label", add]
    for r in remove or []:
        args += ["--remove-label", r]
    _gh(args, repo)


def pr_checks(repo: str, pr: int) -> tuple[dict[str, str], bool]:
    """All checks on a PR's head as {context: state}, plus green status.

    Mirrors what bin/merge enforces, including the orchestrator-posted
    sim-validation / review statuses, which show up here as checks.
    """
    r = subprocess.run(
        [
            "gh",
            "pr",
            "checks",
            str(pr),
            "-R",
            repo,
            "--json",
            "name,bucket,state",
        ],
        capture_output=True, text=True,
    )
    if r.returncode not in (0, 1, 8):
        raise RuntimeError(f"gh pr checks {pr} failed: {r.stderr.strip()}")
    checks: dict[str, str] = {}
    buckets: list[str] = []
    for check in json.loads(r.stdout or "[]"):
        if check.get("name"):
            checks[check["name"]] = check.get("bucket") or check.get("state") or ""
            buckets.append(checks[check["name"]])
    green = bool(checks) and all(bucket == "pass" for bucket in buckets)
    return checks, green


def approved_prs(repo: str, base: str) -> list[dict]:
    out = _gh(
        [
            "pr",
            "list",
            "--state",
            "open",
            "--base",
            base,
            "--label",
            "approved",
            "--json",
            "number,title,body,baseRefName,headRefName,headRefOid,isDraft,labels,url,updatedAt",
            "--limit",
            "50",
        ],
        repo,
    )
    return json.loads(out)


def branch_head(repo: str, branch: str) -> str:
    slug = _repo_slug(repo)
    encoded = quote(branch, safe="")
    r = subprocess.run(
        ["gh", "api", f"repos/{slug}/git/ref/heads/{encoded}", "--jq", ".object.sha"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh api branch head {branch} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def branch_checks(repo: str, branch: str) -> tuple[dict[str, str], bool]:
    sha = branch_head(repo, branch)
    out = _gh(
        [
            "run",
            "list",
            "--branch",
            branch,
            "--json",
            "name,status,conclusion,headSha,url,databaseId",
            "--limit",
            "50",
        ],
        repo,
    )
    checks: dict[str, str] = {}
    for run in json.loads(out or "[]"):
        if run.get("headSha") != sha:
            continue
        name = run.get("name")
        if not name or name in checks:
            continue
        checks[name] = _run_bucket(run)
    green = bool(checks) and all(bucket in {"pass", "skipping"} for bucket in checks.values())
    return checks, green


def find_pr(repo: str, *, base: str, head: str) -> dict | None:
    out = _gh(
        [
            "pr",
            "list",
            "--state",
            "open",
            "--base",
            base,
            "--head",
            head,
            "--json",
            "number,url,headRefOid",
            "--limit",
            "1",
        ],
        repo,
    )
    items = json.loads(out)
    return items[0] if items else None


def create_pr(repo: str, *, base: str, head: str, title: str, body_path: Path) -> dict:
    r = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "-R",
            repo,
            "--base",
            base,
            "--head",
            head,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh pr create failed: {r.stderr.strip()}")
    url = _parse_pr_url(r.stdout + "\n" + r.stderr)
    if not url:
        raise RuntimeError("gh pr create did not print a PR URL")
    return {"number": _parse_pr_number(url), "url": url}


def comment_issue(repo: str, number: int, body: str) -> None:
    _gh(["issue", "comment", str(number), "--body", body], repo)


def comment_pr(repo: str, number: int, body: str) -> None:
    _gh(["pr", "comment", str(number), "--body", body], repo)


def _run_bucket(run: dict) -> str:
    status = str(run.get("status") or "").lower()
    conclusion = str(run.get("conclusion") or "").lower()
    if status != "completed":
        return "pending"
    if conclusion == "success":
        return "pass"
    if conclusion in {"skipped", "neutral"}:
        return "skipping"
    return "fail"


def _repo_slug(repo: str) -> str:
    value = repo.strip()
    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")
    if value.startswith("https://github.com/"):
        value = value.removeprefix("https://github.com/")
    return value.removesuffix(".git").strip("/")


def _parse_pr_url(text: str) -> str | None:
    match = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/[0-9]+", text)
    return match.group(0) if match else None


def _parse_pr_number(url: str) -> int:
    match = re.search(r"/pull/([0-9]+)$", url)
    if not match:
        raise RuntimeError(f"could not parse PR number from {url}")
    return int(match.group(1))
