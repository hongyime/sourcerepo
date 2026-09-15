#!/usr/bin/env python3
"""Reconcile live owned GitHub repositories with sourcerepo metadata.

This tool never modifies target repositories. With --write, it only updates
repos.yml and tiers.yml in sourcerepo so the existing sync workflow can fan out
approved source-of-truth changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_KEY = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+):\s*$")
TIER_NAMES = ("external", "archived", "showcase", "standard")
UPKEEP_OWNER = "hongyime"


@dataclass(frozen=True)
class LiveRepo:
    full_name: str
    description: str
    homepage: str
    topics: tuple[str, ...]
    archived: bool
    private: bool
    fork: bool
    disabled: bool


def run(cmd: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc.stdout


def yaml_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def parse_repos(path: Path) -> dict[str, dict[str, Any]]:
    repos: dict[str, dict[str, Any]] = {}
    current: str | None = None
    current_field: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        match = REPO_KEY.match(line)
        if match:
            current = match.group(1)
            current_field = None
            repos[current] = {}
            continue
        if current is None:
            continue
        if line.startswith("  ") and not line.startswith("    "):
            key, _, rest = line.strip().partition(":")
            current_field = key
            value = rest.strip()
            if value == "":
                repos[current][key] = []
            elif value == "[]":
                repos[current][key] = []
            elif value in {"true", "false"}:
                repos[current][key] = value == "true"
            elif (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                repos[current][key] = value[1:-1]
            else:
                repos[current][key] = value
            continue
        if line.startswith("    ") and current_field:
            stripped = line.strip()
            if stripped.startswith("- "):
                values = repos[current].setdefault(current_field, [])
                if isinstance(values, list):
                    values.append(stripped[2:].strip())
    return repos


def parse_tiers(path: Path) -> dict[str, list[str]]:
    tiers = {tier: [] for tier in TIER_NAMES}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"[A-Za-z_-]+:", stripped):
            current = stripped[:-1]
            tiers.setdefault(current, [])
            continue
        if current and stripped.startswith("- "):
            tiers.setdefault(current, []).append(stripped[2:].strip())
    return tiers


def parse_topic_vocab(path: Path) -> set[str]:
    allowed: set[str] = set()
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if re.fullmatch(r"[A-Za-z_-]+:", stripped):
            current = stripped[:-1]
            continue
        if current in {"topics", "reserved"} and stripped.startswith("- "):
            allowed.add(stripped[2:].strip())
    return allowed


def api_json(path: str) -> list[dict[str, Any]]:
    raw = run(["gh", "api", "--paginate", path], timeout=120)
    pages: list[Any] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        page, offset = decoder.raw_decode(raw, index)
        pages.append(page)
        index = offset
    repos: list[dict[str, Any]] = []
    if not pages:
        raise ValueError("Repository discovery returned no JSON pages")
    for page in pages:
        if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
            raise ValueError("Repository discovery returned an invalid page")
        repos.extend(page)
    return repos


def live_repo_from_api(item: dict[str, Any]) -> LiveRepo | None:
    full_name = item.get("full_name") or ""
    if not full_name:
        return None
    return LiveRepo(
        full_name=full_name,
        description=(item.get("description") or "").strip(),
        homepage=(item.get("homepage") or "").strip(),
        topics=tuple(topic for topic in item.get("topics") or [] if isinstance(topic, str)),
        archived=bool(item.get("archived")),
        private=bool(item.get("private")),
        fork=bool(item.get("fork")),
        disabled=bool(item.get("disabled")),
    )


def discover_live_repos(owner: str) -> dict[str, LiveRepo]:
    live: dict[str, LiveRepo] = {}
    if owner != UPKEEP_OWNER:
        raise ValueError("Repository upkeep is restricted to hongyime")
    for item in api_json(f"orgs/{owner}/repos?per_page=100"):
        repo = live_repo_from_api(item)
        if repo and repo.full_name.split("/", 1)[0] == owner and not repo.disabled:
            live[repo.full_name] = repo
    return dict(sorted(live.items()))


def add_repos_entries(path: Path, missing: list[LiveRepo], allowed_topics: set[str]) -> None:
    if not missing:
        return
    lines = path.read_text(encoding="utf-8").rstrip().splitlines()
    if lines and lines[-1] != "":
        lines.append("")
    for repo in missing:
        filtered_topics = [topic for topic in repo.topics if topic in allowed_topics]
        lines.append(f"{repo.full_name}:")
        lines.append(f"  description: {yaml_quote(repo.description)}")
        lines.append(f"  homepage: {yaml_quote(repo.homepage)}")
        if repo.private:
            lines.append("  visibility: private")
        lines.append("  topics:" if filtered_topics else "  topics: []")
        for topic in filtered_topics:
            lines.append(f"    - {topic}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def add_tier_entries(path: Path, missing_by_tier: dict[str, list[str]]) -> None:
    if not any(missing_by_tier.values()):
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    for tier in ("archived", "standard"):
        values = missing_by_tier.get(tier, [])
        if not values:
            continue
        insert_at = len(lines)
        for i, line in enumerate(lines):
            if line == f"{tier}:":
                insert_at = i + 1
                while insert_at < len(lines) and re.match(r"\s*-\s+", lines[insert_at]):
                    insert_at += 1
                break
        for value in sorted(values):
            lines.insert(insert_at, f"  - {value}")
            insert_at += 1
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def markdown_report(
    *,
    live: dict[str, LiveRepo],
    repos: dict[str, dict[str, Any]],
    tiers: dict[str, list[str]],
    missing_repos: list[LiveRepo],
    missing_tiers: dict[str, list[str]],
) -> str:
    managed_tiered = {
        value
        for tier, values in tiers.items()
        if tier != "external"
        for value in values
    }
    tiered = {value for values in tiers.values() for value in values}
    owned = lambda value: value.split("/", 1)[0] == UPKEEP_OWNER
    stale_repos = sorted(value for value in set(repos) - set(live) if owned(value))
    stale_tiers = sorted(value for value in managed_tiered - set(live) if owned(value))
    duplicate_tiers = sorted(
        value
        for value in tiered
        if owned(value) and sum(value in values for values in tiers.values()) > 1
    )

    lines = [
        "## Summary",
        "",
        "Register missing hongyime catalog entries while preserving existing metadata and review history.",
        "",
        f"- Live owned repos discovered: {len(live)}",
        f"- Missing repos.yml entries: {len(missing_repos)}",
        f"- Missing tiers.yml entries: {sum(len(v) for v in missing_tiers.values())}",
        f"- Stale repos.yml entries: {len(stale_repos)}",
        f"- Stale tiers.yml entries: {len(stale_tiers)}",
        f"- Duplicate tier entries: {len(duplicate_tiers)}",
        "",
        "## Changes",
        "",
    ]
    if missing_repos:
        lines += ["### Added repos.yml Entries", ""]
        for repo in missing_repos:
            visibility = "private" if repo.private else "public"
            lines.append(f"- {repo.full_name} ({visibility})")
        lines.append("")
    if any(missing_tiers.values()):
        lines += ["### Added tiers.yml Entries", ""]
        for tier, values in missing_tiers.items():
            for value in values:
                lines.append(f"- {value} -> {tier}")
        lines.append("")
    if stale_repos:
        lines += ["### Unresolved repos.yml Entries - Review Only", ""]
        lines += [f"- {value}" for value in stale_repos]
        lines.append("")
    if stale_tiers:
        lines += ["### Unresolved tiers.yml Entries - Review Only", ""]
        lines += [f"- {value}" for value in stale_tiers]
        lines.append("")
    if duplicate_tiers:
        lines += ["### Duplicate Tier Entries - Review Only", ""]
        lines += [f"- {value}" for value in duplicate_tiers]
        lines.append("")
    if not missing_repos and not any(missing_tiers.values()):
        lines.append("No registration changes are needed.")
    lines += [
        "", "## Testing", "",
        "This report compares the accessible owned-repository inventory with the current catalogs. "
        "Hosted checks and the proposed diff must be reviewed before merge; discovery does not prove release readiness.",
        "Missing inventory entries are retained. Absence or a 404 does not establish deletion or authorize cleanup.",
        "", "## Checklist", "",
        "- [ ] No debug code or console logs left behind.",
        "- [ ] No secrets or credentials committed.",
        "- [ ] Documentation updated if behaviour changed.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile live repos with sourcerepo metadata.")
    parser.add_argument("--org-owner", default=os.environ.get("GITHUB_REPOSITORY_OWNER", "hongyime"))
    parser.add_argument("--repos-yml", type=Path, default=Path("repos.yml"))
    parser.add_argument("--tiers-yml", type=Path, default=Path("tiers.yml"))
    parser.add_argument("--topics-yml", type=Path, default=Path("topics.yml"))
    parser.add_argument("--live-json", type=Path, help="Use a fixture instead of gh repo list.")
    parser.add_argument("--report", type=Path, help="Write a markdown reconciliation report.")
    parser.add_argument("--write", action="store_true", help="Update repos.yml and tiers.yml.")
    args = parser.parse_args(argv)
    if args.org_owner != UPKEEP_OWNER:
        parser.error("Repository upkeep is restricted to hongyime")

    repos = parse_repos(args.repos_yml)
    tiers = parse_tiers(args.tiers_yml)
    allowed_topics = parse_topic_vocab(args.topics_yml)
    if args.live_json:
        raw_live = json.loads(args.live_json.read_text(encoding="utf-8"))
        if not isinstance(raw_live, list) or any(not isinstance(item, dict) for item in raw_live):
            raise ValueError("Repository fixture must contain an array of objects")
        live = {
            item["full_name"]: LiveRepo(
                full_name=item["full_name"],
                description=item.get("description", ""),
                homepage=item.get("homepage", ""),
                topics=tuple(item.get("topics", [])),
                archived=bool(item.get("archived")),
                private=bool(item.get("private")),
                fork=bool(item.get("fork")),
                disabled=bool(item.get("disabled")),
            )
            for item in raw_live
        }
    else:
        live = discover_live_repos(args.org_owner)
    live = {
        name: repo for name, repo in live.items()
        if name.split("/", 1)[0] == UPKEEP_OWNER and not repo.disabled
    }

    tiered = {value for values in tiers.values() for value in values}
    missing_repos = [
        repo for name, repo in live.items()
        if name not in repos and not repo.fork
    ]
    missing_tiers: dict[str, list[str]] = {"archived": [], "standard": []}
    for name, repo in live.items():
        if name not in tiered and not repo.fork:
            tier = "archived" if repo.archived else "standard"
            missing_tiers[tier].append(name)

    report = markdown_report(
        live=live,
        repos=repos,
        tiers=tiers,
        missing_repos=missing_repos,
        missing_tiers=missing_tiers,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report, end="")

    if args.write:
        add_repos_entries(args.repos_yml, missing_repos, allowed_topics)
        add_tier_entries(args.tiers_yml, missing_tiers)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
