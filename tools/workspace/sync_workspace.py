#!/usr/bin/env python
"""Synchronise the local repo workspace without deleting anything.

Scope:
- hongyime org repos
- repos owned by the authenticated GitHub user
- repos where the authenticated user is an explicit collaborator

This replaces the old root sync script's dangerous pruning behavior. Missing
repos are cloned. Existing repos are fetched and fast-forwarded only when their
working tree is clean and the current branch has a matching remote branch.
"""

from __future__ import annotations

import argparse
import json
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
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Portable Git's launcher has a child that inherits these pipes. Killing
        # only the launcher leaves communicate() waiting for that child forever.
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            proc.kill()
        try:
            stdout, _stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(cmd, 124, stdout, f"timeout after {timeout}s")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def gh_json(args: list[str]) -> object:
    proc = run(["gh", *args], timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return json.loads(proc.stdout or "null")


def normalize_path(path: Path) -> Path:
    return Path(str(path).strip().strip('"')).resolve()


_AUTHENTICATED_USER: str | None = None


def authenticated_user() -> str:
    global _AUTHENTICATED_USER
    if _AUTHENTICATED_USER:
        return _AUTHENTICATED_USER
    data = gh_json(["api", "user"])
    _AUTHENTICATED_USER = str(data["login"])
    return _AUTHENTICATED_USER


def paginated(endpoint: str) -> list[dict]:
    proc = run(["gh", "api", "--paginate", endpoint], timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    items: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, list):
            items.extend(payload)
        else:
            items.append(payload)
    return items


def remote_repos() -> list[dict]:
    user = authenticated_user()
    repos: dict[str, dict] = {}

    for repo in paginated("orgs/hongyime/repos?per_page=100&type=all"):
        if not repo.get("fork") and not repo.get("disabled"):
            repos[repo["full_name"]] = repo

    for repo in paginated("user/repos?per_page=100&affiliation=owner,collaborator"):
        owner = repo.get("owner", {})
        owner_login = owner.get("login")
        owner_type = owner.get("type")
        if repo.get("fork") or repo.get("disabled"):
            continue
        if owner_login in {"hongyime", user}:
            repos[repo["full_name"]] = repo
            continue
        if owner_type == "User":
            repos[repo["full_name"]] = repo

    return sorted(repos.values(), key=lambda item: item["full_name"].lower())


def parse_full_name(remote_url: str) -> str | None:
    match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", remote_url.strip())
    if not match:
        return None
    owner, repo = match.groups()
    return f"{owner}/{repo.removesuffix('.git')}"


def local_repos(workspace: Path, command_timeout: int) -> dict[str, Path]:
    found: dict[str, Path] = {}
    metadata_timeout = max(command_timeout, 30)
    candidates = [p for p in workspace.iterdir() if p.is_dir() and p.name not in EXCLUDED_DIRS]
    for first in candidates:
        repo_dirs = [first] if (first / ".git").exists() else []
        if not repo_dirs:
            repo_dirs.extend(p for p in first.iterdir() if p.is_dir() and (p / ".git").exists())
        for repo_dir in repo_dirs:
            proc = run(["git", "remote", "get-url", "origin"], cwd=repo_dir, timeout=metadata_timeout)
            if proc.returncode != 0:
                continue
            full_name = parse_full_name(proc.stdout)
            if full_name and full_name not in found:
                found[full_name] = repo_dir
    return found


def clone_path(workspace: Path, full_name: str) -> Path:
    owner, repo = full_name.split("/", 1)
    if owner in {"hongyime", authenticated_user()}:
        return workspace / repo
    return workspace / owner / repo


def selected(full_name: str, filters: set[str]) -> bool:
    if not filters:
        return True
    lowered = full_name.lower()
    repo = lowered.rsplit("/", 1)[-1]
    return lowered in filters or repo in filters


def command_failure(operation: str, proc: subprocess.CompletedProcess[str]) -> str:
    # Report useful failure categories without printing credential-bearing URLs.
    reason = "timed out" if proc.returncode == 124 else f"exit {proc.returncode}"
    return f"{operation} failed ({reason})"


def is_clean(repo_dir: Path, command_timeout: int) -> bool:
    proc = run(["git", "status", "--porcelain"], cwd=repo_dir, timeout=command_timeout)
    if proc.returncode != 0:
        raise RuntimeError(command_failure("status check", proc))
    return not proc.stdout.strip()


def is_empty_dir(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False


def existing_target_full_name(path: Path, command_timeout: int) -> str | None:
    if not (path / ".git").exists():
        return None
    proc = run(["git", "remote", "get-url", "origin"], cwd=path, timeout=max(command_timeout, 30))
    if proc.returncode != 0:
        return None
    return parse_full_name(proc.stdout)


def has_tracked_changes(repo_dir: Path, command_timeout: int) -> bool:
    proc = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo_dir, timeout=command_timeout)
    return proc.returncode != 0 or bool(proc.stdout.strip())


def current_branch(repo_dir: Path, command_timeout: int) -> str | None:
    proc = run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], cwd=repo_dir, timeout=command_timeout)
    if proc.returncode == 1:
        return None
    if proc.returncode != 0:
        raise RuntimeError(command_failure("branch check", proc))
    branch = proc.stdout.strip()
    return branch or None


def count_revs(repo_dir: Path, revspec: str, command_timeout: int) -> int | None:
    proc = run(["git", "rev-list", "--count", revspec], cwd=repo_dir, timeout=max(command_timeout, 30))
    if proc.returncode != 0:
        return None
    try:
        return int((proc.stdout or "0").strip() or "0")
    except ValueError:
        return None


def ask_choice(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    print(prompt)
    lookup: dict[str, str] = {}
    for index, (key, description) in enumerate(options, 1):
        marker = " default" if key == default else ""
        print(f"  {index}. {key} - {description}{marker}")
        lookup[str(index)] = key
        lookup[key] = key
    response = input("Choose number or word: ").strip().lower()
    return lookup.get(response, default)


def merge_origin(repo_dir: Path, branch: str) -> str:
    merge = run(["git", "merge", "--no-edit", f"origin/{branch}"], cwd=repo_dir, timeout=300)
    if merge.returncode == 0:
        return "merged"

    print((merge.stderr or merge.stdout).strip()[:400])
    choice = ask_choice(
        "Merge conflicted.",
        [
            ("abort", "stop this merge and leave the repo unchanged"),
            ("local", "resolve conflicts by keeping local file contents"),
            ("github", "resolve conflicts by keeping GitHub file contents"),
        ],
        "abort",
    )
    if choice == "local":
        run(["git", "checkout", "--ours", "."], cwd=repo_dir, timeout=120)
        run(["git", "add", "-A"], cwd=repo_dir, timeout=120)
        commit = run(["git", "commit", "--no-edit"], cwd=repo_dir, timeout=120)
        return "merged keep-local" if commit.returncode == 0 else "merge keep-local failed"
    if choice == "github":
        run(["git", "checkout", "--theirs", "."], cwd=repo_dir, timeout=120)
        run(["git", "add", "-A"], cwd=repo_dir, timeout=120)
        commit = run(["git", "commit", "--no-edit"], cwd=repo_dir, timeout=120)
        return "merged keep-github" if commit.returncode == 0 else "merge keep-github failed"

    run(["git", "merge", "--abort"], cwd=repo_dir, timeout=120)
    return "skip merge conflict"


def interactive_dirty_sync(repo_dir: Path, branch: str, command_timeout: int) -> str:
    choice = ask_choice(
        "Dirty repo: local file changes are present.",
        [
            ("skip", "do nothing to this repo"),
            ("stash", "stash local changes, update, then re-apply the stash"),
            ("local", "commit local tracked changes, then try to merge GitHub"),
            ("github", "discard local changes and match GitHub after an extra confirmation"),
        ],
        "skip",
    )
    if choice == "skip":
        return "skip dirty"
    if choice == "github":
        confirm = ask_choice(
            "Confirm destructive reset: this discards local tracked changes and untracked files.",
            [
                ("skip", "cancel and leave this repo unchanged"),
                ("github", "discard local files and match GitHub"),
            ],
            "skip",
        )
        if confirm != "github":
            return "skip dirty"
        reset = run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_dir, timeout=180)
        clean = run(["git", "clean", "-fd"], cwd=repo_dir, timeout=180)
        return "kept github" if reset.returncode == 0 and clean.returncode == 0 else "keep github failed"
    if choice == "local":
        if not has_tracked_changes(repo_dir, command_timeout):
            return "skip dirty untracked only"
        commit = run(["git", "add", "-A"], cwd=repo_dir, timeout=120)
        if commit.returncode != 0:
            return "stage failed"
        commit = run(["git", "commit", "-m", "chore: save local workspace changes"], cwd=repo_dir, timeout=180)
        if commit.returncode != 0:
            return "commit failed"
        return merge_origin(repo_dir, branch)

    stash = run(["git", "stash", "push", "-u", "-m", "workspace sync"], cwd=repo_dir, timeout=180)
    if stash.returncode != 0:
        return "stash failed"
    ff = run(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=repo_dir, timeout=180)
    if ff.returncode != 0:
        run(["git", "stash", "pop"], cwd=repo_dir, timeout=180)
        return "stash restored; ff failed"
    pop = run(["git", "stash", "pop"], cwd=repo_dir, timeout=180)
    return "updated with stash" if pop.returncode == 0 else "updated; stash pop conflict"


def sync_existing(repo_dir: Path, full_name: str, dry_run: bool, command_timeout: int, interactive: bool) -> str:
    try:
        branch = current_branch(repo_dir, command_timeout)
    except RuntimeError as exc:
        return str(exc)
    if not branch:
        return "skip detached"
    if dry_run:
        return "would fetch/ff"

    fetch = run(["git", "fetch", "--no-auto-maintenance", "origin"], cwd=repo_dir, timeout=180)
    if fetch.returncode != 0:
        return command_failure("fetch", fetch)
    remote_branch = run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd=repo_dir, timeout=command_timeout)
    if remote_branch.returncode == 1:
        return f"skip no origin/{branch}"
    if remote_branch.returncode != 0:
        return command_failure("remote branch check", remote_branch)

    try:
        clean = is_clean(repo_dir, command_timeout)
    except RuntimeError as exc:
        return str(exc)
    if not clean:
        return interactive_dirty_sync(repo_dir, branch, command_timeout) if interactive else "skip dirty"

    ahead = count_revs(repo_dir, f"origin/{branch}..HEAD", command_timeout)
    behind = count_revs(repo_dir, f"HEAD..origin/{branch}", command_timeout)
    if ahead is None or behind is None:
        return "skip rev-list failed"
    if ahead == 0 and behind == 0:
        return "current"
    if ahead > 0 and behind == 0:
        return "local ahead"

    if ahead == 0:
        ff = run(["git", "-c", "maintenance.auto=false", "merge", "--ff-only", f"origin/{branch}"], cwd=repo_dir, timeout=900)
        return "updated" if ff.returncode == 0 else command_failure("fast-forward", ff)

    if not interactive:
        return "skip not fast-forward"
    choice = ask_choice(
        "Branch diverged: local commits and GitHub commits both exist.",
        [
            ("skip", "do nothing to this repo"),
            ("merge", "try a normal Git merge"),
            ("local", "keep local branch as-is"),
            ("github", "reset local branch to GitHub after an extra confirmation"),
        ],
        "skip",
    )
    if choice == "merge":
        return merge_origin(repo_dir, branch)
    if choice == "github":
        confirm = ask_choice(
            "Confirm destructive reset: this resets the branch to GitHub.",
            [
                ("skip", "cancel and leave this repo unchanged"),
                ("github", "reset local branch to GitHub"),
            ],
            "skip",
        )
        if confirm != "github":
            return "skip not fast-forward"
        reset = run(["git", "reset", "--hard", f"origin/{branch}"], cwd=repo_dir, timeout=180)
        return "kept github" if reset.returncode == 0 else "keep github failed"
    if choice == "local":
        return "kept local"
    return "skip not fast-forward"


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Safely clone/fetch/fast-forward workspace repos.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--interactive", action="store_true", help="prompt for dirty/diverged repo decisions")
    parser.add_argument("--command-timeout", type=int, default=30, help="local Git check timeout in seconds (fetch/clone have separate limits)")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="limit to a repo name or full repo name; may be repeated",
    )
    args = parser.parse_args()

    workspace = normalize_path(args.workspace)
    filters = {item.strip().lower() for raw in args.only for item in raw.split(",") if item.strip()}
    print(f"Workspace: {workspace}")
    print("Discovering accessible GitHub repositories...")
    remotes = remote_repos()
    if filters:
        remotes = [repo for repo in remotes if selected(repo["full_name"], filters)]
    print(f"Remote repos in scope: {len(remotes)}")
    if filters:
        print(f"Filter: {', '.join(sorted(filters))}")
    print("No local repos are deleted by this tool.")
    print("Scanning local repository remotes...")
    local = local_repos(workspace, args.command_timeout)
    print(f"Local GitHub repos found: {len(local)}")
    print("-" * 72)

    cloned = current = updated = review = skipped = failed = 0
    review_queue: list[tuple[str, Path, str]] = []

    def record_existing_result(full_name: str, repo_dir: Path, result: str) -> None:
        nonlocal current, failed, review, skipped, updated
        display = result
        if args.interactive and result == "skip dirty":
            review_queue.append((full_name, repo_dir, "dirty working tree"))
            display = "review dirty"
        elif args.interactive and result == "skip not fast-forward":
            review_queue.append((full_name, repo_dir, "diverged branch"))
            display = "review diverged"

        if result == "updated":
            updated += 1
        elif result == "current":
            current += 1
        elif display.startswith("review "):
            review += 1
        elif "failed" in result:
            failed += 1
        else:
            skipped += 1
        print(f"[{display.upper():18}] {full_name} -> {repo_dir}")

    for index, repo in enumerate(remotes, 1):
        full_name = repo["full_name"]
        print(f"[{index}/{len(remotes)}] Checking {full_name}...")
        repo_dir = local.get(full_name)
        if repo_dir:
            result = sync_existing(repo_dir, full_name, args.dry_run, args.command_timeout, False)
            record_existing_result(full_name, repo_dir, result)
            continue

        target = clone_path(workspace, full_name)
        if target.exists():
            existing_full_name = existing_target_full_name(target, args.command_timeout)
            if existing_full_name == full_name:
                result = sync_existing(target, full_name, args.dry_run, args.command_timeout, False)
                record_existing_result(full_name, target, result)
                continue
            if existing_full_name:
                skipped += 1
                print(f"[SKIP PATH CONFLICT] {full_name}: {target} is {existing_full_name}")
                continue
            if not is_empty_dir(target):
                skipped += 1
                print(f"[SKIP PATH EXISTS  ] {full_name}: {target} exists but is not this Git repo")
                continue

        if args.dry_run:
            print(f"[WOULD CLONE        ] {full_name} -> {target}")
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Cloning {full_name} (timeout: 600s)...")
        clone = run(["gh", "repo", "clone", full_name, str(target), "--", "--filter=blob:none"], timeout=600)
        if clone.returncode == 0:
            cloned += 1
            print(f"[CLONED            ] {full_name} -> {target}")
        else:
            failed += 1
            print(f"[CLONE FAILED      ] {full_name}: {(clone.stderr or clone.stdout).strip()[:160]}")

    if args.interactive and review_queue and not args.dry_run:
        print("-" * 72)
        print(f"Safe pass complete. Review queue: {len(review_queue)} dirty/diverged repo(s).")
        print("You can skip any repo; destructive choices still require a second confirmation.")
        choice = ask_choice(
            "Review these now?",
            [
                ("review", "walk through the queued repos one by one"),
                ("skip", "leave queued repos unchanged"),
            ],
            "review",
        )
        if choice == "review":
            for index, (full_name, repo_dir, reason) in enumerate(review_queue, 1):
                print("-" * 72)
                print(f"{index}/{len(review_queue)} {full_name} -> {repo_dir}")
                print(f"Reason: {reason}")
                result = sync_existing(repo_dir, full_name, False, args.command_timeout, True)
                print(f"[{result.upper():18}] {full_name} -> {repo_dir}")

    print("-" * 72)
    print(
        f"Current: {current} | Updated: {updated} | Cloned: {cloned} | "
        f"Review: {review} | Skipped: {skipped} | Failed: {failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
