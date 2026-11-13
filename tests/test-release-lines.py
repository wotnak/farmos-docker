#!/usr/bin/env python3
"""Check major-only release selection without Nix or network access."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/releases.py"
sys.path.insert(0, str(SCRIPT.parent))
import releases


class ReleaseMajorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "versions.json").write_text(json.dumps({"minimum_major": 4, "development_branch": "4.x"}))
        (self.root / ".build-inputs").mkdir()
        self.data = {
            "minimum_major": 4,
            "versions": {"4.x": {
                "constraint": "4.x-dev", "farmosRev": "a" * 40,
                "farmosSourceHash": "source-hash", "composerProjectRev": "b" * 40,
                "composerProjectHash": "project-hash", "devHash": "development-hash",
            }},
        }
        for version in ["10.0.1", "4.10.0", "9.1.0", "5.1.0"]:
            self.pin(version)

    def save(self):
        (self.root / releases.SNAPSHOT).write_text(json.dumps(self.data))

    def pin(self, version, major=None):
        major = version.split(".", 1)[0] if major is None else major
        self.data["versions"][major] = {"version": version, "prodHash": "prod-hash", "devHash": "dev-hash"}
        self.save()

    def run_helper(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                                text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
        return result.stdout.strip()

    def test_major_before_preparation_and_explicit_policy_validation(self):
        (self.root / releases.SNAPSHOT).unlink()
        self.assertEqual(self.run_helper("--field", "major"), "4")
        self.assertEqual(self.run_helper("--major", "99", "--field", "major"), "99")
        for major in ["3", "04", "4.x", "4\n"]:
            self.run_helper("--major", major, "--field", "major", success=False)
        self.run_helper("--field", "version", success=False)
        self.run_helper("--matrix", success=False)

    def test_provisional_snapshot_is_not_public(self):
        (self.root / ".build-inputs/.preparing").touch()
        self.run_helper("--matrix", success=False)
        self.run_helper("--field", "major", success=False)

    def test_root_policy_rejects_saved_application_pins(self):
        (self.root / "versions.json").write_text(json.dumps(self.data))
        self.run_helper("--matrix", success=False)

    def test_matrix_has_only_one_release_per_major_in_numeric_order(self):
        rows = json.loads(self.run_helper("--matrix"))["include"]
        self.assertEqual(rows, [
            {"major": "4", "version": "4.10.0"}, {"major": "5", "version": "5.1.0"},
            {"major": "9", "version": "9.1.0"}, {"major": "10", "version": "10.0.1"},
        ])

    def test_fields_default_to_latest_or_select_major(self):
        self.assertEqual(self.run_helper("--field", "version"), "10.0.1")
        self.assertEqual(self.run_helper("--field", "major"), "10")
        self.assertEqual(self.run_helper("--major", "4", "--field", "version"), "4.10.0")
        self.assertEqual(self.run_helper("--major", "4", "--field", "major"), "4")
        self.assertEqual(json.loads(self.run_helper("--major", "4")), {"major": "4", "version": "4.10.0"})

    def test_invalid_or_untracked_majors_fail(self):
        for major in ["", "4.0", "4.0.5", "04", "../4", "6", "4\n", "-4", "4.x"]:
            with self.subTest(major=major):
                self.run_helper("--major", major, "--field", "version", success=False)

    def test_removed_options_and_fields_are_rejected(self):
        for args in [("--line", "4.0"), ("--field", "minor"), ("--field", "line"),
                     ("--field", "publish_major"), ("--major", "4", "--matrix")]:
            with self.subTest(args=args):
                self.run_helper(*args, success=False)

    def test_version_must_match_major_key(self):
        self.pin("5.1.1", major="4")
        self.run_helper("--matrix", success=False)

    def test_minor_and_noncanonical_major_keys_are_rejected(self):
        for major in ["", "4.0", "04", "latest", "4\n", "-4", "5.x", "04.x"]:
            with self.subTest(major=major):
                self.pin("4.1.1", major=major)
                self.run_helper("--matrix", success=False)
                del self.data["versions"][major]

    def test_empty_release_set_fails(self):
        self.data["versions"] = {"4.x": self.data["versions"]["4.x"]}
        self.save()
        self.assertEqual(releases.read_releases(self.root), {})
        self.assertEqual(json.loads(self.run_helper("--matrix")), {"include": []})
        self.assertEqual(self.run_helper("--field", "major"), "4")
        self.run_helper("--field", "version", success=False)

    def test_legacy_release_requires_tracking_policy_change(self):
        self.pin("3.2.1")
        self.run_helper("--matrix", success=False)

    def test_invalid_tracking_policy_fails(self):
        for value in [True, "4", -1, None]:
            with self.subTest(value=value):
                self.data["minimum_major"] = value
                self.save()
                self.run_helper("--matrix", success=False)

    def test_invalid_json_and_nonobject_metadata_fail(self):
        for contents in ["not json", "null", "[]", "4", '"metadata"']:
            with self.subTest(contents=contents):
                (self.root / releases.SNAPSHOT).write_text(contents)
                self.run_helper("--matrix", success=False)

    def test_missing_and_wrongly_typed_metadata_fields_fail(self):
        for key, values in [("minimum_major", [None]), ("versions", [None, []])]:
            original = self.data.pop(key)
            self.save()
            self.run_helper("--matrix", success=False)
            for value in values:
                with self.subTest(key=key, value=value):
                    self.data[key] = value
                    self.save()
                    self.run_helper("--matrix", success=False)
            self.data[key] = original

    def test_development_entry_is_optional_but_must_be_an_object(self):
        del self.data["versions"]["4.x"]
        self.save()
        self.run_helper("--matrix")
        for value in [None, [], "4.x-dev", 4]:
            with self.subTest(value=value):
                self.data["versions"]["4.x"] = value
                self.save()
                self.run_helper("--matrix", success=False)

    def test_separate_releases_and_development_schema_is_rejected(self):
        versions = self.data.pop("versions")
        self.data["development"] = versions.pop("4.x")
        self.data["releases"] = versions
        self.save()
        self.run_helper("--matrix", success=False)

    def test_invalid_release_objects_and_fields_fail(self):
        original = self.data["versions"]["4"]
        invalid = [None, [], "4.1.0", {}, {**original, "version": 4},
                   {**original, "version": "4.01.0"}, {**original, "version": "4.0.1\n"}]
        for field in ["prodHash", "devHash"]:
            missing = original.copy()
            del missing[field]
            invalid.extend([missing, {**original, field: None}, {**original, field: 4}])
        for value in invalid:
            with self.subTest(value=value):
                self.data["versions"]["4"] = value
                self.save()
                self.run_helper("--matrix", success=False)

    def test_development_fields_must_be_strings(self):
        original = self.data["versions"]["4.x"].copy()
        for field in original:
            for value in [None, 4, False, []]:
                with self.subTest(field=field, value=value):
                    self.data["versions"]["4.x"] = {**original, field: value}
                    self.save()
                    self.run_helper("--matrix", success=False)
            self.data["versions"]["4.x"] = original.copy()
            del self.data["versions"]["4.x"][field]
            self.save()
            self.run_helper("--matrix", success=False)

    def test_duplicate_keys_are_rejected_at_every_level(self):
        contents = json.dumps(self.data)
        for original, duplicate in [
            ('"minimum_major": 4', '"minimum_major": 4, "minimum_major": 4'),
            ('"versions": {', '"versions": {}, "versions": {'),
            ('"4": {', '"4": {}, "4": {'),
            ('"4.x": {', '"4.x": {}, "4.x": {'),
            ('"version": "4.10.0"', '"version": "4.10.0", "version": "4.10.0"'),
            ('"constraint": "4.x-dev"', '"constraint": "4.x-dev", "constraint": "4.x-dev"'),
        ]:
            with self.subTest(key=original):
                (self.root / releases.SNAPSHOT).write_text(contents.replace(original, duplicate))
                self.run_helper("--matrix", success=False)

    def test_helpers_round_trip_empty_hash_placeholders(self):
        self.data["versions"]["4"].update(prodHash="", devHash="")
        self.data["versions"]["4.x"]["devHash"] = ""
        path = self.root / releases.SNAPSHOT
        replace = releases.os.replace

        def replace_complete_file(source, target):
            self.assertEqual(Path(target), path)
            self.assertEqual(Path(source).parent, path.parent)
            self.assertEqual(json.loads(Path(source).read_text()), self.data)
            self.assertEqual(json.loads(path.read_text())["versions"]["4"]["prodHash"], "prod-hash")
            replace(source, target)

        with patch.object(releases.os, "replace", side_effect=replace_complete_file) as replacement:
            releases.write_versions(self.root, self.data)
        replacement.assert_called_once()
        self.assertEqual(path.read_text(), json.dumps(self.data, indent=2) + "\n")
        self.assertEqual(releases.read_versions(self.root), self.data)
        self.assertEqual(releases.minimum_major(self.root), 4)
        self.assertEqual(releases.read_releases(self.root), {
            "4": "4.10.0", "5": "5.1.0", "9": "9.1.0", "10": "10.0.1",
        })
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_atomic_replacement_preserves_original_and_cleans_temporary(self):
        path = self.root / releases.SNAPSHOT
        original = path.read_bytes()
        self.data["versions"]["4"]["version"] = "4.11.0"
        with patch.object(releases.os, "replace", side_effect=OSError("replacement failed")):
            with self.assertRaises(OSError):
                releases.write_versions(self.root, self.data)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.iterdir()), [path])

    def test_writer_rejects_nonstring_major_keys_before_replacing_metadata(self):
        original = (self.root / releases.SNAPSHOT).read_bytes()
        self.data["versions"][4] = self.data["versions"].pop("4")
        with self.assertRaises(releases.ReleaseError):
            releases.write_versions(self.root, self.data)
        self.assertEqual((self.root / releases.SNAPSHOT).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
