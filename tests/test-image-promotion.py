#!/usr/bin/env python3
"""Exercise the all-images publication gate without a registry."""
import importlib.machinery
import importlib.util
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
loader = importlib.machinery.SourceFileLoader('promotion', str(ROOT / 'scripts/promote-images'))
spec = importlib.util.spec_from_loader(loader.name, loader)
promotion = importlib.util.module_from_spec(spec)
loader.exec_module(promotion)
IMAGE = 'ghcr.io/owner/farmos@sha256:'


class ImagePromotionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.indexes = self.root / 'indexes'
        self.children = self.root / 'children'
        self.destination = self.root / 'promotion'
        self.destination.mkdir()
        self.context = {'source': 'https://github.com/owner/farmos', 'revision': 'd' * 40,
                        'buildInputs': {'flake.lock': 'e' * 64}, 'sourceMetadataSha256': 'f' * 64}
        self.workflow = {'GITHUB_RUN_ID': '123', 'GITHUB_WORKFLOW_REF': 'workflow', 'GITHUB_SHA': 'd' * 40}
        self.builds = [dict(system=system, image=IMAGE + digit * 64, output='farmos-4')
                       for system, digit in [('aarch64-linux', 'a'), ('x86_64-linux', 'b')]]
        self.identity = {**self.context, 'workflow': self.workflow, 'image': IMAGE + 'c' * 64,
                         'output': 'farmos-4', 'children': [{key: item[key] for key in ('system', 'image')} for item in self.builds]}
        self.write(self.indexes / 'release/identity.json', self.identity)
        for child in self.builds:
            self.write(self.children / child['system'] / 'identity.json', child)
        self.commands = []
        self.failed_image = None
        self.registry = {'manifests': [{'digest': 'sha256:' + digit * 64, 'platform': {'architecture': arch, 'os': 'linux'}}
                                      for digit, arch in [('a', 'arm64'), ('b', 'amd64')]]}
        self.env = patch.dict(os.environ, {'IMAGE_REPOSITORY': 'ghcr.io/owner/farmos', 'GITHUB_REPOSITORY': 'owner/farmos', 'GITHUB_SERVER_URL': 'https://github.com',
                                         'GITHUB_REF': 'refs/heads/main', 'SOURCE_REVISION': 'd' * 40, 'DEFAULT_BRANCH': 'main'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def run_command(self, root, *command, **kwargs):
        self.commands.append(command)
        if command[:2] == ('scripts/attest-image', 'verify') and command[2] == self.failed_image:
            raise subprocess.CalledProcessError(1, command)
        stdout = json.dumps(self.registry) if '--raw' in command else 'd' * 40 + '\trefs/heads/main\n'
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    def plan(self, outputs=None):
        with patch.object(promotion.evidence, 'checkout_identity', return_value=self.context), \
             patch.object(promotion.evidence, 'invocation', return_value=self.workflow), \
             patch.object(promotion.evidence, 'validate_children', return_value=self.builds), \
             patch.object(promotion, 'run', side_effect=self.run_command):
            return promotion.plan(self.root, self.indexes, self.children,
                                  outputs or {'farmos-4': ['4']}, self.destination)

    def test_missing_any_required_index_blocks_the_entire_set(self):
        with self.assertRaisesRegex(ValueError, 'Missing index'):
            self.plan({'farmos-4': ['4'], 'farmos-4x-dev': ['4.x-dev']})
        self.assertEqual(self.commands, [])

    def test_release_set_has_exactly_one_tag_per_variant_and_major(self):
        with patch.object(promotion.releases, 'read_releases', return_value={'4': '4.1.2', '40': '40.0.4'}):
            outputs = promotion.expected_outputs(self.root)
            selected = promotion.expected_outputs(self.root, major='4')
        expected = {'farmos-' + major + suffix: [major + suffix]
                    for major in ('4', '40')
                    for suffix in ('', '-dev', '-runtime', '-dev-runtime')}
        self.assertEqual(outputs, {**expected, 'farmos-4x-dev': ['4.x-dev']})
        self.assertEqual(selected, {key: value for key, value in expected.items()
                                    if key.startswith('farmos-4-') or key == 'farmos-4'})
        with self.assertRaisesRegex(ValueError, 'farmos-4-dev-runtime'):
            self.plan(selected)
        self.assertEqual(self.commands, [])

    def test_development_runtime_requires_signatures_and_provenance(self):
        output = 'farmos-4-dev-runtime'
        self.identity['output'] = output
        self.write(self.indexes / 'release/identity.json', self.identity)
        for child in self.builds:
            child['output'] = output
            self.write(self.children / child['system'] / 'identity.json', child)
        plan = self.plan({output: ['4-dev-runtime']})
        self.assertEqual(plan, [{'output': output, 'image': IMAGE + 'c' * 64,
                                 'tags': ['4-dev-runtime']}])
        signatures = {command[2] for command in self.commands if command[:2] == ('scripts/attest-image', 'verify')}
        self.assertEqual(signatures, {IMAGE + digit * 64 for digit in 'abc'})
        self.failed_image = self.builds[0]['image']
        with self.assertRaises(subprocess.CalledProcessError):
            self.plan({output: ['4-dev-runtime']})

    def test_unknown_or_noncanonical_major_cannot_expand_the_publication_scope(self):
        with patch.object(promotion.releases, 'read_releases', return_value={'4': '4.1.2', '40': '40.0.4'}):
            for major in ('', '04', '4.0', '4x', '400'):
                with self.subTest(major=major), self.assertRaisesRegex(ValueError, 'No matching release majors'):
                    promotion.expected_outputs(self.root, major=major)
        with patch.object(promotion.releases, 'read_releases', side_effect=AssertionError('Must not read stable releases')):
            self.assertEqual(promotion.expected_outputs(self.root, branch_only=True),
                             {'farmos-4x-dev': ['4.x-dev']})

    def test_other_major_and_branch_indexes_do_not_replace_missing_requested_outputs(self):
        for output in ('farmos-40', 'farmos-4x-dev'):
            self.write(self.indexes / output / 'identity.json', {**self.identity, 'output': output})
        self.assertEqual(self.plan()[0]['output'], 'farmos-4')
        (self.indexes / 'release/identity.json').unlink()
        self.commands.clear()
        with self.assertRaisesRegex(ValueError, 'Missing index evidence: farmos-4'):
            self.plan()
        self.assertEqual(self.commands, [])

    def test_failed_signature_or_provenance_verification_prevents_all_tag_mutations(self):
        for image in [child['image'] for child in self.builds] + [self.identity['image']]:
            with self.subTest(image=image):
                self.commands.clear()
                self.failed_image = image
                with self.assertRaises(subprocess.CalledProcessError):
                    self.plan()
                self.assertFalse(any('create' in command for command in self.commands))

    def test_mismatched_index_identity_is_rejected(self):
        changes = [('source', 'https://github.com/other/repo'), ('revision', '0' * 40),
                   ('buildInputs', {}), ('sourceMetadataSha256', '0' * 64),
                   ('workflow', {**self.workflow, 'GITHUB_RUN_ID': '456'}),
                   ('children', self.identity['children'][:1]),
                   ('image', 'ghcr.io/other/repo@sha256:' + 'c' * 64)]
        for field, value in changes:
            with self.subTest(field=field):
                self.write(self.indexes / 'release/identity.json', {**self.identity, field: value})
                with self.assertRaises(ValueError):
                    self.plan()
                self.assertEqual(self.commands, [])

    def test_wrong_registry_children_are_rejected(self):
        changes = [('digest', 'sha256:' + '0' * 64),
                   ('architecture', 'amd64'), ('os', 'windows')]
        for field, value in changes:
            with self.subTest(field=field):
                descriptor = self.registry['manifests'][0]
                subject = descriptor if field == 'digest' else descriptor['platform']
                original = subject[field]
                subject[field] = value
                with self.assertRaisesRegex(ValueError, 'descriptors'):
                    self.plan()
                subject[field] = original
                self.assertFalse(any('create' in command for command in self.commands))

    def test_success_checks_all_evidence_then_promotes_exact_digest(self):
        plan = self.plan()
        self.assertFalse(any('create' in command for command in self.commands))
        verifications = [command for command in self.commands
                         if command[:2] == ('scripts/attest-image', 'verify')]
        self.assertEqual([command[2] for command in verifications],
                         [child['image'] for child in self.builds] + [self.identity['image']])
        self.assertEqual([command[-2] for command in verifications],
                         ['architecture', 'architecture', 'index'])
        for command, expected in zip(verifications, [*self.builds, self.identity]):
            self.assertEqual(json.loads(Path(command[-1]).read_text()), expected)
        with patch.object(promotion, 'run', side_effect=self.run_command):
            promotion.promote(self.root, plan, self.destination)
        self.assertEqual(self.commands[-1], ('docker', 'buildx', 'imagetools', 'create',
                                           '--tag', 'ghcr.io/owner/farmos:4', IMAGE + 'c' * 64))
        self.assertEqual(len(json.loads((self.destination / 'promotion.json').read_text())['published']), 1)

    def test_default_registry_is_independent_of_the_github_source_repository(self):
        repository = 'ghcr.io/wotnak/farmos'
        for child in self.builds:
            child['image'] = repository + '@' + child['image'].split('@')[1]
            self.write(self.children / child['system'] / 'identity.json', child)
        self.identity['image'] = repository + '@sha256:' + 'c' * 64
        self.identity['children'] = [{key: child[key] for key in ('system', 'image')} for child in self.builds]
        self.write(self.indexes / 'release/identity.json', self.identity)
        with patch.dict(os.environ):
            os.environ.pop('IMAGE_REPOSITORY', None)
            plan = self.plan()
        self.assertEqual(plan[0]['image'], self.identity['image'])

    def test_advanced_default_branch_leaves_tags_unchanged(self):
        plan = self.plan()
        with patch.object(promotion, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='0' * 40 + '\trefs/heads/main\n')):
            with self.assertRaisesRegex(ValueError, 'branch advanced'):
                promotion.promote(self.root, plan, self.destination)
        self.assertFalse((self.destination / 'promotion.json').exists())

    def test_same_commit_on_other_branch_cannot_publish_an_untrusted_signer(self):
        plan = self.plan()
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/feature'}):
            with self.assertRaisesRegex(ValueError, 'workflow on the default branch'):
                promotion.promote(self.root, plan, self.destination)
        self.assertFalse((self.destination / 'promotion.json').exists())


class WorkflowArtifactTests(unittest.TestCase):
    def downloads(self, filename):
        workflow = (ROOT / '.github/workflows' / filename).read_text()
        downloads = []
        for step in re.split(r'(?m)^      - ', workflow):
            if re.search(r'uses: actions/download-artifact@\S+', step):
                downloads.append(dict(re.findall(r'^          (name|pattern): (.+)$', step, re.MULTILINE)))
        return downloads

    def test_release_downloads_have_exact_major_boundaries(self):
        workflow = (ROOT / '.github/workflows/release-images.yaml').read_text()
        architecture_template = re.search(r'^          name: (image-evidence-.+)$', workflow, re.MULTILINE)[1]
        artifacts = {
            architecture_template.replace('${{ inputs.release-major }}', major)
                .replace('${{ matrix.suffix }}', suffix).replace('${{ matrix.arch }}', arch)
            for major in ('4', '40')
            for suffix in ('', '-dev', '-runtime', '-dev-runtime')
            for arch in ('amd64', 'arm64')
        } | {'image-evidence-4x-dev-amd64', 'image-evidence-4x-dev-arm64'}
        expected = {'image-evidence-4' + suffix + '-' + arch
                    for suffix in ('', '-dev', '-runtime', '-dev-runtime')
                    for arch in ('amd64', 'arm64')}
        downloads = self.downloads('release-images.yaml')
        patterns = [item['pattern'] for item in downloads if 'pattern' in item]
        self.assertEqual(len(patterns), 2)  # Manifest and promotion jobs.
        for pattern in patterns:
            pattern = pattern.replace('${{ inputs.release-major }}', '4')
            self.assertEqual({name for name in artifacts if fnmatch.fnmatchcase(name, pattern)}, expected)
        index_downloads = [item for item in downloads if 'index-evidence-' in str(item)]
        self.assertEqual(index_downloads, [{'name': 'index-evidence-${{ inputs.release-major }}'}])
        index_name = index_downloads[0]['name'].replace('${{ inputs.release-major }}', '4')
        self.assertEqual([name for name in ('index-evidence-4', 'index-evidence-40', 'index-evidence-4x-dev')
                          if name == index_name], ['index-evidence-4'])

    def test_hourly_promotion_downloads_all_majors_and_branch_evidence(self):
        downloads = self.downloads('hourly-images.yaml')
        patterns = {item['pattern'] for item in downloads if 'pattern' in item}
        self.assertEqual(patterns, {'image-evidence-*', 'index-evidence-*'})
        for pattern in patterns:
            for name in ('4', '40', '4x-dev'):
                self.assertTrue(fnmatch.fnmatchcase(pattern[:-1] + name, pattern))


if __name__ == '__main__':
    unittest.main()
