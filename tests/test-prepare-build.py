#!/usr/bin/env python3
"""Exercise fresh input generation with real subprocesses and a mocked Nix CLI."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
prepare = SimpleNamespace(**runpy.run_path(str(REPO / "scripts/prepare-build"), run_name="prepare_build_tests"))
NEW_HASH = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

MOCK_NIX = r'''
import json, os, re, sys
from pathlib import Path
root = Path.cwd()
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\n')
mode = os.environ.get('PREPARE_TEST_MODE', '')
if 'flake' in args:
    if mode == 'nix-update-fail':
        sys.exit('fresh flake update failed')
    reference = args[args.index('--flake') + 1]
    assert reference.startswith('path:')
    source = Path(reference.removeprefix('path:'))
    assert source == root / 'build/nix-source'
    (source / 'flake.lock').write_text('{"fresh":true}')
    sys.exit(0)
if 'hash' in args:
    print('sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
    sys.exit(0)
assert 'build' in args
assert '--rebuild' not in args
if '--expr' in args:
    expression = args[args.index('--expr') + 1]
    reference = json.loads(re.search(r'builtins.getFlake ("(?:\\.|[^"\\])*")', expression).group(1))
    assert reference.startswith('path:')
    source = Path(reference.removeprefix('path:'))
    assert source == root / 'build/nix-source'
    assert (source / '.build-inputs/.preparing').is_file()
    assert json.loads((source / '.build-inputs/versions.json').read_text())['versions']
    nonce = re.search(r'-prepare-([a-z0-9]+)', expression).group(1)
    destination = root / ('resolver-' + nonce)
    if 'outputHash' not in expression:
        destination.mkdir()
        (destination / 'composer.json').write_text(json.dumps({'resolution': nonce}))
        if mode != 'missing-lock':
            (destination / 'composer.lock').write_text('broken' if mode == 'malformed-lock' else json.dumps({'resolution': nonce}))
        if mode == 'resolver-fail':
            sys.exit('fresh composer resolution failed')
        print('error: hash mismatch in fixed-output derivation', file=sys.stderr)
        print('       got: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=', file=sys.stderr)
        sys.exit(1)
    print(destination)
else:
    reference = next(arg for arg in args if arg.startswith('path:'))
    path, attr = reference.removeprefix('path:').split('#', 1)
    source = Path(path)
    assert source == root / 'build/nix-source'
    assert (source / '.build-inputs/.preparing').is_file()
    data = json.loads((source / '.build-inputs/versions.json').read_text())['versions']
    selector = '4.x' if '4x' in attr else re.search(r'farmos-([0-9]+)', attr).group(1)
    field = 'devHash' if '-dev-' in attr else 'prodHash'
    if mode == 'app-fail' or mode == 'app-verify-fail' and data[selector][field]:
        sys.exit('application build failed')
    if not data[selector][field] and mode != 'cached-app':
        print('error: hash mismatch in fixed-output derivation', file=sys.stderr)
        print('       got: sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=', file=sys.stderr)
        sys.exit(1)
    print(root / 'application-output')
'''


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "versions.json").write_text('{"minimum_major":4,"development_branch":"4.x"}\n')
        (self.root / "flake.nix").write_text('{}\n')
        for directory in ('packages', 'images', 'tests'):
            (self.root / directory).mkdir()
        (self.root / 'packages/default.nix').write_text('{}\n')
        (self.root / 'images/default.nix').write_text('{}\n')
        (self.root / 'images/source.json').write_text('{}\n')
        (self.root / 'tests/check-runtime.php').write_text('<?php\n')
        self.policy_bytes = (self.root / "versions.json").read_bytes()
        mock = self.root / "mock nix"
        mock.write_text(f"#!{sys.executable}\n" + MOCK_NIX)
        mock.chmod(0o755)
        env = patch.dict(os.environ, {"NIX": str(mock), "NIX_FLAGS": '--option test-flag "two words"',
                                      "NIX_SYSTEM": "aarch64-linux", "PREPARE_TEST_MODE": ""})
        env.start()
        self.addCleanup(env.stop)
        self.latest = patch.object(prepare.discovery, "latest_releases", return_value={"10": "10.0.2", "4": "4.10.9"}).start()
        self.branch = patch.object(prepare.discovery, "branch_head", side_effect=lambda repo: "a" * 40 if repo == "farmOS" else "b" * 40).start()
        self.archive = patch.object(prepare.urllib.request, "urlopen", side_effect=lambda *args, **kwargs: io.BytesIO(b"archive bytes")).start()
        self.addCleanup(patch.stopall)

    def run_prepare(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            return prepare.prepare(self.root, **kwargs)

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def seed_stale(self):
        (self.root / ".build-inputs/composer/releases/99").mkdir(parents=True)
        (self.root / ".build-inputs/composer/releases/99/composer.lock").write_text('saved lock must never be reused')
        (self.root / ".build-inputs/versions.json").write_text('broken stale snapshot')
        (self.root / "flake.lock").write_text('stale nix lock')

    def assert_invalidated(self):
        self.assertFalse((self.root / ".build-inputs").exists())
        self.assertFalse((self.root / "flake.lock").exists())
        self.assertFalse((self.root / ".prepare-build.lock").exists())
        self.assertFalse((self.root / "build/nix-source").exists())
        self.assertEqual((self.root / "versions.json").read_bytes(), self.policy_bytes)

    def test_default_prepares_every_current_major_and_branch(self):
        self.seed_stale()
        data = self.run_prepare()
        self.assertEqual(list(data['versions']), ['4', '10', '4.x'])
        self.assertEqual(data['versions']['4']['version'], '4.10.9')
        self.assertFalse((self.root / '.build-inputs/composer/releases/99').exists())
        for selector, entry in data['versions'].items():
            destination = '4.x' if selector == '4.x' else 'releases/' + selector
            for name in ['composer.json', 'composer.lock']:
                self.assertIn('resolution', json.loads((self.root / '.build-inputs/composer' / destination / name).read_text()))
            self.assertEqual(entry['devHash'], NEW_HASH)
        self.assertEqual(data['versions']['4']['prodHash'], NEW_HASH)
        self.assertEqual(data['versions']['4.x']['farmosRev'], 'a' * 40)
        self.assertEqual(data['versions']['4.x']['farmosSourceHash'], 'sha256-' + prepare.base64.b64encode(prepare.hashlib.sha256(b'archive bytes').digest()).decode())
        self.latest.assert_called_once_with(4)
        self.assertEqual(self.branch.call_count, 2)
        self.assertEqual(self.archive.call_count, 2)
        self.assertEqual(sum('flake' in args for args in self.calls()), 1)
        self.assertFalse((self.root / '.build-inputs/.preparing').exists())
        source = self.root / 'build/nix-source'
        self.assertFalse((source / '.build-inputs/.preparing').exists())
        self.assertEqual(json.loads((source / '.build-inputs/versions.json').read_text()), data)
        self.assertEqual((source / 'flake.lock').read_bytes(), (self.root / 'flake.lock').read_bytes())
        for path in (self.root / '.build-inputs').rglob('*'):
            if path.is_file():
                self.assertEqual((source / path.relative_to(self.root)).read_bytes(), path.read_bytes())
        self.assertEqual((self.root / 'versions.json').read_bytes(), self.policy_bytes)

    def test_major_scope_has_no_placeholder_branch_or_other_majors(self):
        data = self.run_prepare(major='4')
        self.assertEqual(list(data['versions']), ['4'])
        self.assertFalse((self.root / '.build-inputs/composer/4.x').exists())
        self.assertFalse((self.root / '.build-inputs/composer/releases/10').exists())
        self.branch.assert_not_called()
        self.archive.assert_not_called()

    def test_branch_scope_has_no_stable_lines(self):
        data = self.run_prepare(branch_only=True)
        self.assertEqual(list(data['versions']), ['4.x'])
        self.assertFalse((self.root / '.build-inputs/composer/releases').exists())
        self.latest.assert_not_called()

    def test_repeated_invocations_resolve_again_with_distinct_derivation_names(self):
        self.run_prepare(major='4')
        before = json.loads((self.root / '.build-inputs/composer/releases/4/composer.lock').read_text())
        self.run_prepare(major='4')
        after = json.loads((self.root / '.build-inputs/composer/releases/4/composer.lock').read_text())
        self.assertNotEqual(before, after)
        self.assertEqual(sum('flake' in args for args in self.calls()), 2)
        first_attempts = [args for args in self.calls() if '--expr' in args and 'outputHash' not in args[args.index('--expr') + 1]]
        self.assertEqual(len(first_attempts), 2)
        self.assertNotEqual(first_attempts[0], first_attempts[1])

    def test_prod_and_dev_share_one_resolution_and_never_rebuild(self):
        self.run_prepare(major='4')
        expressions = [args[args.index('--expr') + 1] for args in self.calls() if '--expr' in args]
        self.assertEqual(len(expressions), 2)
        self.assertEqual(len({re.search(r'-prepare-([a-z0-9]+)', expr).group(1) for expr in expressions}), 1)
        self.assertIn('."farmos-4-dev-app".resolveDependencies', expressions[0])
        self.assertIn("pname = old.pname", expressions[0])
        self.assertNotIn("old.name", expressions[0])
        source = 'path:' + str(self.root.resolve() / 'build/nix-source')
        self.assertEqual(sum(source + '#"farmos-4-app"' in args for args in self.calls()), 2)
        self.assertEqual(sum(source + '#"farmos-4-dev-app"' in args for args in self.calls()), 2)
        self.assertFalse(any('--rebuild' in args for args in self.calls()))

    def test_nix_executable_flags_and_system_are_honored(self):
        self.run_prepare(major='4')
        for args in self.calls():
            self.assertEqual(args[:4], ['--option', 'test-flag', 'two words', 'flake'] if 'flake' in args else ['--option', 'test-flag', 'two words', 'build'])
            if 'build' in args:
                self.assertEqual(args[-2:], ['--system', 'aarch64-linux'])
                if '--expr' in args:
                    self.assertIn('.packages.${"aarch64-linux"}', args[args.index('--expr') + 1])

    def test_cached_application_outputs_get_explicit_hashes_without_rebuild(self):
        with patch.dict(os.environ, {'PREPARE_TEST_MODE': 'cached-app'}):
            data = self.run_prepare(major='4')
        self.assertEqual(data['versions']['4']['prodHash'], NEW_HASH)
        self.assertEqual(data['versions']['4']['devHash'], NEW_HASH)
        self.assertEqual(sum('hash' in args for args in self.calls()), 2)
        self.assertFalse(any('--rebuild' in args for args in self.calls()))

    def test_failures_at_each_stage_remove_stale_and_partial_inputs(self):
        for mode in ['nix-update-fail', 'resolver-fail', 'missing-lock', 'malformed-lock', 'app-fail', 'app-verify-fail']:
            with self.subTest(mode=mode):
                self.seed_stale()
                with patch.dict(os.environ, {'PREPARE_TEST_MODE': mode}), self.assertRaises((prepare.ReleaseError, OSError, ValueError)):
                    self.run_prepare(major='4')
                self.assert_invalidated()

    def test_discovery_and_archive_failure_invalidate_generation(self):
        for function in [self.latest, self.archive]:
            with self.subTest(stage=function):
                self.seed_stale()
                function.side_effect = prepare.PreparationError('network unavailable')
                with self.assertRaises(prepare.PreparationError):
                    self.run_prepare()
                self.assert_invalidated()
                function.side_effect = None

    def test_unknown_supported_major_invalidates_previous_generation(self):
        self.seed_stale()
        with self.assertRaisesRegex(prepare.PreparationError, 'No published stable'):
            self.run_prepare(major='5')
        self.assert_invalidated()

    def test_invalid_major_fails_before_nix_or_mutation(self):
        self.seed_stale()
        for major in ['04', '3', '4.x', '../4', '4\n']:
            with self.subTest(major=major), self.assertRaises(prepare.ReleaseError):
                self.run_prepare(major=major)
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.root / 'flake.lock').read_text(), 'stale nix lock')

    def test_concurrent_prepare_does_not_delete_active_inputs(self):
        self.seed_stale()
        (self.root / '.prepare-build.lock').mkdir()
        with self.assertRaisesRegex(prepare.PreparationError, 'Another preparation'):
            self.run_prepare(major='4')
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.root / '.build-inputs/versions.json').exists())

    def test_success_and_failures_preserve_git_index_and_unrelated_changes(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('/.build-inputs/\n/flake.lock\n/.prepare-build.lock/\n/build/\n')
        note = self.root / 'notes.txt'
        note.write_text('staged unrelated text\n')
        subprocess.run(['git', 'add', 'notes.txt'], cwd=self.root, check=True)
        note.write_text('unstaged unrelated text\n')
        index = self.root / '.git/index'
        original_index = index.read_bytes()
        self.run_prepare(major='4')
        self.assertEqual(index.read_bytes(), original_index)
        self.assertEqual(note.read_text(), 'unstaged unrelated text\n')
        self.assertEqual(subprocess.check_output(['git', 'show', ':notes.txt'], cwd=self.root, text=True),
                         'staged unrelated text\n')
        self.assertEqual(subprocess.check_output(['git', 'ls-files'], cwd=self.root, text=True), 'notes.txt\n')
        self.assertTrue((self.root / 'build/nix-source/.build-inputs/versions.json').is_file())
        for mode in ['nix-update-fail', 'resolver-fail', 'missing-lock', 'malformed-lock', 'app-fail', 'app-verify-fail']:
            with self.subTest(mode=mode):
                self.seed_stale()
                with patch.dict(os.environ, {'PREPARE_TEST_MODE': mode}), self.assertRaises((prepare.ReleaseError, OSError, ValueError)):
                    self.run_prepare(major='4')
                self.assert_invalidated()
                self.assertEqual(index.read_bytes(), original_index)
                self.assertEqual(note.read_text(), 'unstaged unrelated text\n')
                self.assertEqual(subprocess.check_output(['git', 'ls-files'], cwd=self.root, text=True), 'notes.txt\n')

    def test_archive_error_does_not_expose_response_details(self):
        with patch.object(prepare.urllib.request, 'urlopen', side_effect=prepare.urllib.error.URLError('private detail')):
            with self.assertRaisesRegex(prepare.PreparationError, 'Could not download farmOS archive') as raised:
                prepare.archive_hash('farmOS', 'a' * 40)
        self.assertNotIn('private detail', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
