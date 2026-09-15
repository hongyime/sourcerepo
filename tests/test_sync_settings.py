"""Run the workflow's actual settings script with an in-memory GitHub API."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/sync-repo-settings.yml").read_text(encoding="utf-8"))
SCRIPT = next(step["with"]["script"] for step in WORKFLOW["jobs"]["configure-repo-settings"]["steps"] if "script" in step.get("with", {}))
NODE = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const calls = [], failures = [];
const api = {repos: {listForOrg: 'org', listForAuthenticatedUser: 'personal', update: async payload => {
  calls.push(['update', payload]);
  if (input.failSettings && 'has_issues' in payload) throw Object.assign(new Error('fixture failure'), {status: 403});
}}};
const github = {rest: api, paginate: async (endpoint, options) => {
  calls.push(['list', endpoint, options]);
  if (endpoint !== 'org') throw new Error('Personal repository access is forbidden');
  return input.repos;
}};
const requireFixture = name => {
  if (name !== 'fs') throw new Error('Unexpected dependency');
  return {existsSync: () => true, readFileSync: () => JSON.stringify(input.settings)};
};
const fixtureConsole = {log: () => {}};
const core = {setFailed: message => failures.push(message)};
(async () => {
  try {
    await new (Object.getPrototypeOf(async function(){}).constructor)('github', 'require', 'console', 'core', input.script)(github, requireFixture, fixtureConsole, core);
  } catch (error) { failures.push(error.message); }
  process.stdout.write(JSON.stringify({calls, failures}));
})();
"""


def repo(name="app", owner="hongyime", **extra):
    return dict(name=name, owner={"login": owner}, archived=False, fork=False, disabled=False, private=True, **extra)


class SyncSettings(unittest.TestCase):
    def run_settings(self, repos=None, settings=None, owner="hongyime", include=True, fail=False):
        script = SCRIPT.replace("${{ github.repository_owner }}", owner).replace("${{ env.INCLUDE_ARCHIVED }}", str(include).lower())
        result = subprocess.run([shutil.which("node"), "-e", NODE], input=json.dumps({
            "script": script, "repos": repos or [repo()], "settings": settings or {}, "failSettings": fail
        }), text=True, capture_output=True, timeout=15, check=True)
        return json.loads(result.stdout)

    def test_only_owned_non_fork_enabled_repositories_are_mutated(self):
        repos = [repo(), repo("held", "held-account"), repo("foreign", "someone")]
        repos += [{**repo("fork"), "fork": True}, {**repo("disabled"), "disabled": True}]
        result = self.run_settings(repos)
        self.assertEqual(result["failures"], [])
        self.assertEqual([c[1] for c in result["calls"] if c[0] == "list"], ["org"])
        self.assertEqual([c[1]["repo"] for c in result["calls"] if c[0] == "update"], ["app"])

    def test_missing_or_invalid_visibility_is_omitted(self):
        for value in (None, "internal", ""):
            configured = {} if value is None else {"visibility": value}
            result = self.run_settings(settings={"hongyime/app": configured})
            self.assertEqual(result["failures"], [])
            self.assertNotIn("private", next(c[1] for c in result["calls"] if c[0] == "update"))

    def test_explicit_visibility_and_metadata_are_retained(self):
        for visibility in ("public", "private"):
            result = self.run_settings(settings={"hongyime/app": {"visibility": visibility, "description": "configured", "homepage": "https://example.invalid"}})
            payload = next(c[1] for c in result["calls"] if c[0] == "update")
            self.assertEqual(payload["private"], visibility == "private")
            self.assertEqual(payload["description"], "configured")
            self.assertEqual(payload["homepage"], "https://example.invalid")

    def test_archive_flag_and_restoration_after_failed_settings(self):
        archived = [{**repo(), "archived": True}]
        skipped = self.run_settings(archived, include=False)
        self.assertFalse(any(c[0] == "update" for c in skipped["calls"]))
        result = self.run_settings(archived, fail=True)
        updates = [c[1] for c in result["calls"] if c[0] == "update"]
        self.assertFalse(updates[0]["archived"])
        self.assertTrue(updates[-1]["archived"])

    def test_wrong_source_owner_fails_before_api_calls(self):
        result = self.run_settings(owner="held-account")
        self.assertEqual(result["calls"], [])
        self.assertTrue(result["failures"])

    def test_all_mutating_jobs_are_owner_guarded_and_secret_scope_is_owned(self):
        for job in WORKFLOW["jobs"].values():
            self.assertEqual(job["if"], "github.repository_owner == 'hongyime'")
        secret_step = next(s["run"] for s in WORKFLOW["jobs"]["propagate-secrets"]["steps"] if "gh secret set" in s.get("run", ""))
        self.assertNotIn("user/repos", secret_step)
        self.assertIn('orgs/hongyime/repos?', secret_step)
        self.assertIn('^hongyime/[A-Za-z0-9_.-]+$', secret_step)
        self.assertIn('.fork==false', secret_step)
        # Query assignment must finish before the mutation loop begins.
        self.assertLess(secret_step.index('REPOS="$('), secret_step.index('while IFS='))


if __name__ == "__main__":
    unittest.main()
