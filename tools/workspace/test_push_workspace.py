"""Directly runnable regressions for the workspace push helper."""
from __future__ import annotations

import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.workspace import push_workspace as push


class PushWorkspaceTests(unittest.TestCase):
    def test_default_command_timeout_is_thirty_seconds(self):
        output = io.StringIO()
        with (
            patch.object(push.sys, "argv", ["push_workspace.py", "--personal-owner", "owner"]),
            patch.object(push, "iter_git_repos", return_value=[Path("repo")]),
            patch.object(push, "status", return_value=("clean", "owner/repo")) as status,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(push.main(), 0)
        self.assertEqual(status.call_args.args[2], 30)


if __name__ == "__main__":
    unittest.main()
