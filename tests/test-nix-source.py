#!/usr/bin/env python3
"""Check filtered Nix snapshots against real files and a real Git index."""

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("nix_source", REPO / "scripts/nix_source.py")
nix_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nix_source)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.write("flake.nix", "{ outputs = _: {}; }")
        self.write("versions.json", "{}")
        self.write("packages/runtime/default.nix", "{}")
        self.write("images/scripts/start", "#!/bin/sh\nexit 0\n").chmod(0o755)
        self.write("tests/check-runtime.php", "<?php echo 'ok';")

    def write(self, name, content="fixture"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def snapshot(self):
        return nix_source.snapshot(self.root)

    def test_only_build_sources_and_generated_inputs_are_copied(self):
        self.write("flake.lock", "{\"nodes\":{}}")
        self.write(".build-inputs/versions.json", "{}")
        self.write(".build-inputs/composer/releases/4/composer.lock", "{}")
        for name in [".env", ".git/config", "build/huge-output", "tests/results/secret",
                     "packages/.env", "images/.env.local", "packages/__pycache__/module.pyc"]:
            self.write(name, "private")
        destination = self.snapshot()
        actual = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
        self.assertEqual(actual, {"flake.nix", "flake.lock", "versions.json",
                                 "packages/runtime/default.nix", "images/scripts/start",
                                 "tests/check-runtime.php", ".build-inputs/versions.json",
                                 ".build-inputs/composer/releases/4/composer.lock"})
        self.assertEqual(stat.S_IMODE((destination / "images/scripts/start").stat().st_mode), 0o755)

    def test_bootstrap_works_without_optional_generated_inputs(self):
        destination = self.snapshot()
        self.assertFalse((destination / "flake.lock").exists())
        self.assertFalse((destination / ".build-inputs").exists())

    def test_refresh_removes_stale_sources_and_generated_inputs(self):
        old = self.write("packages/stale.nix")
        lock = self.write("flake.lock")
        self.snapshot()
        old.unlink()
        lock.unlink()
        self.write("images/new.nix", "new content")
        destination = self.snapshot()
        self.assertFalse((destination / "packages/stale.nix").exists())
        self.assertFalse((destination / "flake.lock").exists())
        self.assertEqual((destination / "images/new.nix").read_text(), "new content")
        self.assertEqual(list((self.root / "build").iterdir()), [destination])

    def test_git_index_is_unchanged(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "/build/\n/.build-inputs/\n/flake.lock\n")
        subprocess.run(["git", "add", "versions.json"], cwd=self.root, check=True)
        before = (self.root / ".git/index").read_bytes()
        self.write(".build-inputs/versions.json", "{}")
        self.write("flake.lock", "{}")
        self.snapshot()
        self.assertEqual((self.root / ".git/index").read_bytes(), before)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        tracked = subprocess.check_output(["git", "ls-files"], cwd=self.root, text=True).splitlines()
        self.assertFalse(any(name.startswith(("build/", ".build-inputs/")) or name == "flake.lock" for name in tracked))

    def test_missing_required_source_preserves_existing_snapshot(self):
        destination = self.snapshot()
        (self.root / "flake.nix").unlink()
        with self.assertRaises(OSError):
            self.snapshot()
        self.assertTrue((destination / "flake.nix").is_file())

    def test_copy_failure_preserves_existing_snapshot_and_cleans_temporary_tree(self):
        destination = self.snapshot()
        original = (destination / "versions.json").read_text()
        self.write("versions.json", "changed")
        with patch.object(nix_source.shutil, "copy2", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self.snapshot()
        self.assertEqual((destination / "versions.json").read_text(), original)
        self.assertEqual(list((self.root / "build").iterdir()), [destination])

    def test_source_symlinks_and_special_files_are_rejected(self):
        self.snapshot()
        path = self.root / "packages/unsafe"
        for kind in ["symlink", "fifo"]:
            with self.subTest(kind=kind):
                if kind == "symlink":
                    path.symlink_to(self.root / ".env")
                else:
                    os.mkfifo(path)
                with self.assertRaises(ValueError):
                    self.snapshot()
                path.unlink()
        self.assertEqual([p.name for p in (self.root / "build").iterdir()], ["nix-source"])

    def test_publication_failure_restores_previous_snapshot(self):
        destination = self.snapshot()
        self.write("versions.json", "changed")
        rename = Path.rename

        def fail_publication(path, target):
            if path.name.startswith(".nix-source-") and not path.name.startswith(".nix-source-old-"):
                raise OSError("publication failed")
            return rename(path, target)

        with patch.object(Path, "rename", new=fail_publication):
            with self.assertRaisesRegex(OSError, "publication failed"):
                self.snapshot()
        self.assertEqual((destination / "versions.json").read_text(), "{}")
        self.assertEqual(list((self.root / "build").iterdir()), [destination])

    def test_source_ancestor_symlink_is_rejected(self):
        (self.root / "tests").rename(self.root / "actual-tests")
        (self.root / "tests").symlink_to("actual-tests", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.snapshot()

    def test_destination_or_build_symlink_is_rejected_without_touching_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        marker = outside / "keep"
        marker.write_text("safe")
        for name in ["build", "build/nix-source"]:
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(exist_ok=True)
                path.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    self.snapshot()
                self.assertEqual(marker.read_text(), "safe")
                path.unlink()

    def test_cli_prints_explicit_path_reference(self):
        result = subprocess.run([sys.executable, str(REPO / "scripts/nix_source.py"),
                                 "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "path:" + str(self.root / "build/nix-source") + "\n")


if __name__ == "__main__":
    unittest.main()
