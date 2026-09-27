#!/usr/bin/env python3
"""
scan_identity.py - find YOUR personal details in a repo. No LLM, no network.

WHERE YOUR DETAILS COME FROM (priority order)
---------------------------------------------
1. $SHELL_IDENTITY      semicolon-separated string. PREFERRED.
                        Set in your PowerShell profile locally; set as a GitHub
                        Actions secret in CI. Never written to disk, never
                        committed, cannot be `git add`-ed by accident.

     phones=+6591234567,+6598765432;emails=you@gmail.com;names=Your Legal Name

2. $SHELL_IDENTITY_FILE path to a YAML/JSON file. Fallback only, discouraged.
                        A file full of your PII beside 110 git repos is one
                        stray `git add -A` from being public forever.

Categories: phones, emails, names, addresses, handles, other
Plus:       generated=path1,path2   (see LINKAGE below)

THE CORE IDEA
-------------
Do not scan for the *shape* of a phone number. Scan for *your specific values*.

A shape-based rule ("does this look like a Singapore mobile?") fires on every row
of sgPhoneNumbers65, on every <input type="tel">, and on every test fixture you
ever write. It is unusable, so you would disable it, so it protects nothing.

An exact-value rule fires only when your actual number, email, or address
appears. A generated +65 corpus is fine. A contact form is fine. Your number
hardcoded in a comment is not.

This complements TruffleHog rather than duplicating it: TruffleHog finds secrets
(API keys, tokens). It does not find your name or your home address.

LINKAGE, NOT PRESENCE
---------------------
If you generate an exhaustive number space, your own number is in it by
construction. That is not a leak - the value is not *associated* with you.
Declare such files in a `.shellignore` at the repo root, or via `generated=`.

USAGE
-----
  python scan_identity.py <path> [--json] [--history] [--quiet]

EXIT CODES
----------
  0 clean    1 hits found    2 not configured / usage error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# --------------------------------------------------------------------------
# config loading
# --------------------------------------------------------------------------

VALID_CATEGORIES = ("phones", "emails", "names", "addresses", "handles", "other")

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", ".venv", "venv",
    "__pycache__", ".mypy_cache", ".pytest_cache", "vendor", ".turbo",
    "coverage", ".cache", "out", ".svelte-kit", "target", ".gradle",
}

# Files we never scan: binaries, media, lockfiles (huge + machine-generated).
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".mp3", ".wav",
    ".zip", ".gz", ".tar", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
    ".parquet", ".db", ".sqlite", ".sqlite3", ".wasm", ".pyc", ".class",
}
SKIP_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "poetry.lock", "Cargo.lock", "composer.lock", "go.sum",
}

MAX_BYTES = 4 * 1024 * 1024  # skip files larger than this


def parse_identity_string(raw: str) -> dict:
    """Parse `phones=a,b;emails=c;names=D E` into a config dict.

    Values may contain spaces (names, addresses) but not ';' or ','.
    Unknown category names are reported rather than ignored: a typo like
    `phone=` instead of `phones=` would otherwise scan for nothing and the
    run would report a false clean.
    """
    cfg: dict = {}
    unknown: list[str] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        key, _, vals = chunk.partition("=")
        key = key.strip().lower()
        values = [v.strip() for v in vals.split(",") if v.strip()]
        if key == "generated":
            cfg["generated_paths"] = values
        elif key in VALID_CATEGORIES:
            cfg.setdefault(key, []).extend(values)
        else:
            unknown.append(key)
    if unknown:
        sys.stderr.write(
            "scan_identity: unknown category in $SHELL_IDENTITY: "
            + ", ".join(unknown)
            + "\n  valid: " + ", ".join(VALID_CATEGORIES) + ", generated\n")
    return cfg


def _load_file(path: Path) -> dict:
    """Fallback loader. Discouraged - prefer $SHELL_IDENTITY."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        data: dict = {}
        current = None
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if re.match(r"^\s+-\s", line):
                if current:
                    data.setdefault(current, []).append(
                        line.strip()[1:].strip().strip("'\""))
            elif ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip().strip("'\"")
                if v:
                    data[k] = v
                    current = None
                else:
                    data[k] = []
                    current = k
        return data


def load_config() -> tuple[dict, str]:
    """Env var first, file fallback, else fail closed."""
    raw = os.environ.get("SHELL_IDENTITY", "").strip()
    if raw:
        return parse_identity_string(raw), "$SHELL_IDENTITY"

    fpath = os.environ.get("SHELL_IDENTITY_FILE", "").strip()
    if fpath:
        p = Path(fpath).expanduser()
        if p.is_file():
            sys.stderr.write(
                "scan_identity: reading from a file. Prefer $SHELL_IDENTITY so "
                "your details never touch disk.\n")
            return _load_file(p), str(p)
        sys.stderr.write(f"scan_identity: $SHELL_IDENTITY_FILE not found: {p}\n")
        sys.exit(2)

    sys.stderr.write(
        "scan_identity: no identity data configured.\n\n"
        "Set $SHELL_IDENTITY, e.g. in your PowerShell profile:\n"
        '  $env:SHELL_IDENTITY = "phones=+6591234567;emails=you@gmail.com;'
        'names=Your Legal Name"\n\n'
        "In CI, set it as a GitHub Actions secret on sourcerepo only.\n"
        "Refusing to run: an unconfigured scan reports clean and protects "
        "nothing.\n")
    sys.exit(2)


# --------------------------------------------------------------------------
# normalisation — the part that makes matching actually work
# --------------------------------------------------------------------------

def norm_phone(s: str) -> str:
    """Digits only, with a leading 65 country code stripped.

    So +65 9123 4567 / +6591234567 / 9123-4567 / 91234567 all collapse to
    the same key and all match.
    """
    d = re.sub(r"\D", "", s)
    if len(d) > 8 and d.startswith("65"):
        d = d[2:]
    return d


def norm_email(s: str) -> str:
    """Lowercase, and drop plus-addressing so sample.user+gh@x.com matches sample.user@x.com."""
    s = s.strip().lower()
    if "@" not in s:
        return s
    local, _, domain = s.partition("@")
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def norm_text(s: str) -> str:
    """Collapse whitespace and punctuation for names / addresses / handles."""
    return re.sub(r"[\s\-_.,#]+", " ", s.strip().lower()).strip()


NORMALISERS = {
    "phones": norm_phone,
    "emails": norm_email,
    "names": norm_text,
    "addresses": norm_text,
    "handles": norm_text,
    "other": norm_text,
}

# Token extractors per category — what we pull OUT of a file to compare.
TOKEN_PATTERNS = {
    "phones": re.compile(r"(?:\+?\d[\d\s\-().]{6,20}\d)"),
    "emails": re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
}


def digest(value: str, salt: str) -> str:
    return hashlib.sha256((salt + "\x00" + value).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------

@dataclass
class Hit:
    path: str
    line: int
    category: str
    excerpt: str

    def render(self) -> str:
        return f"{self.path}:{self.line}  [{self.category}]  {self.excerpt}"


class Matcher:
    """Holds your normalised values and compares file content against them."""

    def __init__(self, cfg: dict):
        self.needles: dict[str, set[str]] = {}
        for cat, norm in NORMALISERS.items():
            values = cfg.get(cat) or []
            if isinstance(values, str):
                values = [values]
            normed = {norm(str(v)) for v in values if v and str(v).strip()}
            # Drop anything too short to be a meaningful identifier; a 2-char
            # needle would match half of every file.
            self.needles[cat] = {n for n in normed if n and len(n) >= 4}

        dropped = sum(
            len([v for v in (cfg.get(c) or []) if v and str(v).strip()])
            for c in NORMALISERS) - sum(len(v) for v in self.needles.values())
        if dropped > 0:
            sys.stderr.write(
                f"scan_identity: ignored {dropped} value(s) shorter than 4 "
                "characters after normalisation.\n")

    def _hit(self, cat: str, candidate: str) -> bool:
        return bool(candidate) and candidate in self.needles.get(cat, set())

    def scan_line(self, line: str) -> list[tuple[str, str]]:
        """Return [(category, matched_text)] for this line."""
        found: list[tuple[str, str]] = []

        # Structured categories: extract tokens, normalise, compare.
        for cat, pattern in TOKEN_PATTERNS.items():
            if not self.needles.get(cat):
                continue
            for m in pattern.finditer(line):
                raw = m.group(0)
                if self._hit(cat, NORMALISERS[cat](raw)):
                    found.append((cat, raw))

        # Free-text categories: substring search on the normalised line.
        norm_line = norm_text(line.lower())
        for cat in ("names", "addresses", "handles", "other"):
            for needle in self.needles.get(cat, set()):
                if needle in norm_line:
                    found.append((cat, needle))
        return found


# --------------------------------------------------------------------------
# walking
# --------------------------------------------------------------------------

def generated_match(rel: str, generated: list[str]) -> bool:
    for g in generated:
        g = g.strip().rstrip("/")
        if not g:
            continue
        if rel == g or rel.startswith(g + "/") or Path(rel).match(g):
            return True
    return False


def should_skip(path: Path, root: Path, generated: list[str]) -> bool:
    rel = path.relative_to(root).as_posix()
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if generated_match(rel, generated):
        return True
    try:
        if path.stat().st_size > MAX_BYTES:
            return True
    except OSError:
        return True
    return False


def scan_tree(root: Path, matcher: Matcher, generated: list[str]) -> list[Hit]:
    hits: list[Hit] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_skip(path, root, generated):
            continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if "\x00" in line:      # binary sneaked through
                        break
                    for cat, raw in matcher.scan_line(line):
                        excerpt = line.strip()
                        if len(excerpt) > 140:
                            excerpt = excerpt[:137] + "..."
                        hits.append(Hit(
                            path.relative_to(root).as_posix(), lineno, cat, excerpt))
        except (OSError, UnicodeDecodeError):
            continue
    return hits


def scan_history(root: Path, matcher: Matcher, generated: list[str]) -> list[Hit]:
    """Report-only scan of committed history. Never rewrites anything."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "-p", "--no-color", "--all"],
            capture_output=True, text=True, errors="replace", timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    hits: list[Hit] = []
    commit = "?"
    current_file = ""
    seen: set[tuple[str, str]] = set()
    for line in out.stdout.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:9]
            current_file = ""
        elif line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+++ /dev/null"):
            current_file = ""
        elif line.startswith("+") and not line.startswith("+++"):
            if current_file and generated_match(current_file, generated):
                continue
            for cat, raw in matcher.scan_line(line[1:]):
                key = (commit, raw)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(Hit(f"history@{commit}", 0, cat, line[1:].strip()[:140]))
    return hits


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Scan a repo for your personal details.")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("-j", "--json", action="store_true", help="machine-readable output")
    ap.add_argument("-H", "--history", action="store_true",
                    help="also scan git history (report only, never rewrites)")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print on failure")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.is_dir():
        sys.stderr.write(f"scan_identity: not a directory: {root}\n")
        return 2

    cfg, cfg_src = load_config()
    matcher = Matcher(cfg)

    total_needles = sum(len(v) for v in matcher.needles.values())
    if total_needles == 0:
        sys.stderr.write(
            f"scan_identity: {cfg_src} contained no usable values. "
            "An empty needle list reports clean and protects nothing.\n")
        return 2

    # Per-repo declared generated corpora, plus any global ones from config.
    generated = list(cfg.get("generated_paths") or [])
    local_ignore = root / ".shellignore"
    if local_ignore.is_file():
        generated += [
            ln.strip() for ln in local_ignore.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]

    hits = scan_tree(root, matcher, generated)
    if args.history:
        hits += scan_history(root, matcher, generated)

    if args.json:
        print(json.dumps({
            "repo": root.name,
            "source": cfg_src,
            "needles": total_needles,
            "hits": [asdict(h) for h in hits],
        }, indent=2))
    elif hits:
        print(f"IDENTITY HITS in {root.name} ({len(hits)}):")
        for h in hits:
            print("  " + h.render())
        print("\nRemove these, then re-run. If a file is a generated corpus "
              "(an exhaustive number space, not data about you), add it to "
              ".shellignore instead.")
    elif not args.quiet:
        print(f"clean: {root.name} ({total_needles} needles from {cfg_src})")

    return 1 if hits else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Piping into `head` etc. closes stdout early; not an error.
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
