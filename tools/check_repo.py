#!/usr/bin/env python3
"""Check one repository against the SHELL standard.

Pure Python, deterministic file checks, and optional GitHub metadata via `gh`.
The script never modifies the target repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


OWNERS = {"hongyime", "bryanseah234"}
NOTICE_TEXT = "Copyright 2026 The Prawn Organisation"
DEFAULT_HOMEPAGES = {
    "",
    "https://www.hong-yi.me",
    "http://www.hong-yi.me",
    "https://hong-yi.me",
    "http://hong-yi.me",
}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)


def parse_simple_yaml(path: Path) -> dict[str, Any]:
    """Load the repository catalog YAML without accepting unsafe constructors."""
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def sourcerepo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def remote_full_name(repo: Path) -> str | None:
    code, out, _ = run(["git", "remote", "get-url", "origin"], cwd=repo)
    if code != 0:
        return None
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", out)
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def tier_for(full_name: str | None, tiers: dict[str, Any]) -> str:
    if not full_name:
        return "external"
    owner = full_name.split("/", 1)[0]
    if owner not in OWNERS:
        return "external"
    for tier in ("external", "archived", "showcase", "standard"):
        values = tiers.get(tier) or []
        if full_name in values:
            return tier
    return "unclassified"


def github_metadata(full_name: str | None) -> dict[str, Any]:
    if not full_name:
        return {}
    fields = "description,homepageUrl,repositoryTopics,isArchived,isPrivate,licenseInfo,defaultBranchRef,pushedAt"
    code, out, err = run(["gh", "repo", "view", full_name, "--json", fields], timeout=45)
    if code != 0:
        return {"error": err or out or f"gh exited {code}"}
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        return {"error": f"invalid gh JSON: {exc}"}
    data["topics"] = [
        item.get("name")
        for item in data.get("repositoryTopics") or []
        if isinstance(item, dict) and item.get("name")
    ]
    return data


def text(path: Path, max_bytes: int = 500_000) -> str:
    try:
        if path.is_file() and path.stat().st_size <= max_bytes:
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def has_apache_license(repo: Path) -> bool:
    for name in ("LICENSE", "LICENSE.md", "LICENCE", "LICENCE.md"):
        body = text(repo / name).lower()
        if (
            "apache license" in body
            and "version 2.0" in body
            and "http://www.apache.org/licenses/" in body
            and len(body) > 8_000
        ):
            return True
    return False


def readme_ok(repo: Path) -> tuple[bool, list[str]]:
    body = text(repo / "README.md")
    missing: list[str] = []
    if len(body.encode("utf-8")) < 400:
        missing.append("README.md >= 400 bytes")
    if not re.search(r"^#\s+\S", body, re.MULTILINE):
        missing.append("title")
    prose = [
        line
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "[!", "<!--"))
    ]
    if not prose:
        missing.append("description")
    if not any(token in body.lower() for token in ("setup", "install", "getting started", "usage", "run")):
        missing.append("setup")
    return not missing, missing


def media_present(repo: Path, readme: str) -> bool:
    if re.search(r"!\[[^\]]*\]\([^)]*\.(?:png|jpe?g|gif|webp)", readme, re.IGNORECASE):
        return True
    for name in ("screenshot.png", "screenshot.jpg", "demo.gif"):
        if (repo / name).is_file():
            return True
    return False


def repos_config(root: Path) -> dict[str, Any]:
    parsed = parse_simple_yaml(root / "repos.yml")
    return parsed.get("repos") if isinstance(parsed.get("repos"), dict) else parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Check one repo against SHELL R1-R6.")
    parser.add_argument("repo")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    root = sourcerepo_root()
    full_name = remote_full_name(repo)
    tiers = parse_simple_yaml(root / "tiers.yml")
    tier = tier_for(full_name, tiers)
    cfg = repos_config(root)
    gh = github_metadata(full_name) if tier != "external" else {}
    rules: dict[str, dict[str, Any]] = {}

    if tier == "external":
        result = {
            "repo": full_name or repo.name,
            "path": str(repo),
            "tier": tier,
            "ok": True,
            "rules": {},
            "notes": ["external repo; skipped"],
        }
        print(json.dumps(result, indent=2))
        return 0

    if tier == "archived":
        body = text(repo / "README.md")
        archived_banner = "archived" in body.lower()
        rules["archived-banner"] = {"ok": archived_banner, "detail": "README mentions archived"}
        ok = archived_banner
        result = {"repo": full_name, "path": str(repo), "tier": tier, "ok": ok, "rules": rules, "github": gh}
        print(json.dumps(result, indent=2))
        return 0 if ok else 1

    rules["R1"] = {
        "ok": has_apache_license(repo) and NOTICE_TEXT in text(repo / "NOTICE"),
        "detail": "Apache-2.0 LICENSE and NOTICE contains organisation copyright",
    }

    repo_cfg = cfg.get(full_name or "", {}) if isinstance(cfg, dict) else {}
    description = gh.get("description") or repo_cfg.get("description") or ""
    rules["R2"] = {
        "ok": bool(description.strip()) and len(description) <= 120 and description != "Give me 1 ⭐ if it's cool.",
        "detail": "description is non-empty, real, and <= 120 chars",
    }

    topics = gh.get("topics") or repo_cfg.get("topics") or []
    topic_vocab = parse_simple_yaml(root / "topics.yml")
    allowed = set(topic_vocab.get("topics") or []) | set(topic_vocab.get("reserved") or [])
    topic_values = [t for t in topics if t not in {"keep-lfs", "no-config-sync"}]
    rules["R3"] = {
        "ok": len(topic_values) >= 3 and all(t in allowed for t in topics),
        "detail": "at least 3 topics from topics.yml",
        "topics": topics,
    }

    readme_pass, readme_missing = readme_ok(repo)
    rules["R4"] = {"ok": readme_pass, "detail": "README title, description, setup, >=400 bytes", "missing": readme_missing}

    # R5 is provided by tools/scan_identity.py so the secret never enters this script.
    rules["R5"] = {"ok": None, "detail": "run tools/scan_identity.py separately"}

    if tier == "showcase":
        homepage = gh.get("homepageUrl") or repo_cfg.get("homepage") or ""
        hp = homepage.strip().lower().rstrip("/")
        readme = text(repo / "README.md")
        first30 = "\n".join(readme.splitlines()[:30]).lower()
        rules["R6"] = {
            "ok": bool(hp)
            and hp not in DEFAULT_HOMEPAGES
            and (hp in first30 or "demo" in first30 or "live" in first30)
            and media_present(repo, readme),
            "detail": "showcase homepage, demo link in first 30 lines, screenshot/GIF",
        }

    ok = all(rule["ok"] is not False for rule in rules.values())
    result = {
        "repo": full_name,
        "path": str(repo),
        "tier": tier,
        "ok": ok,
        "rules": rules,
        "github": gh,
    }
    print(json.dumps(result, indent=2) if args.json else json.dumps(result))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
