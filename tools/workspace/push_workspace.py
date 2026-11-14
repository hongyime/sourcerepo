#!/usr/bin/env python
"""Report and optionally push clean, ahead-only workspace repos.

This tool deliberately does not auto-commit. It also does not use --no-verify,
so the global SHELL pre-commit/push hooks remain in force.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


EXCLUDED_DIRS = {
    ".codeflicker",
    ".git",
    ".kiro",
    ".molt",
    ".omo",
    ".pytest_cache",
    ".shell",
    ".vscode",
    "_molt",
    "_shell",
    "Git",
    "Python",
    "Readme",
}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, exc.stdout or "", f"timeout after {timeout}s")


def parse_full_name(remote_url: str) -> str | None:
    match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", remote_url.strip())
    if not match:
        return None
    owner, repo = match.groups()
    return f"{owner}/{repo.removesuffix('.git')}"


def normalize_path(path: Path) -> Path:
    return Path(str(path).strip().strip('"')).resolve()


def authenticated_user() -> str:
    proc = run(["gh", "api", "user", "--jq", ".login"], timeout=30)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("gh authentication is required to determine the personal owner")
    return proc.stdout.strip()


def iter_git_repos(workspace: Path) -> list[Path]:
    repos: list[Path] = []
    for first in workspace.iterdir():
        if not first.is_dir() or first.name in EXCLUDED_DIRS:
            continue
        if (first / ".git").exists():
            repos.append(first)
            continue
        repos.extend(p for p in first.iterdir() if p.is_dir() and (p / ".git").exists())
    return sorted(repos, key=lambda p: str(p).lower())


def selected(repo_dir: Path, full_name: str | None, filters: set[str]) -> bool:
    if not filters:
        return True
    names = {repo_dir.name.lower()}
    if full_name:
        names.add(full_name.lower())
        names.add(full_name.rsplit("/", 1)[-1].lower())
    return bool(names & filters)


def selected_by_folder(repo_dir: Path, filters: set[str]) -> bool:
    if not filters:
        return True
    folder = repo_dir.name.lower()
    return any(filter_value == folder or filter_value.endswith(f"/{folder}") for filter_value in filters)


def status(repo_dir: Path, personal_owner: str, command_timeout: int) -> tuple[str, str | None]:
    remote = run(["git", "remote", "get-url", "origin"], cwd=repo_dir, timeout=command_timeout)
    full_name = parse_full_name(remote.stdout) if remote.returncode == 0 else None
    if not full_name:
        return "skip non-github", None
    owner = full_name.split("/", 1)[0]
    if owner not in {"hongyime", personal_owner}:
        return "skip external", full_name

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, timeout=command_timeout)
    if branch.returncode != 0 or branch.stdout.strip() == "HEAD":
        return "skip detached", full_name

    dirty = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_dir, timeout=command_timeout)
    if dirty.returncode != 0:
        if dirty.returncode == 124:
            return f"skip status timeout {command_timeout}s", full_name
        return "skip status failed", full_name
    if dirty.stdout.strip():
        return "dirty - commit manually", full_name

    branch_name = branch.stdout.strip()
    upstream = run(["git", "rev-parse", "--abbrev-ref", "@{u}"], cwd=repo_dir, timeout=command_timeout)
    if upstream.returncode != 0:
        fallback_ref = f"origin/{branch_name}"
        fallback = run(["git", "rev-parse", "--verify", fallback_ref], cwd=repo_dir, timeout=command_timeout)
        if fallback.returncode != 0:
            return f"skip no origin/{branch_name}", full_name
        compare_ref = fallback_ref
    else:
        compare_ref = upstream.stdout.strip()

    ahead = run(["git", "rev-list", "--count", f"{compare_ref}..HEAD"], cwd=repo_dir, timeout=command_timeout)
    behind = run(["git", "rev-list", "--count", f"HEAD..{compare_ref}"], cwd=repo_dir, timeout=command_timeout)
    if ahead.returncode != 0 or behind.returncode != 0:
        if ahead.returncode == 124 or behind.returncode == 124:
            return f"skip rev-list timeout {command_timeout}s", full_name
        return "skip rev-list failed", full_name
    ahead_n = int((ahead.stdout or "0").strip() or "0")
    behind_n = int((behind.stdout or "0").strip() or "0")
    if behind_n:
        return f"skip behind {behind_n}", full_name
    if ahead_n:
        return f"push {ahead_n}", full_name
    return "clean", full_name


def push_current_branch(repo_dir: Path, command_timeout: int) -> subprocess.CompletedProcess[str]:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, timeout=command_timeout)
    if branch.returncode != 0 or branch.stdout.strip() == "HEAD":
        return subprocess.CompletedProcess(["git", "push"], 1, "", "not on a branch")
    branch_name = branch.stdout.strip()
    return run(["git", "push", "-u", "origin", f"HEAD:{branch_name}"], cwd=repo_dir, timeout=300)


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Report/push clean ahead-only owned repos.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--push", action="store_true", help="push clean ahead-only repos")
    parser.add_argument("--command-timeout", type=int, default=30, help="per-repo git command timeout in seconds")
    parser.add_argument("--personal-owner", help="authenticated personal GitHub owner; defaults to gh api user")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="limit to a folder name, repo name, or full repo name; may be repeated",
    )
    args = parser.parse_args()

    workspace = normalize_path(args.workspace)
    personal_owner = args.personal_owner.strip() if args.personal_owner else authenticated_user()
    filters = {item.strip().lower() for raw in args.only for item in raw.split(",") if item.strip()}
    pushed = 0
    print(f"Workspace: {workspace}")
    print("No commits are created by this tool.")
    if filters:
        print(f"Filter: {', '.join(sorted(filters))}")
    print("-" * 72)
    for repo_dir in iter_git_repos(workspace):
        if not selected_by_folder(repo_dir, filters):
            continue
        state, full_name = status(repo_dir, personal_owner, args.command_timeout)
        if not selected(repo_dir, full_name, filters):
            continue
        label = full_name or repo_dir.name
        print(f"[{state.upper():22}] {label} -> {repo_dir}")
        if args.push and state.startswith("push "):
            proc = push_current_branch(repo_dir, args.command_timeout)
            if proc.returncode == 0:
                pushed += 1
                print(f"  pushed {label}")
            else:
                print(f"  push failed: {(proc.stderr or proc.stdout).strip()[:160]}")
    print("-" * 72)
    print(f"Pushed: {pushed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
