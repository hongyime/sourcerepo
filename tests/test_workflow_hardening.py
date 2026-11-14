"""Regression checks for data boundaries in shared workflows."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class WorkflowHardeningTests(unittest.TestCase):
    def test_onboarding_metadata_uses_json_yaml_scalars(self):
        workflow = (ROOT / ".github/workflows/new-repo-request.yml").read_text(encoding="utf-8")
        self.assertIn('f"  description: {json.dumps(description)}"', workflow)
        self.assertIn('f"  homepage: {json.dumps(homepage)}"', workflow)
        description = 'quoted "description" # fragment'
        homepage = 'https://example.invalid/app#preview'
        generated = f"description: {json.dumps(description)}\nhomepage: {json.dumps(homepage)}\n"
        self.assertEqual(yaml.safe_load(generated), {"description": description, "homepage": homepage})

    def test_issue_output_uses_an_unpredictable_delimiter(self):
        workflow = (ROOT / ".github/workflows/summary.yml").read_text(encoding="utf-8")
        self.assertIn('openssl rand -hex 32', workflow)
        self.assertNotIn('title<<EOF', workflow)
        self.assertNotIn('body<<EOF', workflow)
        delimiter = 'a' * 64
        issue = 'ordinary text\nEOF\nbody=attacker-controlled'
        output = f"body<<{delimiter}\n{issue}\n{delimiter}\n"
        self.assertEqual(output.splitlines()[0], f"body<<{delimiter}")
        self.assertEqual(output.splitlines()[-1], delimiter)

    def test_private_scorecard_runs_without_publishing_results(self):
        workflow = (ROOT / ".github/workflows/scorecard.yml").read_text(encoding="utf-8")
        self.assertIn('publish_results: ${{ github.event.repository.private == false }}', workflow)

    def test_dependabot_is_canonical_and_retired_files_are_not_mapped(self):
        workflow = (ROOT / ".github/workflows/sync-repo-settings.yml").read_text(encoding="utf-8")
        self.assertIn('.github/dependabot.yml|.github/dependabot.yml', workflow)
        self.assertNotIn('.github/dependabot_config.yml|.github/dependabot.yml', workflow)
        self.assertNotIn('.github/greetings.yml|.github/greetings.yml', workflow)
        self.assertNotIn('.github/FUNDING.yml|.github/FUNDING.yml', workflow)

    def test_powershell_seed_paths_use_platform_path_joins(self):
        script = (ROOT / "tools/new_repo.ps1").read_text(encoding="utf-8")
        self.assertIn('Join-Path (Join-Path $repoPath ".agents") "STATE.template.md"', script)
        self.assertIn('Join-Path (Join-Path $repoPath ".agents") "STATE.md"', script)
        self.assertNotIn('".agents\\STATE', script)


if __name__ == "__main__":
    unittest.main()
