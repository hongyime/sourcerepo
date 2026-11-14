"""README discovery stays limited to supported workspace repository layouts."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.workspace import collect_readmes


class CollectReadmesTests(unittest.TestCase):
    def test_discovers_root_and_owner_nested_repositories(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            root_repo = workspace / "root-repo"
            nested_repo = workspace / "owner" / "nested-repo"
            ignored_repo = workspace / "Readme" / "ignored"
            for repo in (root_repo, nested_repo, ignored_repo):
                (repo / ".git").mkdir(parents=True)
            found = set(collect_readmes.repository_paths(workspace))
        self.assertEqual(found, {root_repo, nested_repo})


if __name__ == "__main__":
    unittest.main()
