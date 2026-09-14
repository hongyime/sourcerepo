"""Exercise config sync against disposable local Git repos and a fake GitHub CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ConfigSyncTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="prawn-config-sync-")
        self.base = Path(self.scratch.name).resolve()
        self.addCleanup(self.cleanup)
        self.source = self.base / "source with spaces"
        self.seed = self.base / "seed"
        self.bare = self.base / "target.git"
        self.bin = self.base / "bin"
        self.logs = self.base / "github-calls.txt"
        for directory in (self.source, self.seed, self.bin, self.base / "tmp"):
            directory.mkdir()
        self.bash = os.environ.get("PRAWN_TEST_BASH") or (
            "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        )
        jq = os.environ.get("PRAWN_TEST_JQ") or shutil.which("jq")
        real_git = shutil.which("git")
        if not self.bash or not Path(self.bash).is_file() or not jq or not real_git:
            self.fail("Config sync checks require Bash, jq and Git; optional PRAWN_TEST_BASH/JQ paths are supported")
        shutil.copy2(jq, self.bin / ("jq.exe" if os.name == "nt" else "jq"))
        self.real_git = real_git
        # No account credentials are inherited. All Git transports except local files
        # are disabled, and the script's global Git configuration is isolated.
        self.env = {name: value for name, value in os.environ.items()
                    if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"}}
        self.env.update({
            "PATH": str(self.bin) + os.pathsep + str(Path(self.bash).parent) + os.pathsep + os.environ.get("PATH", ""),
            "TMPDIR": (self.base / "tmp").as_posix(),
            "GIT_CONFIG_GLOBAL": (self.base / "gitconfig").as_posix(),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_ALLOW_PROTOCOL": "file",
            "GIT_TERMINAL_PROMPT": "0", "GITHUB_REPOSITORY_OWNER": "hongyime",
            "GITHUB_REPOSITORY": "hongyime/source", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
            "SYNC_ITEMS": "managed.txt|managed.txt\n.github/ISSUE_TEMPLATE|.github/ISSUE_TEMPLATE\n.gitattributes|.gitattributes\n.github/workflows/lfs-guard.yml|.github/workflows/lfs-guard.yml",
            "COMMIT_MESSAGE": "chore(config): fixture sync [skip ci]",
            "PR_TITLE": "chore(config): sync shared configuration", "PR_BODY": "fixture\n\nActual newlines stay intact.\n", "INCLUDE_ARCHIVED": "true",
            "PRAWN_REAL_GIT": Path(real_git).as_posix(), "PRAWN_BARE_REPO": self.bare.as_posix(),
            "PRAWN_GH_LOG": self.logs.as_posix(), "PRAWN_TEST_MODE": "normal",
            "PRAWN_TEST_TOPICS": "", "PRAWN_TEST_ARCHIVED": "false",
            "PRAWN_TEST_PROTECTED": "false", "PRAWN_GIT_LOG": (self.base / "git-calls.txt").as_posix(),
        })
        script = Path(os.environ.get("PRAWN_CONFIG_SYNC_SCRIPT", ROOT / ".github/scripts/sync-selected-paths.sh"))
        self.script = self.source / "sync.sh"
        self.script.write_text(script.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        self.write(self.source, ".github/scripts/preserve-workflow-actions.py",
                   (ROOT / ".github/scripts/preserve-workflow-actions.py").read_text(encoding="utf-8"))
        for name, value in {
            "managed.txt": "new shared config\n",
            ".github/ISSUE_TEMPLATE/bug.yml": "shared issue form\n",
            ".gitattributes": "shared attributes\n",
            ".github/workflows/lfs-guard.yml": "name: shared LFS guard\njobs: {}\n",
        }.items():
            self.write(self.source, name, value)
        self.preserved = {
            "docs/manual.txt": "application documentation\n",
            "skills/domain/reference.txt": "application skill data\n",
            "skills-lock.json": '{"owned":"by app"}\n',
            ".devcontainer/devcontainer.json": '{"name":"app environment"}\n',
            "nested/dev.code-workspace": '{"folders":[]}\n',
            "templates/index.html": "application template\n",
            ".agents/STATE.md": "application handoff\n",
            ".github/ISSUE_TEMPLATE/local.yml": "custom local issue form\n",
        }
        for name, value in {**self.preserved, "managed.txt": "old shared config\n",
                            ".gitattributes": "app LFS attributes\n",
                            ".github/workflows/lfs-guard.yml": "name: app LFS policy\njobs: {}\n"}.items():
            self.write(self.seed, name, value)
        self.git("init", "--initial-branch=main", cwd=self.seed)
        self.git("add", "-A", cwd=self.seed)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture", cwd=self.seed)
        self.git("clone", "--bare", str(self.seed), str(self.bare), cwd=self.base)
        self.original_head = self.git("rev-parse", "main", cwd=self.bare).stdout.strip()
        self.executable("gh", '''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$PRAWN_GH_LOG"
case "$1 $2" in
  'api --paginate')
    if [[ "$3" == orgs/* ]]; then
      [ "$PRAWN_TEST_MODE" != org_error ] || exit 71
      printf '[{"name":"target","full_name":"hongyime/target","owner":{"login":"hongyime"},"archived":%s,"disabled":false,"fork":false,"default_branch":"main"}]\\n' "$PRAWN_TEST_ARCHIVED"
    elif [[ "$3" == user/repos* ]]; then
      [ "$PRAWN_TEST_MODE" != personal_error ] || exit 72
      printf '[]\\n'
    else exit 90; fi ;;
  'api repos/hongyime/target/topics')
    [ "$PRAWN_TEST_MODE" != topics_error ] || exit 73
    printf '%s\\n' "$PRAWN_TEST_TOPICS" ;;
  'api repos/hongyime/target/branches/main')
    [ "$PRAWN_TEST_MODE" != protection_error ] || exit 76
    if [ "$PRAWN_TEST_MODE" = invalid_protection ]; then printf 'unknown\\n'
    else printf '%s\\n' "$PRAWN_TEST_PROTECTED"; fi ;;
  'api -X')
    [ "$3" = PATCH ] && [ "$4" = repos/hongyime/target ] || exit 91
    case "$6" in archived=true|archived=false) exit 0;; *) exit 92;; esac ;;
  'repo clone')
    [ "$3" = hongyime/target ] || exit 93
    exec "$PRAWN_REAL_GIT" clone "$PRAWN_BARE_REPO" "$4" ;;
  'pr create')
    [ "$PRAWN_TEST_MODE" != pr_error ] || exit 77
    shift 2
    title='' head='' body_file=''
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --title) title="$2"; shift 2 ;;
        --head) head="$2"; shift 2 ;;
        --body-file) body_file="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [ "$title" = 'chore(config): sync shared configuration' ] || exit 78
    [[ "$head" =~ ^chore/[a-z0-9]+(-[a-z0-9]+)*$ ]] || exit 79
    [ -f "$body_file" ] && [ "$(cat "$body_file")" = "${PR_BODY%$'\\n'}" ] || exit 80
    printf 'https://github.com/hongyime/target/pull/1\\n' ;;
  *) echo 'Unexpected fake GitHub operation' >&2; exit 94 ;;
esac
''')
        self.executable("git", '''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$PRAWN_GIT_LOG"
if [ "$1" = push ] && [ "$PRAWN_TEST_MODE" = push_error ]; then exit 75; fi
if [ "$*" = 'push origin HEAD:main' ] && [ "$PRAWN_TEST_MODE" = main_push_error ]; then exit 75; fi
exec "$PRAWN_REAL_GIT" "$@"
''')
        self.executable("sleep", "#!/usr/bin/env bash\n# Retry delays are unnecessary for deterministic fixture failures.\nexit 0\n")
        if os.name == "nt":
            self.executable("jq", '#!/usr/bin/env bash\nexec "$(dirname "$0")/jq.exe" --binary "$@"\n')

    def cleanup(self):
        expected_parent = Path(tempfile.gettempdir()).resolve()
        if self.base != Path(self.scratch.name).resolve() or self.base.parent != expected_parent or not self.base.name.startswith("prawn-config-sync-"):
            raise RuntimeError("Unexpected fixture cleanup target")
        # Git creates read-only loose objects on Windows; clear only test-owned bits.
        if os.name == "nt":
            for path in self.base.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    path.chmod(0o600)
        self.scratch.cleanup()

    @staticmethod
    def write(root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def executable(self, name, text):
        path = self.bin / name
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o700)

    def git(self, *args, cwd):
        return subprocess.run([self.real_git, *args], cwd=cwd, env=self.env,
                              capture_output=True, text=True, check=True, timeout=60)

    def run_sync(self, mode="normal", topics="", archived=False, protected=False):
        env = {**self.env, "PRAWN_TEST_MODE": mode, "PRAWN_TEST_TOPICS": topics,
               "PRAWN_TEST_ARCHIVED": "true" if archived else "false",
               "PRAWN_TEST_PROTECTED": "true" if protected else "false"}
        return subprocess.run([self.bash, "--noprofile", "--norc", "sync.sh"], cwd=self.source,
                              env=env, capture_output=True, text=True, timeout=120)

    def blob(self, path):
        try:
            return self.git("show", "main:" + path, cwd=self.bare).stdout
        except subprocess.CalledProcessError:
            self.fail("Expected tracked file is missing after sync: " + path)

    def assert_untouched(self):
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        calls = self.logs.read_text() if self.logs.exists() else ""
        self.assertNotIn("repo clone", calls)
        self.assertNotIn("api -X", calls)

    def test_sync_preserves_application_files(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.blob("managed.txt"), "new shared config\n")
        for path, value in self.preserved.items():
            with self.subTest(path=path):
                self.assertEqual(self.blob(path), value)

    def test_workflow_sync_preserves_reviewed_sha_and_annotation(self):
        path = ".github/workflows/pinned.yml"
        source = ("name: Shared\non: workflow_dispatch\njobs:\n  check:\n    runs-on: ubuntu-latest\n"
                  "    steps:\n      - uses: actions/labeler@v6\n      - run: echo refreshed-policy\n")
        pin = "bf12e9b00b37c5c0ca2b87b79b2daf7891dbda13"
        target = source.replace("actions/labeler@v6", "actions/labeler@" + pin + " # v7.0.0")
        target = target.replace("refreshed-policy", "old-policy")
        self.write(self.source, path, source)
        self.write(self.seed, path, target)
        self.env["SYNC_ITEMS"] += f"\n{path}|{path}"
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        actual = self.blob(path)
        self.assertIn("actions/labeler@" + pin, actual)
        self.assertIn("# v7.0.0", actual)
        self.assertNotIn("actions/labeler@v6", actual)
        self.assertIn("echo refreshed-policy", actual)

    def test_workflow_sync_preserves_repository_action_version(self):
        path = ".github/workflows/python.yml"
        source = ("name: Shared\non: workflow_dispatch\njobs:\n  check:\n    runs-on: ubuntu-latest\n"
                  "    steps:\n      - uses: actions/setup-python@v6\n        with:\n          python-version: '3.12'\n")
        self.write(self.source, path, source)
        self.write(self.seed, path, source.replace("setup-python@v6", "setup-python@v7"))
        self.env["SYNC_ITEMS"] += f"\n{path}|{path}"
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("setup-python@v7", self.blob(path))
        self.assertNotIn("setup-python@v6", self.blob(path))

    def test_sync_does_not_enumerate_held_personal_repositories(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("user/repos", self.logs.read_text())

    def test_directory_sync_keeps_custom_issue_forms(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.blob(".github/ISSUE_TEMPLATE/bug.yml"), "shared issue form\n")
        self.assertEqual(self.blob(".github/ISSUE_TEMPLATE/local.yml"), "custom local issue form\n")

    def test_sync_preserves_repository_contribution_contracts(self):
        contracts = ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md")
        for path in contracts:
            self.write(self.source, path, "generic shared rules\n")
            self.write(self.seed, path, "repo-specific rules, naming and review requirements\n")
            self.env["SYNC_ITEMS"] += f"\n{path}|{path}"
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in contracts:
            self.assertEqual(self.blob(path), "repo-specific rules, naming and review requirements\n")

    def test_sync_seeds_missing_contribution_contracts(self):
        for path in ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"):
            self.write(self.source, path, "initial shared rules\n")
            self.env["SYNC_ITEMS"] += f"\n{path}|{path}"
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"):
            self.assertEqual(self.blob(path), "initial shared rules\n")

    def test_sync_preserves_case_variant_contribution_contracts(self):
        for path in ("agents.md", "contributing.md", ".github/PULL_REQUEST_TEMPLATE.md"):
            self.write(self.seed, path, "custom case-variant rules\n")
        for path in ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"):
            self.write(self.source, path, "generic shared rules\n")
            self.env["SYNC_ITEMS"] += f"\n{path}|{path}"
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in ("agents.md", "contributing.md", ".github/PULL_REQUEST_TEMPLATE.md"):
            self.assertEqual(self.blob(path), "custom case-variant rules\n")
        tracked = self.git("ls-tree", "-r", "--name-only", "main", cwd=self.bare).stdout.splitlines()
        for path in ("AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"):
            self.assertNotIn(path, tracked)

    def test_topics_failure_skips_before_clone_or_archive_change(self):
        result = self.run_sync(mode="topics_error", archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_untouched()

    def test_opted_out_archived_repo_is_not_unarchived_or_cloned(self):
        result = self.run_sync(topics="no-config-sync", archived=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_untouched()

    def test_org_enumeration_failure_aborts_before_changes(self):
        result = self.run_sync(mode="org_error")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_untouched()

    def test_personal_api_is_never_needed(self):
        result = self.run_sync(mode="personal_error")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("user/repos", self.logs.read_text())

    def test_wrong_source_owner_aborts_before_changes(self):
        self.env["GITHUB_REPOSITORY_OWNER"] = "held-account"
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_untouched()

    def test_unowned_api_result_is_not_cloned_or_mutated(self):
        fake = self.bin / "gh"
        fake.write_text(fake.read_text().replace('"login":"hongyime"', '"login":"held-account"'))
        result = self.run_sync(archived=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_untouched()

    def test_workflow_directory_preserves_pin_and_second_sync_is_idempotent(self):
        path = ".github/workflows/pinned.yml"
        shared = "jobs: {check: {steps: [{uses: actions/checkout@v6}]}}\n"
        self.write(self.source, path, shared)
        self.write(self.seed, path, shared.replace("@v6", "@" + "a" * 40))
        self.env["SYNC_ITEMS"] += "\n.github/workflows|.github/workflows"
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("@" + "a" * 40, self.blob(path))
        head = self.git("rev-parse", "main", cwd=self.bare).stdout
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout, head)

    def test_invalid_workflow_is_not_pushed_and_archive_is_restored(self):
        self.write(self.seed, ".github/workflows/lfs-guard.yml", "jobs: [invalid\n")
        self.update_fixture_commit()
        result = self.run_sync(archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertTrue(self.logs.read_text().rstrip().endswith("archived=true"))

    def test_keep_lfs_preserves_existing_lfs_policy(self):
        result = self.run_sync(topics="keep-lfs")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.blob(".gitattributes"), "app LFS attributes\n")
        self.assertEqual(self.blob(".github/workflows/lfs-guard.yml"), "name: app LFS policy\njobs: {}\n")
        self.assertEqual(self.blob("managed.txt"), "new shared config\n")

    def test_archived_repo_is_restored_after_success(self):
        result = self.run_sync(archived=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.logs.read_text()
        self.assertIn("archived=false", calls)
        self.assertTrue(calls.rstrip().endswith("archived=true"), calls)

    def test_push_failure_is_reported_and_archive_is_restored(self):
        result = self.run_sync(mode="push_error", archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertTrue(self.logs.read_text().rstrip().endswith("archived=true"))

    def assert_review_branch(self):
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertEqual(self.git("rev-parse", "chore/config-sync-1-1^", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertEqual(self.git("show", "-s", "--format=%B", "chore/config-sync-1-1", cwd=self.bare).stdout.strip(), "chore(config): sync from sourcerepo")
        self.assertEqual(self.git("show", "chore/config-sync-1-1:managed.txt", cwd=self.bare).stdout, "new shared config\n")
        for path, value in self.preserved.items():
            self.assertEqual(self.git("show", "chore/config-sync-1-1:" + path, cwd=self.bare).stdout, value)

    def test_protected_branch_uses_review_without_a_direct_push(self):
        result = self.run_sync(protected=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_review_branch()
        self.assertIn("pr create --repo hongyime/target", self.logs.read_text())
        self.assertNotIn("push origin HEAD:main", (self.base / "git-calls.txt").read_text())
        self.assertIn("Opened PR for target", result.stdout)

    def test_unprotected_direct_commit_keeps_existing_skip_policy(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("show", "-s", "--format=%B", "main", cwd=self.bare).stdout.strip(), self.env["COMMIT_MESSAGE"])
        self.assertNotIn("pr create", self.logs.read_text())

    def test_failed_direct_push_falls_back_to_runnable_review(self):
        result = self.run_sync(mode="main_push_error")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_review_branch()
        self.assertIn("pr create --repo hongyime/target", self.logs.read_text())

    def test_unreadable_protection_fails_before_clone_or_archive_change(self):
        result = self.run_sync(mode="protection_error", archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Cannot read branch protection", result.stderr)
        self.assert_untouched()

    def test_invalid_protection_fails_before_clone_or_archive_change(self):
        result = self.run_sync(mode="invalid_protection", archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Cannot read branch protection", result.stderr)
        self.assert_untouched()

    def test_pr_creation_failure_is_reported_and_archive_is_restored(self):
        result = self.run_sync(mode="pr_error", archived=True, protected=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_review_branch()
        self.assertIn("Review branch or PR creation failed", result.stderr)
        self.assertNotIn("Opened PR for target", result.stdout)
        self.assertTrue(self.logs.read_text().rstrip().endswith("archived=true"))

    def test_protected_review_push_failure_restores_archive(self):
        result = self.run_sync(mode="push_error", archived=True, protected=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Review branch or PR creation failed", result.stderr)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertNotIn("pr create", self.logs.read_text())
        self.assertTrue(self.logs.read_text().rstrip().endswith("archived=true"))

    def update_fixture_commit(self):
        self.git("add", "-A", cwd=self.seed)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture conflict", cwd=self.seed)
        self.git("push", str(self.bare), "main", cwd=self.seed)
        self.original_head = self.git("rev-parse", "main", cwd=self.bare).stdout.strip()

    def test_type_conflict_is_preserved_and_archive_restored(self):
        self.write(self.source, ".github/ISSUE_TEMPLATE/conflict.yml", "shared form\n")
        self.write(self.seed, ".github/ISSUE_TEMPLATE/conflict.yml/local.txt", "keep local directory\n")
        self.update_fixture_commit()
        result = self.run_sync(archived=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertEqual(self.blob(".github/ISSUE_TEMPLATE/conflict.yml/local.txt"), "keep local directory\n")
        self.assertTrue(self.logs.read_text().rstrip().endswith("archived=true"))

    @unittest.skipIf(os.name == "nt", "Native symlink preservation is verified by Linux CI")
    def test_linked_destination_does_not_overwrite_external_file(self):
        outside = self.base / "outside.txt"
        outside.write_text("preserve outside data\n")
        managed = self.seed / "managed.txt"
        managed.unlink()
        managed.symlink_to(outside)
        self.update_fixture_commit()
        result = self.run_sync()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(outside.read_text(), "preserve outside data\n")
        self.assertEqual(self.git("rev-parse", "main", cwd=self.bare).stdout.strip(), self.original_head)


if __name__ == "__main__":
    unittest.main()
