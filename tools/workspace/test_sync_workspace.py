"""Regression checks for safe sync decisions and progress reporting."""

import contextlib
import io
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_workspace as sync


def completed(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class SafeSyncTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows Git launches a child process")
    def test_timeout_stops_children_holding_output_pipes(self):
        child = "import time; time.sleep(30)"
        parent = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "time.sleep(30)"
        )
        started = time.monotonic()
        result = sync.run([sys.executable, "-c", parent], timeout=1)
        self.assertEqual(result.returncode, 124)
        # Allow the bounded 5s tree cleanup + 5s pipe drain and Windows startup.
        self.assertLess(time.monotonic() - started, 15)

    def sync_with(self, results):
        with patch.object(sync, "run", side_effect=results) as run:
            result = sync.sync_existing(Path("repo"), "owner/repo", False, 8, False)
        return result, run

    def test_branch_timeout_is_a_failure_not_detached(self):
        result, run = self.sync_with([completed(code=124)])
        self.assertIn("branch check failed", result)
        self.assertIn("timed out", result)
        self.assertEqual(run.call_count, 1)

    def test_detached_head_is_left_untouched(self):
        result, run = self.sync_with([completed(code=1)])
        self.assertEqual(result, "skip detached")
        self.assertEqual(run.call_count, 1)

    def test_empty_remote_has_no_branch_to_update(self):
        result, run = self.sync_with([completed("main\n"), completed(), completed(code=1)])
        self.assertEqual(result, "skip no origin/main")
        self.assertEqual(run.call_count, 3)

    def test_status_timeout_is_a_failure_not_dirty(self):
        result, run = self.sync_with([
            completed("main\n"), completed(), completed("abc\n"), completed(code=124),
        ])
        self.assertIn("status check failed", result)
        self.assertEqual(run.call_count, 4)

    def test_remote_check_timeout_is_not_a_missing_branch(self):
        result, run = self.sync_with([completed("main\n"), completed(), completed(code=124)])
        self.assertIn("remote branch check failed", result)
        self.assertEqual(run.call_count, 3)

    def test_dirty_repo_is_fetched_but_never_merged(self):
        result, run = self.sync_with([
            completed("main\n"), completed(), completed("abc\n"), completed(" M app.py\n"),
        ])
        self.assertEqual(result, "skip dirty")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["git", "fetch", "--no-auto-maintenance", "origin"], commands)
        self.assertFalse(any("merge" in command for command in commands))

    def test_clean_behind_repo_fast_forwards(self):
        result, run = self.sync_with([
            completed("main\n"), completed(), completed("abc\n"), completed(),
            completed("0\n"), completed("3\n"), completed(),
        ])
        self.assertEqual(result, "updated")
        self.assertEqual(run.call_args.args[0], ["git", "-c", "maintenance.auto=false", "merge", "--ff-only", "origin/main"])

    def test_failed_fast_forward_is_not_mislabeled_as_divergence(self):
        result, _ = self.sync_with([
            completed("main\n"), completed(), completed("abc\n"), completed(),
            completed("0\n"), completed("3\n"), completed(code=128),
        ])
        self.assertIn("fast-forward failed", result)

    def test_diverged_repo_is_left_untouched(self):
        result, run = self.sync_with([
            completed("main\n"), completed(), completed("abc\n"), completed(),
            completed("2\n"), completed("3\n"),
        ])
        self.assertEqual(result, "skip not fast-forward")
        self.assertEqual(run.call_count, 6)

    def test_main_shows_progress_before_fetch_and_exits_nonzero_on_failure(self):
        output = io.StringIO()

        def failing_sync(*args):
            self.assertIn("[1/1] Checking owner/repo", output.getvalue())
            return "fetch failed (exit 128)"

        with (
            patch.object(sync.sys, "argv", ["sync_workspace.py", "--workspace", "."]),
            patch.object(sync, "remote_repos", return_value=[{"full_name": "owner/repo"}]),
            patch.object(sync, "local_repos", return_value={"owner/repo": Path("repo")}),
            patch.object(sync, "sync_existing", side_effect=failing_sync),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(sync.main(), 1)
        self.assertIn("Failed: 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
