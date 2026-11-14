#!/usr/bin/env python3
"""Validate named GitHub Environments and their image build matrices."""

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_config


ID = re.compile(r"[1-9][0-9]*")
ENVIRONMENT_FIELDS = {"environment", "environment-id"}

class EnvironmentError(ValueError):
    """Environment discovery or build configuration is inconsistent."""


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EnvironmentError("Duplicate JSON field: " + key)
        result[key] = value
    return result


def load_json(value):
    return json.loads(value, object_pairs_hook=_unique_keys)


def environment_name(value):
    if (not isinstance(value, str) or not value.strip()
            or any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)):
        raise EnvironmentError("Environment names must be nonempty strings without control characters")
    return value


def environment_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise EnvironmentError("Environment IDs must be canonical positive decimal strings")
    return value


def _environment_rows(rows):
    if not isinstance(rows, list):
        raise EnvironmentError("Environment matrix include must be a list")
    identifiers = set()
    names = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != ENVIRONMENT_FIELDS:
            raise EnvironmentError("Environment matrix rows must contain only environment and environment-id")
        identifier = environment_id(row["environment-id"])
        name = environment_name(row["environment"])
        if identifier in identifiers or name.casefold() in names:
            raise EnvironmentError("Environment IDs and names must be unique")
        identifiers.add(identifier)
        names.add(name.casefold())
    return sorted(rows, key=lambda row: int(row["environment-id"]))


def discover(pages):
    """Read gh api --paginate --slurp output without fetching anything."""
    if not isinstance(pages, list):
        raise EnvironmentError("Environment discovery must contain a list of response pages")
    rows = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("environments"), list):
            raise EnvironmentError("Each discovery page must contain an environments list")
        for item in page["environments"]:
            if not isinstance(item, dict):
                raise EnvironmentError("Each discovered environment must be an object")
            identifier = item.get("id")
            if type(identifier) is int:
                identifier = str(identifier)
            rows.append({"environment": item.get("name"), "environment-id": identifier})
    return {"include": _environment_rows(rows)}


def variant_matrix(configuration):
    profile = build_config.normalize(configuration)
    return {"include": [
        {"variant": variant, "output": build_config.VARIANTS[variant]["output"],
         "suite": "runtime" if variant in {"runtime", "development-runtime"} else "smoke"}
        for variant in profile["variants"]
    ]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("discover", help="Validate paginated GitHub Environments JSON from stdin")
    commands.add_parser("select", help="Read and validate the environment build profile")
    variant_parser = commands.add_parser("variant-matrix", help="Select independent variant flows")
    variant_parser.add_argument("--configuration", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "discover":
            result = discover(load_json(sys.stdin.read()))
        elif args.command == "select":
            result = build_config.load()
        else:
            if args.configuration.is_symlink() or not args.configuration.is_file():
                raise EnvironmentError("Build configuration must be a regular file")
            configuration = load_json(args.configuration.read_text())
            result = variant_matrix(configuration)
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    except (EnvironmentError, build_config.ConfigurationError, OSError, ValueError) as error:
        print(f"Build environment configuration failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
