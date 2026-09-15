import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('gate', Path(__file__).parents[1] / 'scripts/checked-bot-merge.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class MergePolicyTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'state': 'open', 'draft': False, 'user': {'login': 'dependabot[bot]'}, 'head': {'sha': 'a' * 40, 'repo': {'full_name': 'owner/app'}}, 'base': {'ref': 'main', 'repo': {'full_name': 'owner/app', 'default_branch': 'main'}}}
        self.pr.update(mergeable=True, mergeable_state='clean')
        self.build = {'name': 'Build', 'workflow': 'Build Check', 'bucket': 'pass', 'state': 'SUCCESS'}
        self.required = [self.build]
        self.checks = [self.build, {'name': 'Vercel', 'bucket': 'pass', 'state': 'SUCCESS'}]

    def decide(self):
        return gate.decision(self.pr, self.required, self.checks, 'a' * 40, gate.BOTS['dependabot'])

    def test_passes_only_with_required_successful_build(self):
        self.assertIsNone(self.decide())

    def test_no_required_checks_defers(self):
        self.required = []
        self.assertIsNotNone(self.decide())

    def test_missing_or_wrong_workflow_build_defers(self):
        for required in [[{'name': 'guard', 'bucket': 'pass'}], [{'name': 'Build', 'workflow': 'Unrelated', 'bucket': 'pass'}]]:
            self.required = required
            self.assertIsNotNone(self.decide())

    def test_every_unsuccessful_required_state_defers(self):
        for state in ['pending', 'fail', 'cancel', 'skipping', None]:
            self.required = [dict(self.build, bucket=state)]
            self.assertIsNotNone(self.decide())

    def test_pending_or_failed_external_check_defers(self):
        for state in ['pending', 'fail', 'cancel', None]:
            self.checks[-1]['bucket'] = state
            self.assertIsNotNone(self.decide())

    def test_optional_skipped_check_allowed(self):
        self.checks.append({'name': 'label', 'bucket': 'skipping'})
        self.assertIsNone(self.decide())

    def test_unknown_conflicting_or_blocked_mergeability_defers(self):
        for state in ['unknown', 'blocked', 'dirty', 'behind', 'unstable', None]:
            self.pr['mergeable_state'] = state
            self.assertIsNotNone(self.decide())
        self.pr['mergeable_state'] = 'clean'
        self.pr['mergeable'] = None
        self.assertIsNotNone(self.decide())

    def test_required_build_cannot_be_neutral_or_skipped(self):
        for state in ['NEUTRAL', 'SKIPPED']:
            self.checks[0] = dict(self.build, state=state)
            self.assertIsNotNone(self.decide())

    def test_closed_draft_human_fork_wrong_base_or_stale_head_defers(self):
        cases = [dict(state='closed'), dict(draft=True), dict(user={'login': 'human'}), dict(head={'sha': 'a' * 40, 'repo': {'full_name': 'fork/app'}}), dict(base={'ref': 'other', 'repo': self.pr['base']['repo']}), dict(head={'sha': 'b' * 40, 'repo': self.pr['head']['repo']})]
        for case in cases:
            self.assertIsNotNone(gate.decision(dict(self.pr, **case), self.required, self.checks, 'a' * 40, gate.BOTS['dependabot']))

    def test_head_changed_during_checks_never_merges(self):
        changed = copy.deepcopy(self.pr)
        changed['head']['sha'] = 'b' * 40
        with patch.object(gate, 'gh', side_effect=[self.pr, self.required, self.checks, changed]) as api:
            self.assertEqual(gate.inspect_and_merge('owner/app', 1, gate.BOTS['dependabot']), 'PR head changed')
            self.assertEqual(api.call_count, 4)

    def test_merge_has_exact_sha_and_no_bypass(self):
        with patch.object(gate, 'gh', side_effect=[self.pr, self.required, self.checks, self.pr, {'merged': True}]) as api:
            self.assertEqual(gate.inspect_and_merge('owner/app', 1, gate.BOTS['dependabot']), 'merged checked head')
            self.assertEqual(api.call_args.args, ('api', '--method', 'PUT', 'repos/owner/app/pulls/1/merge', '-f', 'merge_method=squash', '-f', 'sha=' + 'a' * 40))

    def test_dry_run_never_merges(self):
        with patch.object(gate, 'gh', side_effect=[self.pr, self.required, self.checks, self.pr]) as api:
            self.assertIn('dry run', gate.inspect_and_merge('owner/app', 1, gate.BOTS['dependabot'], dry_run=True))
            self.assertEqual(api.call_count, 4)

    def test_api_error_never_merges(self):
        with patch.object(gate, 'gh', side_effect=[self.pr, RuntimeError('failed')]) as api:
            with self.assertRaises(RuntimeError):
                gate.inspect_and_merge('owner/app', 1, gate.BOTS['dependabot'])
            self.assertEqual(api.call_count, 2)

    def test_unknown_event_head_never_looks_up_checks_or_merges(self):
        with patch.object(gate, 'gh', return_value=self.pr) as api:
            self.assertEqual(gate.inspect_and_merge('owner/app', 1, gate.BOTS['dependabot'], 'b' * 40), 'PR head changed')
            self.assertEqual(api.call_count, 1)


class WorkflowOwnershipTests(unittest.TestCase):
    def test_sync_cannot_replace_application_ci(self):
        root = Path(__file__).parents[1]
        sync = (root / 'workflows/sync-repo-settings.yml').read_text(encoding='utf-8')
        items = sync.split('SYNC_ITEMS: |', 1)[1].split('COMMIT_MESSAGE:', 1)[0]
        destinations = [line.strip().split('|')[1] for line in items.splitlines() if '|' in line]
        self.assertNotIn('.github/workflows/ci.yml', destinations)
        self.assertIn('.github/scripts/checked-bot-merge.py', destinations)

    def test_privileged_workflows_only_execute_default_branch_policy(self):
        root = Path(__file__).parents[1]
        for name in ['dependabot-auto-merge.yml', 'auto-merge-bots.yml']:
            workflow = (root / 'workflows' / name).read_text(encoding='utf-8')
            self.assertNotIn('  pull_request:', workflow)
            self.assertNotIn('  pull_request_target:', workflow)
            self.assertIn('ref: ${{ github.event.repository.default_branch }}', workflow)
            self.assertIn('persist-credentials: false', workflow)
            self.assertNotIn('gh pr merge', workflow)
            self.assertIn('checked-bot-merge.py --group', workflow)


if __name__ == '__main__':
    unittest.main()
