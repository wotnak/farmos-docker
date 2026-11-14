#!/usr/bin/env python3
"""Copy only build sources and generated inputs into an untracked Nix flake."""

import argparse
from pathlib import Path
import shutil
import stat
import sys
import tempfile


def _kind(path):
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise ValueError(f"Nix source paths must not be symlinks: {path}")
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    raise ValueError(f"Nix source paths must be regular files or directories: {path}")


def _ignored(name):
    return (name in {".git", ".env", "__pycache__"}
            or name.startswith(".env.") or name.endswith((".pyc", ".pyo")))


def _copy(source, destination):
    if _kind(source) == "directory":
        destination.mkdir()
        for child in sorted(source.iterdir()):
            if not _ignored(child.name):
                _copy(child, destination / child.name)
        shutil.copystat(source, destination)
    else:
        shutil.copy2(source, destination)


def snapshot(root: Path) -> Path:
    """Refresh build/nix-source without changing Git's index or copying secrets."""
    root = Path(root)
    if _kind(root) != "directory":
        raise ValueError(f"Expected a source directory: {root}")
    root = root.resolve()
    sources = [("flake.nix", "file"),
               ("packages", "directory"), ("images", "directory"),
               ("tests/check-runtime.php", "file")]
    # Inspect source ancestors too, so tests/ cannot redirect the required file.
    for name, expected in sources:
        relative = Path(name)
        for ancestor in reversed(relative.parents):
            if ancestor != Path(".") and _kind(root / ancestor) != "directory":
                raise ValueError(f"Expected a source directory: {root / ancestor}")
        if _kind(root / name) != expected:
            raise ValueError(f"Expected a source {expected}: {root / name}")
    for name, expected in [("flake.lock", "file"), (".build-inputs", "directory")]:
        path = root / name
        if path.exists() or path.is_symlink():
            if _kind(path) != expected:
                raise ValueError(f"Expected a source {expected}: {path}")
            sources.append((name, expected))

    build = root / "build"
    if build.exists() or build.is_symlink():
        if _kind(build) != "directory":
            raise ValueError(f"Expected a build directory: {build}")
    else:
        build.mkdir()
    destination = build / "nix-source"
    if destination.exists() or destination.is_symlink():
        if _kind(destination) != "directory":
            raise ValueError(f"Expected a snapshot directory: {destination}")

    temporary = Path(tempfile.mkdtemp(prefix=".nix-source-", dir=build))
    previous = None
    try:
        for name, _ in sources:
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy(root / name, target)
        if destination.exists():
            # Reserve an unused sibling name for rollback if publication fails.
            previous = Path(tempfile.mkdtemp(prefix=".nix-source-old-", dir=build))
            previous.rmdir()
            destination.rename(previous)
        try:
            temporary.rename(destination)
        except BaseException:
            if previous is not None:
                backup = previous
                previous = None
                backup.rename(destination)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if previous is not None and previous.exists():
            shutil.rmtree(previous)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        print("path:" + str(snapshot(args.root)))
    except (OSError, ValueError) as error:
        print(f"Could not prepare Nix source: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
