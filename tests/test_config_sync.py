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
            "GIT_TERMINAL_PROMPT": "0", "GITHUB_REPOSITORY_OWNER": "fixture",
            "GITHUB_REPOSITORY": "fixture/source", "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
            "SYNC_ITEMS": "managed.txt|managed.txt\n.github/ISSUE_TEMPLATE|.github/ISSUE_TEMPLATE\n.gitattributes|.gitattributes\n.github/workflows/lfs-guard.yml|.github/workflows/lfs-guard.yml",
            "COMMIT_MESSAGE": "chore(config): fixture sync [skip ci]",
            "PR_TITLE": "fixture", "PR_BODY": "fixture", "INCLUDE_ARCHIVED": "true",
            "PRAWN_REAL_GIT": Path(real_git).as_posix(), "PRAWN_BARE_REPO": self.bare.as_posix(),
            "PRAWN_GH_LOG": self.logs.as_posix(), "PRAWN_TEST_MODE": "normal",
            "PRAWN_TEST_TOPICS": "", "PRAWN_TEST_ARCHIVED": "false",
            "PRAWN_TEST_PROTECTED": "false", "PRAWN_GIT_LOG": (self.base / "git-calls.txt").as_posix(),
        })
        script = Path(os.environ.get("PRAWN_CONFIG_SYNC_SCRIPT", ROOT / ".github/scripts/sync-selected-paths.sh"))
        self.script = self.source / "sync.sh"
        self.script.write_text(script.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        for name, value in {
            "managed.txt": "new shared config\n",
            ".github/ISSUE_TEMPLATE/bug.yml": "shared issue form\n",
            ".gitattributes": "shared attributes\n",
            ".github/workflows/lfs-guard.yml": "shared LFS guard\n",
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
                            ".github/workflows/lfs-guard.yml": "app LFS policy\n"}.items():
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
      printf '[{"name":"target","full_name":"fixture/target","owner":{"login":"fixture"},"archived":%s,"disabled":false,"fork":false,"default_branch":"main"}]\\n' "$PRAWN_TEST_ARCHIVED"
    elif [[ "$3" == user/repos* ]]; then
      [ "$PRAWN_TEST_MODE" != personal_error ] || exit 72
      printf '[]\\n'
    else exit 90; fi ;;
  'api repos/fixture/target/topics')
    [ "$PRAWN_TEST_MODE" != topics_error ] || exit 73
    printf '%s\\n' "$PRAWN_TEST_TOPICS" ;;
  'api repos/fixture/target/branches/main')
    [ "$PRAWN_TEST_MODE" != protection_error ] || exit 76
    if [ "$PRAWN_TEST_MODE" = invalid_protection ]; then printf 'unknown\\n'
    else printf '%s\\n' "$PRAWN_TEST_PROTECTED"; fi ;;
  'api -X')
    [ "$3" = PATCH ] && [ "$4" = repos/fixture/target ] || exit 91
    case "$6" in archived=true|archived=false) exit 0;; *) exit 92;; esac ;;
  'repo clone')
    [ "$3" = fixture/target ] || exit 93
    exec "$PRAWN_REAL_GIT" clone "$PRAWN_BARE_REPO" "$4" ;;
  'pr create')
    [ "$PRAWN_TEST_MODE" != pr_error ] || exit 77
    printf 'https://github.com/fixture/target/pull/1\\n' ;;
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

    def test_directory_sync_keeps_custom_issue_forms(self):
        result = self.run_sync()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.blob(".github/ISSUE_TEMPLATE/bug.yml"), "shared issue form\n")
        self.assertEqual(self.blob(".github/ISSUE_TEMPLATE/local.yml"), "custom local issue form\n")

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

    def test_personal_enumeration_failure_aborts_before_changes(self):
        result = self.run_sync(mode="personal_error")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assert_untouched()

    def test_keep_lfs_preserves_existing_lfs_policy(self):
        result = self.run_sync(topics="keep-lfs")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.blob(".gitattributes"), "app LFS attributes\n")
        self.assertEqual(self.blob(".github/workflows/lfs-guard.yml"), "app LFS policy\n")
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
        self.assertEqual(self.git("rev-parse", "sync-1-1^", cwd=self.bare).stdout.strip(), self.original_head)
        self.assertEqual(self.git("show", "-s", "--format=%B", "sync-1-1", cwd=self.bare).stdout.strip(), "chore(config): sync from sourcerepo")
        self.assertEqual(self.git("show", "sync-1-1:managed.txt", cwd=self.bare).stdout, "new shared config\n")
        for path, value in self.preserved.items():
            self.assertEqual(self.git("show", "sync-1-1:" + path, cwd=self.bare).stdout, value)

    def test_protected_branch_uses_review_without_a_direct_push(self):
        result = self.run_sync(protected=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_review_branch()
        self.assertIn("pr create --repo fixture/target", self.logs.read_text())
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
        self.assertIn("pr create --repo fixture/target", self.logs.read_text())

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
