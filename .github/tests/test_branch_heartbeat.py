import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
            for directory in sorted({e['path'].split('/')[0] for e in data['tree'] if '/' in e['path']}):
                self.trees[sha]['tree'].append({'path': directory, 'type': 'tree', 'mode': '040000', 'sha': 'subtree'})
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

    def test_opt_in_accepts_reviewed_directory_and_refuses_unsafe_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(heartbeat.CONFIG))
            heartbeat.validate_config(path)
            path.write_text(json.dumps({"version": 1, "rootDirectory": "web"}))
            self.assertEqual(heartbeat.validate_config(path), 'web')
            for value in [{"version": True, "rootDirectory": ""}, {"version": 2, "rootDirectory": ""},
                          {**heartbeat.CONFIG, "branch": "main"}, {}, None]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    heartbeat.validate_config(path)
            path.write_text("invalid json")
            with self.assertRaises(ValueError):
                heartbeat.validate_config(path)

    def test_nested_root_creates_both_disabled_configs_and_preserves_history(self):
        def run(timestamp):
            return heartbeat.heartbeat(self.api, 'owner/app', 'refs/heads/main', 'workflow_dispatch', timestamp, 'web')
        first = run('2026-09-12T06:00:00Z')
        files = {e['path']: e['content'] for m, p, d in self.api.calls if m == 'POST' and p == '/git/trees' for e in d['tree']}
        self.assertEqual(set(files), {'.prawn-heartbeat.json', 'vercel.json', 'web/vercel.json', 'last_sync.txt'})
        self.assertEqual(json.loads(files['.prawn-heartbeat.json'])['rootDirectory'], 'web')
        for name in ['vercel.json', 'web/vercel.json']:
            self.assertIs(json.loads(files[name])['git']['deploymentEnabled'], False)
        self.assertFalse(run('2026-09-12T06:00:00Z')['changed'])
        second = run('2026-09-19T06:00:00Z')
        self.assertEqual(self.api.commits[second['sha']]['parents'], [first['sha']])
        self.assertIs(self.api.calls[-1][2]['force'], False)

    def test_nested_config_tampering_directory_modes_or_root_change_refused(self):
        heartbeat.heartbeat(self.api, 'owner/app', 'refs/heads/main', 'workflow_dispatch', '2026-09-12T06:00:00Z', 'web')
        original = copy.deepcopy(self.api)
        for mutation in ['config', 'directory', 'extra', 'duplicate', 'changed-root']:
            with self.subTest(mutation=mutation):
                self.api = copy.deepcopy(original)
                entries = self.api.trees['1']['tree']
                if mutation == 'config':
                    next(e for e in entries if e['path'] == 'web/vercel.json')['sha'] = 'tampered'
                elif mutation == 'directory':
                    next(e for e in entries if e['path'] == 'web')['mode'] = '120000'
                elif mutation == 'extra':
                    entries.append({'path': 'web/app.js', 'type': 'blob', 'mode': '100644', 'sha': 'app'})
                elif mutation == 'duplicate':
                    entries[-1] = entries[0]
                self.api.calls.clear()
                with self.assertRaises(ValueError):
                    heartbeat.heartbeat(self.api, 'owner/app', 'refs/heads/main', 'workflow_dispatch', '2026-09-19T06:00:00Z', 'other' if mutation == 'changed-root' else 'web')
                self.assertEqual(self.api.ref, original.ref)
                self.assertTrue(all(m == 'GET' for m, _, _ in self.api.calls))

    def test_unsafe_roots_fail_before_any_api_request(self):
        for root in ['.', '..', '../web', '/web', 'C:/web', 'web/other', 'web\\other', '.git', '*', 'web ', None, False, 'x'*65]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                heartbeat.heartbeat(self.api, 'owner/app', 'refs/heads/main', 'workflow_dispatch', '2026-09-12T06:00:00Z', root)
        self.assertEqual(self.api.calls, [])

    def test_main_reads_the_nested_project_config_before_api_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'.github').mkdir()
            (root/'web').mkdir()
            (root/'.github/branch-heartbeat.json').write_text('{"version":1,"rootDirectory":"web"}')
            (root/'web/vercel.json').write_text('{"git":{"deploymentEnabled":{"automation/heartbeat":false}}}')
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch('sys.argv', ['heartbeat']), patch.dict(os.environ, {'GITHUB_REPOSITORY':'owner/app', 'GITHUB_REF':'refs/heads/main', 'GITHUB_EVENT_NAME':'workflow_dispatch', 'GITHUB_TOKEN':'synthetic'}), patch.object(heartbeat, 'GitHub', return_value=self.api):
                    heartbeat.main()
                    self.assertIsNotNone(self.api.ref)
                    self.api.calls.clear()
                    (root/'web/vercel.json').write_text('{"git":{"deploymentEnabled":true}}')
                    with self.assertRaises(ValueError):
                        heartbeat.main()
                    self.assertEqual(self.api.calls, [])
            finally:
                os.chdir(previous)

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
