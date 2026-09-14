"""Repository Action references survive template logic updates or fail closed."""
import importlib.util
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

import yaml

SPEC = importlib.util.spec_from_file_location(
    "workflow_refs", Path(__file__).resolve().parents[1] / ".github/scripts/preserve-workflow-actions.py")
refs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = refs
SPEC.loader.exec_module(refs)
PIN = "a" * 40


def workflow(steps, job="build"):
    return f"name: fixture\non: workflow_dispatch\njobs:\n  {job}:\n    runs-on: ubuntu-latest\n    steps:\n{steps}"


class WorkflowReferences(unittest.TestCase):
    def test_long_malformed_reference_fails_promptly_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.yml", Path(directory) / "target.yml"
            source.write_text(workflow("      - uses: " + "-/" * 20000 + "!\n"))
            target.write_text("name: keep\njobs: {}\n")
            result = subprocess.run([sys.executable, SPEC.origin, str(source), str(target)],
                                    capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Unrecognized GitHub Action", result.stderr)
            self.assertEqual(target.read_text(), "name: keep\njobs: {}\n")

    def test_keeps_pin_annotation_and_new_template_logic(self):
        source = workflow("      - uses: actions/checkout@v7 # shared\n      - run: echo new\n")
        target = source.replace("@v7 # shared", "@" + PIN + " # reviewed v6").replace("echo new", "echo old")
        actual = refs.preserve(source, target)
        self.assertIn("@" + PIN + " # reviewed v6", actual)
        self.assertIn("echo new", actual)
        self.assertNotIn("# shared", actual)

    def test_versions_are_owned_without_attempting_an_upgrade(self):
        for shared, owned in (("v6", "v7"), ("v7", "v6")):
            source = workflow(f"      - uses: actions/setup-python@{shared}\n")
            self.assertEqual(refs.preserve(source, source.replace(shared, owned)), source.replace(shared, owned))

    def test_reordering_uses_step_ids_to_preserve_distinct_pins(self):
        source = workflow("      - id: second\n        uses: actions/checkout@v7\n      - id: first\n        uses: actions/checkout@v7\n")
        target = workflow("      - id: first\n        uses: actions/checkout@" + PIN + "\n      - id: second\n        uses: actions/checkout@" + "b" * 40 + "\n")
        actual = yaml.safe_load(refs.preserve(source, target))["jobs"]["build"]["steps"]
        self.assertEqual([(s["id"], s["uses"][-40:]) for s in actual], [("second", "b" * 40), ("first", PIN)])

    def test_reusable_workflow_and_renamed_job(self):
        source = "jobs:\n  new:\n    uses: org/repo/.github/workflows/check.yml@v7\n"
        target = source.replace("new:", "old:").replace("@v7", "@" + PIN)
        self.assertIn("new:\n    uses: org/repo/.github/workflows/check.yml@" + PIN, refs.preserve(source, target))

    def test_same_job_wins_over_different_job_reference(self):
        source = "jobs:\n  a:\n    uses: org/repo/.github/workflows/a.yml@v7\n  b:\n    uses: org/repo/.github/workflows/a.yml@v7\n"
        target = source.replace("@v7", "@v6", 1)
        self.assertEqual(refs.preserve(source, target), target)

    def test_flow_yaml_and_quoted_scalars_keep_other_fields(self):
        source = 'jobs: {build: {steps: [{uses: "actions/checkout@v7", with: {fetch-depth: 1}}]}}\n'
        actual = refs.preserve(source, source.replace("@v7", "@" + PIN))
        self.assertEqual(yaml.safe_load(actual)["jobs"]["build"]["steps"][0]["with"], {"fetch-depth": 1})
        self.assertIn('"actions/checkout@' + PIN + '"', actual)

    def test_run_examples_are_never_action_references(self):
        source = workflow("      - run: |\n          echo 'uses: actions/checkout@v7'\n      - uses: actions/checkout@v7\n")
        target = workflow("      - uses: actions/checkout@" + PIN + "\n")
        actual = refs.preserve(source, target)
        self.assertIn("echo 'uses: actions/checkout@v7'", actual)
        self.assertIn("      - uses: actions/checkout@" + PIN, actual)

    def test_new_action_uses_template_and_local_actions_follow_template(self):
        source = workflow("      - uses: actions/checkout@v7\n      - uses: ./local-new\n")
        self.assertEqual(refs.preserve(source, workflow("      - uses: ./local-old\n")), source)

    def test_anonymous_distinct_pins_require_manual_review(self):
        source = workflow("      - uses: actions/checkout@v7\n")
        target = workflow("      - uses: actions/checkout@" + PIN + "\n      - uses: actions/checkout@" + "b" * 40 + "\n")
        with self.assertRaisesRegex(refs.PolicyError, "Ambiguous"):
            refs.preserve(source, target)

    def test_duplicate_keys_merge_keys_and_invalid_shapes_fail(self):
        source = workflow("      - uses: actions/checkout@v7\n")
        for target in ("jobs: {}\njobs: {}\n", "jobs: [oops]\n", "plain text\n", "jobs: {a: {steps: oops}}\n", "jobs: {a: {<<: {steps: []}}}\n"):
            with self.subTest(target=target), self.assertRaises(refs.PolicyError):
                refs.preserve(source, target)

    def test_anchors_fail_closed_when_action_needs_replacement(self):
        source = workflow("      - uses: &checkout actions/checkout@v7\n      - uses: *checkout\n")
        with self.assertRaisesRegex(refs.PolicyError, "anchors"):
            refs.preserve(source, source.replace("@v7", "@" + PIN))

    def test_flow_comment_cannot_be_silently_lost(self):
        source = "jobs: {a: {steps: [{uses: actions/checkout@v7}]}}\n"
        target = workflow("      - uses: actions/checkout@" + PIN + " # reviewed\n")
        with self.assertRaisesRegex(refs.PolicyError, "annotated"):
            refs.preserve(source, target)

    def test_second_merge_is_identical(self):
        source = workflow("      - uses: actions/checkout@v7\n      - run: echo new\n")
        target = source.replace("@v7", "@" + PIN)
        self.assertEqual(refs.preserve(source, refs.preserve(source, target)), target)

    def test_malformed_yaml_keeps_existing_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.yml", Path(directory) / "target.yml"
            source.write_text("jobs: [invalid\n")
            target.write_bytes(b"name: preserve\r\njobs: {}\r\n")
            with self.assertRaises(yaml.YAMLError):
                refs.copy_workflow(source, target)
            self.assertEqual(target.read_bytes(), b"name: preserve\r\njobs: {}\r\n")
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_copy_creates_missing_file_and_keeps_case_insensitive_coordinate(self):
        source_text = workflow("      - uses: Actions/Checkout@v7\n")
        target_text = source_text.replace("Actions/Checkout@v7", "actions/checkout@" + PIN)
        self.assertIn("actions/checkout@" + PIN, refs.preserve(source_text, target_text))
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "source.yml", Path(directory) / "nested/target.yml"
            source.write_text(source_text)
            refs.copy_workflow(source, target)
            self.assertEqual(target.read_text(), source_text)


if __name__ == "__main__":
    unittest.main()
