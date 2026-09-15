"""Offline inventory and publication regressions; hosted fixtures use only local Git."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('reconcile_repos', ROOT / 'tools/reconcile_repos.py')
reconcile = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reconcile
SPEC.loader.exec_module(reconcile)


def inventory(name: str, **kwargs):
    return {'full_name': name, 'description': '', 'homepage': '', 'topics': [], **kwargs}


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='prawn-catalog-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.repos = self.root / 'repos.yml'
        self.tiers = self.root / 'tiers.yml'
        self.topics = self.root / 'topics.yml'
        self.live = self.root / 'live.json'
        self.report = self.root / 'report.txt'
        self.repos.write_text('hongyime/retained:\n  description: "keep"\n  topics: []\nforeign/preserved:\n  topics: []\n')
        self.tiers.write_text('external:\n  - foreign/preserved\narchived:\nstandard:\n  - hongyime/retained\n')
        self.topics.write_text('topics:\n  - python\nreserved:\n  - keep-lfs\n')
        self.before = (self.repos.read_bytes(), self.tiers.read_bytes())
        self.runner = patch.object(reconcile, 'run', side_effect=AssertionError('No real GitHub requests'))
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def apply(self, live, write=True):
        self.live.write_text(json.dumps(live))
        args = ['--org-owner', 'hongyime', '--repos-yml', str(self.repos), '--tiers-yml', str(self.tiers),
                '--topics-yml', str(self.topics), '--live-json', str(self.live), '--report', str(self.report)]
        if write:
            args.append('--write')
        return reconcile.main(args)

    def test_discovery_calls_only_the_owned_org(self):
        with patch.object(reconcile, 'api_json', return_value=[inventory('hongyime/live'), inventory('foreign/no'), inventory('hongyime/disabled', disabled=True)]) as api:
            self.assertEqual(set(reconcile.discover_live_repos('hongyime')), {'hongyime/live'})
            api.assert_called_once_with('orgs/hongyime/repos?per_page=100')

    def test_foreign_owner_fails_before_discovery_or_file_reads(self):
        with patch.object(reconcile, 'api_json') as api, self.assertRaises(ValueError):
            reconcile.discover_live_repos('foreign')
        api.assert_not_called()
        with self.assertRaises(SystemExit) as error:
            reconcile.main(['--org-owner', 'foreign'])
        self.assertEqual(error.exception.code, 2)

    def test_multiple_json_pages_are_retained(self):
        pages = json.dumps([inventory('hongyime/a')]) + '\n' + json.dumps([inventory('hongyime/b')])
        with patch.object(reconcile, 'run', return_value=pages):
            self.assertEqual(len(reconcile.api_json('fixture')), 2)

    def test_malformed_or_missing_api_pages_fail(self):
        for response in ('', '{}', '[null]', '[]\n{}', 'invalid'):
            with self.subTest(response=response), patch.object(reconcile, 'run', return_value=response), self.assertRaises(ValueError):
                reconcile.api_json('fixture')

    def test_only_eligible_owned_repositories_are_added(self):
        self.apply([inventory('hongyime/active'), inventory('hongyime/archive', archived=True),
                    inventory('foreign/new'), inventory('hongyime/fork', fork=True), inventory('hongyime/disabled', disabled=True)])
        catalog = yaml.safe_load(self.repos.read_text())
        tiers = yaml.safe_load(self.tiers.read_text())
        self.assertEqual(set(catalog), {'hongyime/retained', 'foreign/preserved', 'hongyime/active', 'hongyime/archive'})
        self.assertIn('hongyime/archive', tiers['archived'])
        self.assertIn('hongyime/active', tiers['standard'])
        self.assertNotIn('foreign/', self.report.read_text())

    def test_unavailable_entries_and_foreign_records_are_preserved(self):
        self.apply([])
        self.assertEqual((self.repos.read_bytes(), self.tiers.read_bytes()), self.before)
        self.assertIn('hongyime/retained', self.report.read_text())
        self.assertIn('does not establish deletion', self.report.read_text())

    def test_empty_topics_are_an_array_and_metadata_escaping_survives(self):
        description = 'Hash # quotes " Unicode 雨\nnext line'
        self.apply([inventory('hongyime/new', description=description, topics=['not-allowed'])])
        entry = yaml.safe_load(self.repos.read_text())['hongyime/new']
        self.assertEqual(entry['topics'], [])
        self.assertEqual(entry['description'], description)

    def test_allowed_topics_and_private_marker_are_preserved(self):
        self.apply([inventory('hongyime/new', private=True, topics=['python', 'keep-lfs', 'not-allowed'])])
        entry = yaml.safe_load(self.repos.read_text())['hongyime/new']
        self.assertEqual(entry['topics'], ['python', 'keep-lfs'])
        self.assertEqual(entry['visibility'], 'private')

    def test_repeated_inventory_does_not_rewrite_catalogs(self):
        live = [inventory('hongyime/new')]
        self.apply(live)
        first = (self.repos.read_bytes(), self.tiers.read_bytes())
        self.apply(live)
        self.assertEqual((self.repos.read_bytes(), self.tiers.read_bytes()), first)
        self.assertIn('No registration changes are needed', self.report.read_text())

    def test_read_only_mode_leaves_catalog_bytes_unchanged(self):
        self.apply([inventory('hongyime/new')], write=False)
        self.assertEqual((self.repos.read_bytes(), self.tiers.read_bytes()), self.before)

    def test_malformed_fixture_fails_before_any_write(self):
        for fixture in ({}, [None], [{}]):
            with self.subTest(fixture=fixture), self.assertRaises((ValueError, KeyError)):
                self.apply(fixture)
            self.assertEqual((self.repos.read_bytes(), self.tiers.read_bytes()), self.before)

    def test_generated_report_follows_the_repository_template(self):
        self.apply([inventory('hongyime/new')])
        report = self.report.read_text()
        for heading in ('## Summary', '## Changes', '## Testing', '## Checklist'):
            self.assertEqual(report.count(heading), 1)
        self.assertIn('must be reviewed before merge', report)
        self.assertNotIn('- [x]', report)


@unittest.skipIf(os.name == 'nt', 'Real Bash/Git publication fixtures run on hosted Linux')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='prawn-reconciliation-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.repo = self.root / 'source with spaces'
        self.repo.mkdir()
        for directory in (self.repo / '.github', self.repo / 'tools', self.root / 'bin', self.root / 'tmp'):
            directory.mkdir()
        shutil.copy2(ROOT / 'tools/reconcile_repos.py', self.repo / 'tools/reconcile_repos.py')
        (self.repo / 'repos.yml').write_text('hongyime/retained:\n  topics: []\n')
        (self.repo / 'tiers.yml').write_text('external:\narchived:\nstandard:\n  - hongyime/retained\n')
        (self.repo / 'topics.yml').write_text('topics:\n  - python\n')
        self.calls = self.root / 'gh-calls.jsonl'
        self.prs = self.root / 'prs.json'
        self.live = self.root / 'live.json'
        self.prs.write_text('[[]]')
        self.live.write_text(json.dumps([inventory('hongyime/retained'), inventory('hongyime/new')]))
        self.output = self.root / 'output.txt'
        self.env = {key: value for key, value in os.environ.items() if key in {'PATH', 'TMP', 'TEMP', 'SYSTEMROOT'}}
        self.env.update({'PATH': str(self.root / 'bin') + os.pathsep + os.environ['PATH'],
            'GIT_CONFIG_GLOBAL': str(self.root / 'gitconfig'), 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ALLOW_PROTOCOL': 'file',
            'GIT_TERMINAL_PROMPT': '0', 'GITHUB_REPOSITORY': 'hongyime/sourcerepo', 'GITHUB_REPOSITORY_OWNER': 'hongyime',
            'DEFAULT_BRANCH': 'main', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2', 'RUNNER_TEMP': str(self.root / 'tmp'),
            'GITHUB_OUTPUT': str(self.output), 'PRAWN_FAKE_PRS': str(self.prs), 'PRAWN_FAKE_LIVE': str(self.live),
            'PRAWN_GH_CALLS': str(self.calls)})
        fake = self.root / 'bin/gh'
        fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['PRAWN_GH_CALLS'], 'a') as stream:
    stream.write(json.dumps(args) + '\\n')
if os.environ.get('PRAWN_FAKE_API_FAIL') == '1':
    raise SystemExit(71)
if args == ['api', '--paginate', '--slurp', 'repos/hongyime/sourcerepo/pulls?state=open&per_page=100']:
    print(pathlib.Path(os.environ['PRAWN_FAKE_PRS']).read_text())
elif args == ['api', '--paginate', 'orgs/hongyime/repos?per_page=100']:
    print(pathlib.Path(os.environ['PRAWN_FAKE_LIVE']).read_text())
elif args[:2] == ['pr', 'create']:
    body = pathlib.Path(args[args.index('--body-file') + 1]).read_text()
    pathlib.Path(os.environ['PRAWN_GH_CALLS'] + '.body').write_text(body)
else:
    raise SystemExit(72)
''')
        fake.chmod(0o755)
        self.git('init', '--initial-branch=main')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', '.')
        self.git('commit', '-m', 'chore: seed fixture')
        self.before = self.git('rev-parse', 'HEAD').stdout.strip()
        self.bare = self.root / 'remote.git'
        self.git('clone', '--bare', str(self.repo), str(self.bare))
        self.git('remote', 'add', 'origin', str(self.bare))
        doc = yaml.safe_load((ROOT / '.github/workflows/repo-reconcile.yml').read_text())
        steps = doc['jobs']['reconcile']['steps']
        self.review, self.plan, self.publish = [step for step in steps if 'run' in step]
        self.assertEqual(self.plan['if'], "steps.review.outputs.pending == 'false'")
        self.assertEqual(self.publish['if'], "steps.review.outputs.pending == 'false'")

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True, timeout=30)

    def step(self, step):
        return subprocess.run(['bash', '-c', step['run']], cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=45)

    def execute(self):
        review = self.step(self.review)
        if review.returncode:
            return review
        if 'pending=true' in self.output.read_text():
            return review
        plan = self.step(self.plan)
        return self.step(self.publish) if plan.returncode == 0 else plan

    def test_existing_reviews_on_later_pages_are_preserved(self):
        for branch in ('chore/reconcile-repos', 'shell/reconcile-repos', 'chore/reconcile-repos-11-2'):
            with self.subTest(branch=branch):
                self.output.write_text('')
                self.prs.write_text(json.dumps([[], [{'head': {'ref': branch, 'repo': {'full_name': 'hongyime/sourcerepo'}}}]]))
                result = self.execute()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('pending=true', self.output.read_text())
                self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)
                self.assertEqual(self.git('status', '--porcelain').stdout, '')
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(all(call[:3] == ['api', '--paginate', '--slurp'] for call in calls))

    def test_new_owned_entry_publishes_a_conventional_branch(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        branch = 'chore/reconcile-repos-123-2'
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), branch)
        self.assertEqual(self.git('log', '-1', '--format=%s').stdout.strip(), 'chore(shell): reconcile repo metadata')
        self.assertEqual(set(self.git('diff', '--name-only', self.before, 'HEAD').stdout.splitlines()), {'repos.yml', 'tiers.yml'})
        self.assertEqual(self.git('--git-dir', str(self.bare), 'rev-parse', 'main').stdout.strip(), self.before)
        self.assertEqual(self.git('--git-dir', str(self.bare), 'rev-parse', branch).stdout.strip(), self.git('rev-parse', 'HEAD').stdout.strip())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertEqual(calls[-1][:2], ['pr', 'create'])
        self.assertIn(branch, calls[-1])
        self.assertEqual(calls[-1][calls[-1].index('--base') + 1], 'main')
        body = Path(str(self.calls) + '.body').read_text()
        self.assertIn('## Checklist', body)
        self.assertFalse(any(call[:2] in (['pr', 'close'], ['pr', 'edit']) for call in calls))

    def test_no_changes_never_closes_reviews_or_creates_branches(self):
        self.live.write_text(json.dumps([inventory('hongyime/retained')]))
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'main')
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(all(call[0] == 'api' for call in calls))

    def test_api_failure_stops_before_catalog_or_git_changes(self):
        self.env['PRAWN_FAKE_API_FAIL'] = '1'
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('status', '--porcelain').stdout, '')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)

    def test_malformed_pr_inventory_stops_before_writes(self):
        for data in ({}, [[{'head': {}}]]):
            with self.subTest(data=data):
                self.prs.write_text(json.dumps(data))
                result = self.execute()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git('status', '--porcelain').stdout, '')

    def test_invalid_run_identifier_is_not_published(self):
        self.env['GITHUB_RUN_ID'] = 'invalid;command'
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'main')
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), self.before)

    def test_fork_pr_does_not_claim_the_owned_review_branch(self):
        self.prs.write_text(json.dumps([[{'head': {'ref': 'chore/reconcile-repos', 'repo': {'full_name': 'foreign/fork'}}}]]))
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pending=false', self.output.read_text())
        self.assertEqual(self.git('branch', '--show-current').stdout.strip(), 'chore/reconcile-repos-123-2')


if __name__ == '__main__':
    unittest.main()
