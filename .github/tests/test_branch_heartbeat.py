import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("heartbeat", ROOT / ".github/scripts/branch-heartbeat.py")
heartbeat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heartbeat)


class FakeGitHub:
    """Model the Git tree/ref operations, including non-fast-forward refusal."""
    def __init__(self):
        self.info = {"default_branch": "main", "full_name": "owner/app"}
        self.ref = None
        self.calls = []
        self.trees = {}
        self.commits = {}
        self.race = False

    def request(self, path, data=None, method="GET"):
        self.calls.append((method, path, copy.deepcopy(data)))
        if method == "GET":
            if path == "":
                return copy.deepcopy(self.info)
            if path == "/git/ref/heads/automation/heartbeat":
                return copy.deepcopy(self.ref)
            if path.startswith("/git/commits/"):
                return copy.deepcopy(self.commits[path.split("/")[-1]])
            if path.startswith("/git/trees/"):
                return copy.deepcopy(self.trees[path.split("/")[-1].split("?")[0]])
        if path == "/git/trees" and method == "POST":
            sha = str(len(self.trees) + 1)
            self.trees[sha] = {"truncated": False, "tree": [
                {"path": e["path"], "type": e["type"], "mode": e["mode"],
                 "sha": heartbeat.blob_sha(e["content"])} for e in data["tree"]]}
            return {"sha": sha}
        if path == "/git/commits" and method == "POST":
            sha = "commit" + str(len(self.commits) + 1)
            self.commits[sha] = {"tree": {"sha": data["tree"]}, "parents": data["parents"]}
            return {"sha": sha}
        if path == "/git/refs" and method == "POST":
            if self.ref or self.race:
                raise RuntimeError("Ref already exists")
            self.ref = {"ref": data["ref"], "object": {"type": "commit", "sha": data["sha"]}}
            return self.ref
        if path == "/git/refs/heads/automation/heartbeat" and method == "PATCH":
            if self.race or data["force"] is not False or self.commits[data["sha"]]["parents"] != [self.ref["object"]["sha"]]:
                raise RuntimeError("Non-fast-forward")
            self.ref["object"]["sha"] = data["sha"]
            return self.ref
        raise AssertionError((method, path, data))


class BranchHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()

    def run_heartbeat(self, timestamp="2026-09-12T06:00:00Z", ref="refs/heads/main", event="workflow_dispatch"):
        return heartbeat.heartbeat(self.api, "owner/app", ref, event, timestamp)

    def test_creates_only_three_files_on_separate_history(self):
        result = self.run_heartbeat()
        self.assertTrue(result["changed"])
        commit = self.api.commits[result["sha"]]
        self.assertEqual(commit["parents"], [])
        writes = [(p, d) for m, p, d in self.api.calls if m != "GET"]
        files = {e["path"]: e["content"] for e in writes[0][1]["tree"]}
        self.assertEqual(set(files), {"last_sync.txt", "vercel.json", ".prawn-heartbeat.json"})
        self.assertIs(json.loads(files["vercel.json"])["git"]["deploymentEnabled"], False)
        self.assertEqual(writes[-1][1]["ref"], "refs/heads/automation/heartbeat")
        self.assertFalse(any("/actions/" in p for _, p, _ in self.api.calls))

    def test_update_preserves_previous_commit_and_never_forces(self):
        first = self.run_heartbeat()["sha"]
        second = self.run_heartbeat("2026-09-19T06:00:00Z")["sha"]
        self.assertEqual(self.api.commits[second]["parents"], [first])
        self.assertIs(self.api.calls[-1][2]["force"], False)

    def test_same_timestamp_is_idempotent(self):
        self.run_heartbeat()
        self.api.calls.clear()
        self.assertFalse(self.run_heartbeat()["changed"])
        self.assertTrue(all(m == "GET" for m, _, _ in self.api.calls))

    def test_wrong_repository_default_branch_ref_or_event_refused_before_writing(self):
        for field, value in [("full_name", "owner/other"), ("default_branch", heartbeat.BRANCH)]:
            with self.subTest(field=field):
                self.api = FakeGitHub()
                self.api.info[field] = value
                with self.assertRaises(ValueError):
                    self.run_heartbeat()
                self.assertTrue(all(m == "GET" for m, _, _ in self.api.calls))
        self.api = FakeGitHub()
        for ref, event in [("refs/heads/untrusted", "workflow_dispatch"), ("refs/heads/main", "pull_request")]:
            with self.assertRaises(ValueError):
                self.run_heartbeat(ref=ref, event=event)

    def test_existing_branch_collision_and_tampering_preserve_ref(self):
        self.run_heartbeat()
        original = copy.deepcopy(self.api)
        for mutation in ("extra", "missing", "duplicate", "symlink", "owner", "deployment", "truncated"):
            with self.subTest(mutation=mutation):
                self.api = copy.deepcopy(original)
                tree = self.api.trees["1"]
                if mutation == "extra":
                    tree["tree"].append({"path": "application.ts", "type": "blob", "mode": "100644", "sha": "app"})
                elif mutation == "missing":
                    tree["tree"].pop()
                elif mutation == "duplicate":
                    tree["tree"][2] = tree["tree"][0]
                elif mutation == "symlink":
                    tree["tree"][0]["mode"] = "120000"
                elif mutation == "truncated":
                    tree["truncated"] = True
                else:
                    tree["tree"][0 if mutation == "owner" else 1]["sha"] = "unowned"
                self.api.calls.clear()
                with self.assertRaises(ValueError):
                    self.run_heartbeat("2026-09-19T06:00:00Z")
                self.assertEqual(self.api.ref, original.ref)
                self.assertTrue(all(m == "GET" for m, _, _ in self.api.calls))

    def test_concurrent_creation_and_update_fail_without_overwrite(self):
        self.api.race = True
        with self.assertRaises(RuntimeError):
            self.run_heartbeat()
        self.assertIsNone(self.api.ref)
        self.api = FakeGitHub()
        self.run_heartbeat()
        original = copy.deepcopy(self.api.ref)
        self.api.race = True
        with self.assertRaises(RuntimeError):
            self.run_heartbeat("2026-09-19T06:00:00Z")
        self.assertEqual(self.api.ref, original)

    def test_opt_in_refuses_nested_roots_unknown_fields_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(heartbeat.CONFIG))
            heartbeat.validate_config(path)
            for value in [{"version": 1, "rootDirectory": "web"}, {"version": 2, "rootDirectory": ""},
                          {**heartbeat.CONFIG, "branch": "main"}, {}, None]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    heartbeat.validate_config(path)
            path.write_text("invalid json")
            with self.assertRaises(ValueError):
                heartbeat.validate_config(path)

    def test_shared_sync_selects_only_the_opted_in_heartbeat(self):
        source = (ROOT / ".github/scripts/sync-selected-paths.sh").read_text()
        start = source.index('    EFFECTIVE_SYNC_ITEMS="${EFFECTIVE_SYNC_ITEMS/.github')
        end = source.index("\n  fi", start)
        snippet = source[start:end]
        shell = "C:/Program Files/Git/bin/bash.exe" if Path("C:/Program Files/Git/bin/bash.exe").exists() else shutil.which("bash")
        self.assertIsNotNone(shell)
        original = ".github/workflows/heartbeat.yml|.github/workflows/heartbeat.yml\n.github/workflows/codeql.yml|.github/workflows/codeql.yml"
        result = subprocess.run([shell, "-c", snippet + '\nprintf "%s" "$EFFECTIVE_SYNC_ITEMS"'], env={**os.environ, "EFFECTIVE_SYNC_ITEMS": original}, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [
            ".github/workflow-templates/branch-heartbeat.yml|.github/workflows/heartbeat.yml",
            ".github/workflows/codeql.yml|.github/workflows/codeql.yml",
            ".github/scripts/branch-heartbeat.py|.github/scripts/branch-heartbeat.py"])

    def test_main_vercel_config_must_disable_heartbeat_without_true_wildcards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vercel.json"
            path.write_text(json.dumps({"git": {"deploymentEnabled": {heartbeat.BRANCH: False}}}))
            heartbeat.validate_vercel(path)
            for value in [True, False, {}, {heartbeat.BRANCH: True}, {heartbeat.BRANCH: False, "*": True}]:
                path.write_text(json.dumps({"git": {"deploymentEnabled": value}}))
                with self.assertRaises(ValueError):
                    heartbeat.validate_vercel(path)


if __name__ == "__main__":
    unittest.main()
