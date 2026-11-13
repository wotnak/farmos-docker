#!/usr/bin/env python3
"""Exercise provenance against real temporary Git checkouts without Nix or a registry."""

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import image_evidence as evidence


class ImageEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "source"
        self.root.mkdir()
        for name, contents in {
            "flake.lock": '{"nodes":{}}',
            ".build-inputs/versions.json": json.dumps({
                "minimum_major": 4,
                "versions": {
                    "4": {
                        "version": "4.0.4", "prodHash": "sha256-" + "A" * 43 + "=",
                        "devHash": "sha256-" + "B" * 43 + "=",
                    },
                    "4.x": {
                        "constraint": "4.x-dev", "farmosRev": "a" * 40,
                        "farmosSourceHash": "sha256-" + "C" * 43 + "=",
                        "composerProjectRev": "b" * 40,
                        "composerProjectHash": "sha256-" + "D" * 43 + "=",
                        "devHash": "sha256-" + "E" * 43 + "=",
                    },
                },
            }),
            ".build-inputs/composer/releases/4/composer.lock": '{"packages":[]}',
            ".build-inputs/composer/releases/4/composer.json": '{}',
            ".build-inputs/composer/4.x/composer.json": '{}',
            ".build-inputs/composer/4.x/composer.lock": '{"packages":[]}',
            "versions.json": '{"minimum_major":4,"development_branch":"4.x"}',
            "packages/farmos/composer/project/composer.json": '{}',
            ".gitignore": '.build-inputs/\nflake.lock\n',
            "images/source.json": '{}',
            "images/default.nix": '{}',
        }.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        self.git("init", "--quiet")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.env = patch.dict(os.environ, {
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/images",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "SOURCE_REVISION": self.sha,
            "GITHUB_WORKFLOW_REF": "owner/images/.github/workflows/hourly-images.yaml@refs/heads/main",
            # A scheduled run can check out a newer default-branch SHA than its event SHA.
            "GITHUB_SHA": "e" * 40,
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    def prepare(self):
        evidence.prepare_source(self.root)

    def children(self):
        self.prepare()
        self.directory = self.base / "children"
        self.directory.mkdir()
        self.identities = []
        for system, digit in (("aarch64-linux", "a"), ("x86_64-linux", "b")):
            identity = {**evidence.checkout_identity(self.root), "system": system,
                        "image": "ghcr.io/owner/farmos@sha256:" + digit * 64,
                        "output": "farmos-4", "workflow": evidence.invocation()}
            self.identities.append(identity)
        self.save_children()
        return self.directory

    def save_children(self):
        for number, identity in enumerate(self.identities):
            folder = self.directory / str(number)
            folder.mkdir(exist_ok=True)
            (folder / "identity.json").write_text(json.dumps(identity))

    def validate(self):
        return evidence.validate_children(self.root, self.directory, "farmos-4")

    def test_actual_checkout_revision_overrides_event_sha(self):
        self.prepare()
        metadata = json.loads((self.root / "images/source.json").read_text())
        self.assertEqual(metadata, {"source": "https://github.com/owner/images", "revision": self.sha})

    def test_wrong_requested_revision_is_rejected(self):
        with patch.dict(os.environ, {"SOURCE_REVISION": "0" * 40}):
            with self.assertRaisesRegex(evidence.EvidenceError, "SOURCE_REVISION"):
                self.prepare()

    def test_code_changes_staged_or_unstaged_are_rejected(self):
        for name in ("versions/escape", "versions.json/escape", "versions.json.bak"):
            with self.subTest(path=name):
                self.assertFalse(evidence.is_generated(name))
        for stage in (False, True):
            with self.subTest(staged=stage):
                (self.root / "images/default.nix").write_text('{ changed = true; }')
                if stage:
                    self.git("add", "images/default.nix")
                with self.assertRaisesRegex(evidence.EvidenceError, "outside generated build inputs"):
                    self.prepare()

    def test_dependency_refresh_has_exact_generated_fingerprint(self):
        before = evidence.build_input_inventory(self.root)
        lock = self.root / ".build-inputs/composer/releases/4/composer.lock"
        lock.write_text('{"packages":[{"version":"new"}]}')
        versions = self.root / ".build-inputs/versions.json"
        metadata = json.loads(versions.read_text())
        metadata["versions"]["4"]["version"] = "4.0.5"
        versions.write_text(json.dumps(metadata))
        self.git("add", "-f", ".build-inputs", "flake.lock")
        self.prepare()
        after = evidence.checkout_identity(self.root)
        self.assertEqual(after["revision"], self.sha)
        self.assertEqual(set(after["buildInputs"]), {
            "flake.lock", "versions.json", ".build-inputs/versions.json",
            ".build-inputs/composer/releases/4/composer.json",
            ".build-inputs/composer/releases/4/composer.lock",
            ".build-inputs/composer/4.x/composer.json", ".build-inputs/composer/4.x/composer.lock",
        })
        for path in (lock, versions):
            name = path.relative_to(self.root).as_posix()
            with self.subTest(path=name):
                self.assertNotEqual(before[name], after["buildInputs"][name])
                self.assertEqual(after["buildInputs"][name], evidence.digest(path))
                material = next(item for item in evidence.materials(after) if item.get("name") == name)
                self.assertEqual(material["digest"], {"sha256": evidence.digest(path)})

    def test_policy_and_old_composer_source_changes_are_rejected(self):
        for filename in ("versions.json", "packages/farmos/composer/project/composer.json"):
            path = self.root / filename
            original = path.read_text()
            path.write_text('{"changed":true}')
            with self.subTest(path=filename), self.assertRaisesRegex(evidence.EvidenceError, "outside generated"):
                self.prepare()
            path.write_text(original)

    def test_untracked_code_changes_are_rejected(self):
        (self.root / "images/unrecorded.nix").write_text('{}')
        with self.assertRaisesRegex(evidence.EvidenceError, "images/unrecorded.nix"):
            self.prepare()

    def test_missing_input_or_composer_snapshot_is_rejected(self):
        inventory = evidence.build_input_inventory(self.root)
        for filename in inventory:
            path = self.root / filename
            original = path.read_bytes()
            path.unlink()
            with self.subTest(path=filename), self.assertRaises((evidence.EvidenceError, OSError)):
                evidence.build_input_inventory(self.root)
            path.write_bytes(original)

    def test_incomplete_preparation_cannot_produce_evidence(self):
        (self.root / ".build-inputs/.preparing").touch()
        with self.assertRaisesRegex(evidence.EvidenceError, "preparation is incomplete"):
            self.prepare()

    def test_prepare_source_can_refresh_its_own_generated_metadata(self):
        self.prepare()
        self.prepare()
        self.assertEqual(evidence.checkout_identity(self.root)["revision"], self.sha)

    def test_missing_or_symlinked_input_root_is_rejected(self):
        path = self.root / ".build-inputs"
        saved = self.base / "saved-inputs"
        path.rename(saved)
        with self.assertRaisesRegex(evidence.EvidenceError, "build input directory"):
            evidence.build_input_inventory(self.root)
        path.symlink_to(saved, target_is_directory=True)
        with self.assertRaisesRegex(evidence.EvidenceError, "build input directory"):
            evidence.build_input_inventory(self.root)

    def test_scoped_snapshot_requires_only_selected_composer_files(self):
        path = self.root / ".build-inputs/versions.json"
        snapshot = json.loads(path.read_text())
        for selected in ("4", "4.x"):
            path.write_text(json.dumps({**snapshot, "versions": {selected: snapshot["versions"][selected]}}))
            inventory = evidence.build_input_inventory(self.root)
            self.assertIn(".build-inputs/versions.json", inventory)
        path.write_text('{"versions":{}}')
        with self.assertRaisesRegex(evidence.EvidenceError, "select build inputs"):
            evidence.build_input_inventory(self.root)

    def test_source_metadata_tampering_is_rejected(self):
        self.prepare()
        (self.root / "images/source.json").write_text('{}')
        with self.assertRaisesRegex(evidence.EvidenceError, "does not match"):
            evidence.checkout_identity(self.root)

    def test_build_input_symlinks_are_rejected(self):
        versions = self.root / "versions.json"
        external = self.base / "versions.json"
        versions.rename(external)
        versions.symlink_to(external)
        with self.assertRaisesRegex(evidence.EvidenceError, "regular evidence input"):
            evidence.build_input_inventory(self.root)
        versions.unlink()
        external.rename(versions)
        (self.root / ".build-inputs/composer/escape").symlink_to(self.base)
        with self.assertRaisesRegex(evidence.EvidenceError, "symlinks"):
            evidence.build_input_inventory(self.root)

    def test_mutable_or_malformed_image_references_are_rejected(self):
        for value in ("ghcr.io/owner/farmos:4", "ghcr.io/owner/farmos@sha256:short",
                      "ghcr.io/owner/farmos:tag@sha256:" + "a" * 64,
                      "ghcr.io/owner/farmos@sha256:" + "A" * 64):
            with self.subTest(value=value), self.assertRaises(evidence.EvidenceError):
                evidence.image_parts(value)

    def test_valid_architectures_allow_successful_previous_attempt(self):
        self.children()
        with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
            self.assertEqual([child["system"] for child in self.validate()],
                             ["aarch64-linux", "x86_64-linux"])

    def test_reject_mismatched_children(self):
        self.children()
        original = copy.deepcopy(self.identities)
        changes = [("system", "aarch64-linux"), ("system", "riscv64-linux"),
                   ("output", "farmos-4-dev"), ("output", "farmos-4-dev-runtime"), ("revision", "f" * 40),
                   ("source", "https://github.com/other/repo"),
                   ("image", "ghcr.io/other/repo@sha256:" + "b" * 64),
                   ("image", self.identities[0]["image"]), ("buildInputs", {}),
                   ("workflow", {**evidence.invocation(), "GITHUB_RUN_ID": "456"})]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.identities = copy.deepcopy(original)
                self.identities[1][field] = value
                self.save_children()
                with self.assertRaises(evidence.EvidenceError):
                    self.validate()

    def test_development_runtime_provenance_preserves_variant(self):
        children = self.children()
        for identity in self.identities:
            identity['output'] = 'farmos-4-dev-runtime'
        self.save_children()
        destination = self.base / 'development-runtime-index'
        evidence.index(self.root, argparse.Namespace(
            children=children, output='farmos-4-dev-runtime', destination=destination,
            image='ghcr.io/owner/farmos@sha256:' + 'c' * 64))
        identity = json.loads((destination / 'identity.json').read_text())
        self.assertEqual(identity['output'], 'farmos-4-dev-runtime')
        self.assertEqual({child['image'] for child in identity['children']},
                         {child['image'] for child in self.identities})

    def test_output_metadata_accepts_only_canonical_major_outputs_and_current_branch(self):
        for major in ('0', '4', '40'):
            for suffix in ('', '-dev', '-runtime', '-dev-runtime'):
                output = 'farmos-' + major + suffix
                with self.subTest(output=output):
                    self.assertEqual(evidence.output_name(output), output)
        self.assertEqual(evidence.output_name('farmos-4x-dev'), 'farmos-4x-dev')
        for output in ('farmos', 'farmos-dev', 'farmos-runtime', 'farmos-dev-runtime',
                       'farmos-4.0', 'farmos-4.0-dev', 'farmos-4.0-runtime',
                       'farmos-4.0-dev-runtime', 'farmos-04', 'farmos-4x',
                       'farmos-40x-dev', 'farmos-4.x-dev', 'farmos-4-runtime-dev',
                       'farmos-4-dev-extra', 'farmos-4\n'):
            with self.subTest(output=output), self.assertRaises(evidence.EvidenceError):
                evidence.output_name(output)

    def test_both_children_with_same_tampered_build_inputs_are_rejected(self):
        self.children()
        for child in self.identities:
            child["buildInputs"]["flake.lock"] = "0" * 64
        self.save_children()
        with self.assertRaisesRegex(evidence.EvidenceError, "current buildInputs"):
            self.validate()

    def test_generated_input_changes_after_build_are_rejected(self):
        self.children()
        (self.root / "flake.lock").write_text('{"changed":true}')
        with self.assertRaisesRegex(evidence.EvidenceError, "current buildInputs"):
            self.validate()

    def test_incomplete_or_extra_architecture_set_is_rejected(self):
        self.children()
        (self.directory / "0/identity.json").unlink()
        with self.assertRaisesRegex(evidence.EvidenceError, "exactly two"):
            self.validate()
        self.save_children()
        extra = self.directory / "extra"
        extra.mkdir()
        (extra / "identity.json").write_text(json.dumps(self.identities[0]))
        with self.assertRaisesRegex(evidence.EvidenceError, "exactly two"):
            self.validate()

    def test_index_provenance_records_children_and_actual_materials(self):
        children = self.children()
        destination = self.base / "index"
        evidence.index(self.root, argparse.Namespace(
            children=children, output="farmos-4", destination=destination,
            image="ghcr.io/owner/farmos@sha256:" + "c" * 64))
        provenance = json.loads((destination / "provenance.json").read_text())
        definition = provenance["buildDefinition"]
        self.assertEqual(definition["externalParameters"]["revision"], self.sha)
        self.assertTrue(definition["buildType"].endswith("#oci-index-v1"))
        images = [material for material in definition["resolvedDependencies"]
                  if material["uri"].startswith("oci://")]
        self.assertEqual(len(images), 2)
        self.assertEqual({material["digest"]["sha256"] for material in images}, {"a" * 64, "b" * 64})
        self.assertTrue(provenance["runDetails"]["metadata"]["invocationId"].endswith("/123/attempts/1"))

    def test_architecture_records_nix_derivation_and_selected_system(self):
        self.prepare()
        destination = self.base / "architecture"
        destination.mkdir()
        drv = "/nix/store/" + "a" * 32 + "-image-farmos-nix.json.drv"
        original_run, original_digest = evidence.run, evidence.digest
        commands = []

        def fake_run(root, *command):
            if command[0] == "nix":
                commands.append(command)
                return drv
            return original_run(root, *command)

        with patch.object(evidence, "run", side_effect=fake_run), patch.object(
            evidence, "digest", side_effect=lambda path: "f" * 64 if str(path) == drv else original_digest(path)
        ):
            evidence.architecture(self.root, argparse.Namespace(
                image="ghcr.io/owner/farmos@sha256:" + "a" * 64,
                system="aarch64-linux", output="farmos-4x-dev", destination=destination))
        self.assertEqual(commands[0][-4:], ("--system", "aarch64-linux", "--raw", '.#"farmos-4x-dev".drvPath'))
        identity = json.loads((destination / "identity.json").read_text())
        self.assertEqual(identity["derivation"], {"path": drv, "sha256": "f" * 64})
        predicate = json.loads((destination / "provenance.json").read_text())
        self.assertTrue(predicate["buildDefinition"]["buildType"].endswith("#nix-image-v1"))
        self.assertEqual(predicate["buildDefinition"]["externalParameters"]["system"], "aarch64-linux")

    def test_children_from_other_variants_are_filtered(self):
        self.children()
        for output in ('farmos-4-dev', 'farmos-40', 'farmos-4x-dev'):
            extra = self.directory / output
            extra.mkdir()
            other = {**self.identities[0], 'output': output}
            (extra / "identity.json").write_text(json.dumps(other))
        self.assertEqual(len(self.validate()), 2)

    def test_evidence_destination_cannot_overwrite_source(self):
        with self.assertRaisesRegex(evidence.EvidenceError, "outside the source tree"):
            evidence.write_evidence(self.root, self.root / "images", {}, {})


class AttestationBindingTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "source": "https://github.com/owner/images", "revision": "d" * 40,
            "buildInputs": {"flake.lock": "e" * 64, ".build-inputs/versions.json": "f" * 64},
            "sourceMetadataSha256": "1" * 64, "output": "farmos-4", "system": "aarch64-linux",
            "image": "ghcr.io/owner/images@sha256:" + "a" * 64,
            "workflow": {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "d" * 40,
                         "GITHUB_WORKFLOW_REF": "owner/images/.github/workflows/release-images.yaml@refs/heads/main"},
            "derivation": {"path": "/nix/store/" + "a" * 32 + "-image.drv", "sha256": "2" * 64},
        }
        self.index = {key: copy.deepcopy(value) for key, value in self.identity.items()
                      if key not in ("system", "derivation")}
        self.index["children"] = [{"system": system, "image": "ghcr.io/owner/images@sha256:" + digit * 64}
                                  for system, digit in (("aarch64-linux", "b"), ("x86_64-linux", "c"))]

    def statement(self, identity=None, kind="architecture"):
        identity = identity or self.identity
        repository, sha256 = evidence.image_parts(identity["image"])
        return {"_type": "https://in-toto.io/Statement/v0.1", "predicateType": "https://slsa.dev/provenance/v1",
                "subject": [{"name": repository, "digest": {"sha256": sha256}}],
                "predicate": evidence.provenance_for_identity(identity, kind)}

    def envelope(self, statement):
        return {"payloadType": "application/vnd.in-toto+json",
                "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
                "signatures": [{"keyid": "", "sig": "cosign-already-verified-this"}]}

    def verify(self, statements, identity=None, kind="architecture", ndjson=False):
        identity = identity or self.identity
        envelopes = [self.envelope(statement) for statement in statements]
        contents = "\n".join(map(json.dumps, envelopes)) if ndjson else json.dumps(envelopes)
        evidence.verify_attestations(identity, identity["image"], kind, contents)

    def test_accepts_matching_cosign_array_and_ndjson_envelopes(self):
        statement = self.statement()
        for version in ("v0.1", "v1"):
            statement["_type"] = "https://in-toto.io/Statement/" + version
            for ndjson in (False, True):
                with self.subTest(version=version, ndjson=ndjson):
                    self.verify([statement], ndjson=ndjson)

    def test_matching_statement_can_follow_older_dependency_generation(self):
        older = self.statement()
        older["predicate"]["buildDefinition"]["resolvedDependencies"][1]["digest"]["sha256"] = "0" * 64
        for ndjson in (False, True):
            with self.subTest(ndjson=ndjson):
                self.verify([older, self.statement()], ndjson=ndjson)
                with self.assertRaises(evidence.EvidenceError):
                    self.verify([older], ndjson=ndjson)

    def test_unsigned_identity_cannot_relabel_another_signed_generation(self):
        original = self.statement()
        mutations = {
            "source": "https://github.com/other/images", "revision": "0" * 40,
            "buildInputs": {"flake.lock": "0" * 64}, "sourceMetadataSha256": "0" * 64,
            "output": "farmos-4-dev", "system": "x86_64-linux",
            "derivation": {**self.identity["derivation"], "sha256": "0" * 64},
        }
        for field, value in mutations.items():
            modified = {**self.identity, field: value}
            with self.subTest(field=field), self.assertRaisesRegex(evidence.EvidenceError, "No verified SLSA"):
                self.verify([original], identity=modified)

    def test_signed_predicate_run_must_match_identity_original_invocation(self):
        statement = self.statement()
        for name in self.identity["workflow"]:
            workflow = {**self.identity["workflow"], name: "456" if name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT") else "other"}
            modified = {**self.identity, "workflow": workflow}
            with self.subTest(field=name), self.assertRaises(evidence.EvidenceError):
                self.verify([statement], identity=modified)

    def test_previous_successful_attempt_uses_its_original_signed_predicate(self):
        statement = self.statement()
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                                     "GITHUB_SERVER_URL": "https://unrelated.invalid"}):
            self.verify([statement])
        self.assertTrue(statement["predicate"]["runDetails"]["metadata"]["invocationId"].endswith("/attempts/1"))

    def test_subject_must_be_exact_repository_and_immutable_digest(self):
        for subject in ([], [{"name": "ghcr.io/other/images", "digest": {"sha256": "a" * 64}}],
                        [{"name": "ghcr.io/owner/images", "digest": {"sha256": "0" * 64}}]):
            statement = self.statement()
            statement["subject"] = subject
            with self.subTest(subject=subject), self.assertRaises(evidence.EvidenceError):
                self.verify([statement])
        with self.assertRaisesRegex(evidence.EvidenceError, "different immutable image"):
            evidence.verify_attestations(self.identity, "ghcr.io/owner/images@sha256:" + "0" * 64,
                                         "architecture", json.dumps([self.envelope(self.statement())]))

    def test_index_children_and_platforms_are_signed_claims(self):
        statement = self.statement(self.index, "index")
        self.verify([statement], self.index, "index")
        modified = copy.deepcopy(self.index)
        modified["children"][0]["image"] = "ghcr.io/owner/images@sha256:" + "0" * 64
        with self.assertRaises(evidence.EvidenceError):
            self.verify([statement], modified, "index")
        statement["predicate"]["buildDefinition"]["externalParameters"]["platforms"] = ["aarch64-linux"]
        with self.assertRaises(evidence.EvidenceError):
            self.verify([statement], self.index, "index")

    def test_wrong_slsa_type_or_non_intoto_statement_is_rejected(self):
        for field, value in (("predicateType", "https://slsa.dev/provenance/v0.2"), ("_type", "custom")):
            statement = self.statement()
            statement[field] = value
            with self.subTest(field=field), self.assertRaises(evidence.EvidenceError):
                self.verify([statement])

    def test_empty_or_malformed_cosign_output_never_passes(self):
        for contents in ("", "[]", "{}", "null", "not-json", '{"payloadType":"application/vnd.in-toto+json","payload":"bad"}'):
            with self.subTest(contents=contents), self.assertRaises((evidence.EvidenceError, ValueError)):
                evidence.verify_attestations(self.identity, self.identity["image"], "architecture", contents)

    def test_local_unsigned_predicate_is_not_used_for_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            expected = evidence.save_identity(base / "identity.json", self.identity)
            # Even an apparently matching local predicate cannot override an older signed input set.
            (base / "provenance.json").write_text(json.dumps(evidence.provenance_for_identity(self.identity, "architecture")))
            older = self.statement()
            older["predicate"]["buildDefinition"]["externalParameters"]["revision"] = "0" * 40
            verified = base / "cosign.json"
            verified.write_text(json.dumps([self.envelope(older)]))
            self.assertEqual(evidence.main(["verify-attestation", "--identity", str(expected),
                                          "--attestations", str(verified), "--image", self.identity["image"],
                                          "--kind", "architecture"]), 1)


if __name__ == "__main__":
    unittest.main()
