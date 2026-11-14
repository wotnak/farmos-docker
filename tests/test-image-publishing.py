#!/usr/bin/env python3
"""Check publication failure gates using the real shell scripts and fake external CLIs."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "ghcr.io/owner/images"
INDEX = REPOSITORY + "@sha256:" + "c" * 64
SHA = "d" * 40
IDENTITY = "https://github.com/owner/images/.github/workflows/release-images.yaml@refs/heads/main"
sys.path.insert(0, str(ROOT / "scripts"))
import image_evidence as evidence
FAKE = r'''
import base64
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
failure = os.environ.get("FAIL_CASE", "")
index = "ghcr.io/owner/images@sha256:" + "c" * 64
if name == "python3":
    if args and args[0] == "scripts/image_evidence.py":
        if args[1] == "validate-children":
            if failure == "child_validation":
                sys.exit(1)
            destination = Path(args[args.index("--identity-directory") + 1])
            destination.mkdir(parents=True, exist_ok=True)
            for digit in "ab":
                identity = json.loads((Path(os.environ["FIXTURE_DIR"]) / (digit * 64 + ".identity.json")).read_text())
                (destination / ("sha256-" + digit * 64 + ".json")).write_text(json.dumps(identity))
                print(identity["image"])
        elif args[1] == "index":
            destination = Path(args[args.index("--destination") + 1])
            for filename in ("identity.json", "provenance.json"):
                (destination / filename).write_text((Path(os.environ["FIXTURE_DIR"]) / ("c" * 64 + "." + filename)).read_text())
        elif args[1] == "verify-attestation":
            os.execv(sys.executable, [sys.executable, *args])
        else:
            sys.exit(2)
    else:
        os.execv(sys.executable, [sys.executable, *args])
elif name == "docker":
    if "--metadata-file" in args:
        path = Path(args[args.index("--metadata-file") + 1])
        path.write_text(json.dumps({"containerimage.descriptor": {"digest": "sha256:" + "c" * 64}}))
elif name == "cosign":
    if failure == "architecture_" + args[0] and args[-1] != index:
        sys.exit(1)
    if failure == "child_signature" and args[0] == "verify" and args[-1] != index:
        sys.exit(1)
    if failure == "child_provenance" and args[0] == "verify-attestation" and args[-1] != index:
        sys.exit(1)
    if failure == "index_signature" and args[0] == "sign" and args[-1] == index:
        sys.exit(1)
    if failure == "index_provenance" and args[0] == "verify-attestation" and args[-1] == index:
        sys.exit(1)
    if failure == "index_attestation" and args[0] == "attest" and args[-1] == index:
        sys.exit(1)
    if failure == "index_verification" and args[0] == "verify" and args[-1] == index:
        sys.exit(1)
    if args[0] == "verify-attestation":
        statement = json.loads((Path(os.environ["FIXTURE_DIR"]) / (args[-1].split(":")[-1] + ".statement.json")).read_text())
        if failure == "child_input" and args[-1] != index or failure == "index_input" and args[-1] == index:
            statement["predicate"]["buildDefinition"]["resolvedDependencies"][1]["digest"]["sha256"] = "0" * 64
        envelope = {"payloadType": "application/vnd.in-toto+json", "payload": base64.b64encode(json.dumps(statement).encode()).decode(), "signatures": [{"sig": "verified-by-fake-cosign"}]}
        print(json.dumps([envelope]))
    else:
        print("{}")
elif name == "git":
    print(("e" if failure == "source_advanced" else "d") * 40 + "\trefs/heads/main")
else:
    sys.exit(2)
'''


class ImagePublishingTests(unittest.TestCase):
    def setUp(self):
        bash = shutil.which("bash")
        version = subprocess.check_output([bash, "-c", "printf '%s' \"${BASH_VERSINFO[0]}\""], text=True)
        if int(version) < 4:
            self.skipTest("Publication scripts require Bash 4+ on PATH")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source"
        (self.source / "scripts").mkdir(parents=True)
        (self.source / "images").mkdir()
        for script in ("publish-index", "attest-image", "image_evidence.py"):
            shutil.copy2(ROOT / "scripts" / script, self.source / "scripts" / script)
        (self.source / "images/source.json").write_text(json.dumps({"source": "https://github.com/owner/images"}))
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("python3", "docker", "cosign", "git"):
            executable = self.bin / name
            executable.write_text("#!" + sys.executable + "\n" + FAKE)
            executable.chmod(0o755)
        self.log = self.base / "commands.jsonl"
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "COMMAND_LOG": str(self.log), "GITHUB_REPOSITORY": "Owner/Images", "IMAGE_REPOSITORY": REPOSITORY,
                    "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                    "SOURCE_REVISION": SHA, "DEFAULT_BRANCH": "main", "SIGNING_IDENTITY": IDENTITY}
        self.fixtures = self.base / "fixtures"
        self.fixtures.mkdir()
        workflow = {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_SHA": SHA,
                    "GITHUB_WORKFLOW_REF": "owner/images/.github/workflows/release-images.yaml@refs/heads/main"}
        common = {"source": "https://github.com/owner/images", "revision": SHA,
                  "buildInputs": {".build-inputs/composer/releases/4/composer.lock": "e" * 64},
                  "sourceMetadataSha256": "f" * 64, "output": "farmos-4", "workflow": workflow}
        builds = []
        for system, digit in (("aarch64-linux", "a"), ("x86_64-linux", "b")):
            builds.append({**common, "image": REPOSITORY + "@sha256:" + digit * 64, "system": system,
                           "derivation": {"path": "/nix/store/" + digit * 32 + "-image.drv", "sha256": digit * 64}})
        index = {**common, "image": INDEX, "workflow": {**workflow, "GITHUB_RUN_ATTEMPT": "2"},
                 "children": [{"system": child["system"], "image": child["image"]} for child in builds]}
        for identity, kind in [(child, "architecture") for child in builds] + [(index, "index")]:
            digest = identity["image"].split(":")[-1]
            predicate = evidence.provenance_for_identity(identity, kind)
            statement = {"_type": "https://in-toto.io/Statement/v0.1", "predicateType": "https://slsa.dev/provenance/v1",
                         "subject": [{"name": REPOSITORY, "digest": {"sha256": digest}}], "predicate": predicate}
            for suffix, value in (("identity.json", identity), ("provenance.json", predicate), ("statement.json", statement)):
                (self.fixtures / (digest + "." + suffix)).write_text(json.dumps(value))
        self.env["FIXTURE_DIR"] = str(self.fixtures)
        self.command = [bash, "scripts/publish-index", "farmos-4", str(self.base / "children"),
                        str(self.base / "evidence")]

    def publish(self, failure=""):
        result = subprocess.run(self.command, cwd=self.source,
                                env={**self.env, "FAIL_CASE": failure}, capture_output=True, text=True)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        promotions = [command for command in commands if command[:4] == ["docker", "buildx", "imagetools", "create"]
                      and "--metadata-file" not in command]
        return result, commands, promotions

    def test_each_failed_gate_prevents_public_tag_promotion(self):
        for failure in ("child_validation", "child_signature", "child_provenance", "index_signature",
                        "index_attestation", "index_verification", "index_provenance", "child_input", "index_input"):
            with self.subTest(failure=failure):
                self.log.write_text("")
                result, _, promotions = self.publish(failure)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(promotions, [])
                self.assertFalse((self.base / "evidence/candidate-image.txt").exists())

    def attest_architecture(self, failure=""):
        destination = self.base / "architecture"
        destination.mkdir(exist_ok=True)
        for filename in ("identity.json", "provenance.json"):
            shutil.copy2(self.fixtures / ("a" * 64 + "." + filename), destination / filename)
        image = REPOSITORY + "@sha256:" + "a" * 64
        result = subprocess.run(
            [self.command[0], "scripts/attest-image", "sign", image, str(destination), "architecture"],
            cwd=self.source, env={**self.env, "FAIL_CASE": failure}, capture_output=True, text=True)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, commands, destination

    def test_architecture_publishes_and_verifies_signature_and_provenance(self):
        result, commands, destination = self.attest_architecture()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cosign = [command for command in commands if command[0] == "cosign"]
        self.assertEqual([command[:2] for command in cosign],
                         [["cosign", action] for action in ("sign", "attest", "verify", "verify-attestation")])
        for command in (cosign[1], cosign[3]):
            self.assertEqual(command[command.index("--type") + 1], "slsaprovenance1")
        for command in cosign[2:]:
            self.assertIn(IDENTITY, command)
            self.assertIn("https://token.actions.githubusercontent.com", command)
        self.assertEqual({path.name for path in destination.iterdir()},
                         {"identity.json", "provenance.json", "verified-signature.json", "verified-provenance.json"})

    def test_verification_requires_explicit_validated_identity(self):
        image = REPOSITORY + "@sha256:" + "a" * 64
        result = subprocess.run([self.command[0], "scripts/attest-image", "verify", image,
                                 str(self.base / "verify"), "architecture"], cwd=self.source,
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("validated expected identity", result.stderr)
        self.assertFalse(self.log.exists())

    def test_verify_uses_explicit_identity_and_rejects_modified_dependency_generation(self):
        image = REPOSITORY + "@sha256:" + "a" * 64
        directory = self.base / "verify"
        directory.mkdir()
        # Neither a local predicate nor a local identity may replace the explicit expected identity.
        (directory / "provenance.json").write_text('{}')
        (directory / "identity.json").write_text('{}')
        expected = self.base / "expected.json"
        identity = json.loads((self.fixtures / ("a" * 64 + ".identity.json")).read_text())
        expected.write_text(json.dumps(identity))
        command = [self.command[0], "scripts/attest-image", "verify", image,
                   str(directory), "architecture", str(expected)]
        result = subprocess.run(command, cwd=self.source, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        identity["buildInputs"][".build-inputs/composer/releases/4/composer.lock"] = "0" * 64
        expected.write_text(json.dumps(identity))
        result = subprocess.run(command, cwd=self.source, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No verified SLSA statement", result.stderr)

    def test_architecture_signature_and_provenance_failures_stop_publication(self):
        for action in ("sign", "attest", "verify", "verify-attestation"):
            with self.subTest(action=action):
                self.log.write_text("")
                result, commands, _ = self.attest_architecture("architecture_" + action)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(commands[-1][:2], ["cosign", action])

    def test_success_only_publishes_a_signed_candidate(self):
        result, commands, promotions = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(promotions, [])
        self.assertEqual((self.base / "evidence/candidate-image.txt").read_text(), INDEX + "\n")
        signatures = [command for command in commands if command[:2] == ["cosign", "sign"]]
        self.assertEqual(len(signatures), 1)
        self.assertEqual(signatures[0][-1], INDEX)
        attestations = [command for command in commands if command[:2] == ["cosign", "attest"]]
        self.assertEqual(len(attestations), 1)
        self.assertIn("slsaprovenance1", attestations[0])
        self.assertEqual(attestations[0][-1], INDEX)
        verifications = [command for command in commands if command[0] == "cosign" and command[1].startswith("verify")]
        self.assertEqual(len(verifications), 6)  # Signature and provenance for each architecture and the index.
        for command in verifications:
            self.assertIn(IDENTITY, command)
            self.assertIn("https://token.actions.githubusercontent.com", command)
            self.assertRegex(command[-1], r"@sha256:[a-f0-9]{64}$")

    def test_index_evidence_paths_are_uploadable_and_preserve_child_identities(self):
        result, _, _ = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        directory = self.base / "evidence"
        forbidden = set('\":<>|*?\r\n')
        for path in directory.rglob("*"):
            relative = path.relative_to(directory)
            for component in relative.parts:
                self.assertFalse(set(component) & forbidden, str(relative))
        for digit in "ab":
            name = "sha256-" + digit * 64
            expected = directory / "expected-children" / (name + ".json")
            identity = json.loads(expected.read_text())
            self.assertEqual(identity["image"], REPOSITORY + "@sha256:" + digit * 64)
            for filename in ("verified-signature.json", "verified-provenance.json"):
                self.assertTrue((directory / name / filename).is_file())


if __name__ == "__main__":
    unittest.main()
