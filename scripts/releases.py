#!/usr/bin/env python3
"""Read prepared releases. Before preparation, --field major returns the policy minimum."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
MAJOR = re.compile(r"0|[1-9][0-9]*")
SNAPSHOT = Path(".build-inputs/versions.json")


class ReleaseError(Exception):
    """Release metadata cannot safely be used."""


def version_tuple(value):
    if not isinstance(value, str) or not (match := VERSION.fullmatch(value)):
        raise ReleaseError(f"Invalid stable release version: {value!r}")
    return tuple(map(int, match.groups()))


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"Duplicate versions.json key: {key!r}")
        result[key] = value
    return result


def _minimum(data):
    if not isinstance(data, dict):
        raise ReleaseError("versions.json must contain an object")
    minimum = data.get("minimum_major")
    if type(minimum) is not int or minimum < 0:
        raise ReleaseError("versions.json must specify a nonnegative integer minimum_major")
    return minimum


def read_policy(root):
    data = json.loads((root / "versions.json").read_text(), object_pairs_hook=_unique_keys)
    _minimum(data)
    if set(data) != {"minimum_major", "development_branch"} or data["development_branch"] != "4.x":
        raise ReleaseError('Root versions.json must contain only minimum_major and development_branch "4.x"')
    return data


def minimum_major(root):
    return read_policy(root)["minimum_major"]


def validate_major(value, minimum):
    if not isinstance(value, str) or not MAJOR.fullmatch(value):
        raise ReleaseError(f"Invalid release major: {value!r}")
    if int(value) < minimum:
        raise ReleaseError(f"Release major {value} is below minimum major {minimum}")
    return value


def _validate_versions(data):
    minimum = _minimum(data)
    versions = data.get("versions")
    if not isinstance(versions, dict):
        raise ReleaseError("Generated versions.json versions must be an object")
    for key, release in versions.items():
        if not isinstance(release, dict):
            raise ReleaseError(f"Release {key} must contain an object")
        if key == "4.x":
            fields = ("constraint", "farmosRev", "farmosSourceHash", "composerProjectRev",
                      "composerProjectHash", "devHash")
        else:
            validate_major(key, minimum)
            version = release.get("version")
            if key != str(version_tuple(version)[0]):
                raise ReleaseError(f"Version {version} does not belong to release major {key}")
            fields = ("prodHash", "devHash")
        for field in fields:
            if not isinstance(release.get(field), str):
                raise ReleaseError(f"Release {key} {field} must be a string")
    return data


def read_versions(root):
    path = root / SNAPSHOT
    if (path.parent / ".preparing").exists():
        raise ReleaseError("Build inputs are still being prepared. Wait for scripts/prepare-build to finish.")
    if not path.is_file():
        raise ReleaseError("Build inputs are missing. Run scripts/prepare-build first.")
    data = _validate_versions(json.loads(path.read_text(), object_pairs_hook=_unique_keys))
    if data["minimum_major"] != minimum_major(root):
        raise ReleaseError("Build input policy changed. Run scripts/prepare-build again.")
    return data


def write_versions(root, data):
    """Atomically replace a complete generated JSON file, including provisional hashes."""
    _validate_versions(data)
    path = root / SNAPSHOT
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".versions-",
                                         suffix=".json", delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_releases(root):
    return {major: release["version"] for major, release in read_versions(root)["versions"].items()
            if MAJOR.fullmatch(major)}


def release_matrix(versions):
    return {"include": [
        {"major": major, "version": versions[major]}
        for major in sorted(versions, key=int)
    ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--major", help="Select a supported major; defaults to the latest prepared release")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--field", choices=["major", "version"])
    output.add_argument("--matrix", action="store_true")
    args = parser.parse_args(argv)
    try:
        minimum = minimum_major(args.root)
        if args.major is not None:
            validate_major(args.major, minimum)
        if args.matrix and args.major is not None:
            raise ReleaseError("--major cannot be combined with --matrix")
        # Task needs a major before there is a generated snapshot. An explicit
        # major is policy validation here; version selection still needs preparation.
        if args.field == "major" and args.major is not None:
            print(args.major)
            return 0
        if args.field == "major" and not (args.root / SNAPSHOT).exists():
            print(minimum)
            return 0
        matrix = release_matrix(read_releases(args.root))
        if args.matrix:
            print(json.dumps(matrix, separators=(",", ":")))
            return 0
        if not matrix["include"]:
            if args.field == "major":
                print(minimum)
                return 0
            raise ReleaseError("No stable release prepared. Run scripts/prepare-build --major MAJOR.")
        row = matrix["include"][-1]
        if args.major is not None:
            row = next((row for row in matrix["include"] if row["major"] == args.major), None)
            if row is None:
                raise ReleaseError(f"Release major {args.major} is not prepared. Run scripts/prepare-build --major {args.major}.")
        value = row[args.field] if args.field else row
        print(value if isinstance(value, str) else json.dumps(value))
    except (ReleaseError, OSError, ValueError, AttributeError) as error:
        print(f"Release metadata failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
