#!/usr/bin/env python3
"""Report the current latest upstream releases and development commits."""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request


API_ROOT = "https://api.github.com"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from releases import VERSION, ReleaseError, minimum_major, release_matrix, version_tuple
SHA = re.compile(r"[0-9a-fA-F]{40}")


class DiscoveryError(ReleaseError):
    """An upstream response cannot safely be used."""


def api_get(path):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "farmos-image-updater",
    }
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API_ROOT + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
            has_next = bool(re.search(r';\s*rel="next"', response.headers.get("Link", "")))
    except urllib.error.HTTPError as error:
        if error.fp is not None:
            error.close()
        raise DiscoveryError(f"GitHub API request failed: HTTP {error.code} ({path})") from error
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DiscoveryError(f"GitHub API request failed ({path})") from None
    except (ValueError, UnicodeError):
        raise DiscoveryError(f"GitHub API returned invalid JSON ({path})") from None
    return data, has_next


def validate_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise DiscoveryError("Expected a full 40-character Git commit SHA")
    return value.lower()


def latest_releases(minimum):
    stable = []
    for page in range(1, 1001):
        releases, has_next = api_get(f"/repos/farmOS/farmOS/releases?per_page=100&page={page}")
        if not isinstance(releases, list):
            raise DiscoveryError("GitHub releases response must be a list")
        for release in releases:
            if not isinstance(release, dict):
                raise DiscoveryError("Malformed GitHub release")
            if not isinstance(release.get("draft"), bool) or not isinstance(release.get("prerelease"), bool):
                raise DiscoveryError("GitHub release is missing draft/prerelease status")
            if release["draft"] or release["prerelease"]:
                continue
            tag = release.get("tag_name")
            if isinstance(tag, str) and VERSION.fullmatch(tag) and version_tuple(tag)[0] >= minimum:
                stable.append(release)
        if not has_next:
            break
    else:
        raise DiscoveryError("GitHub release pagination exceeded 1000 pages")
    if not stable:
        raise DiscoveryError("No published stable farmOS release found")
    selected = {}
    for release in stable:
        version = release["tag_name"]
        major = str(version_tuple(version)[0])
        if major not in selected or version_tuple(version) > version_tuple(selected[major]):
            selected[major] = version
    return selected


def branch_head(repository):
    result, _ = api_get(f"/repos/farmOS/{repository}/git/ref/heads/4.x")
    if not isinstance(result, dict) or result.get("ref") != "refs/heads/4.x":
        raise DiscoveryError(f"GitHub returned an unexpected {repository} branch reference")
    commit = result.get("object")
    if not isinstance(commit, dict) or commit.get("type") != "commit":
        raise DiscoveryError(f"GitHub returned an invalid {repository} branch commit")
    return validate_sha(commit.get("sha"))


def discover(root):
    selected = latest_releases(minimum_major(root))
    return {
        "release_version": max(selected.values(), key=version_tuple),
        "release_matrix": release_matrix(selected),
        "farmos_rev": branch_head("farmOS"),
        "composer_project_rev": branch_head("composer-project"),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--github-output", type=Path, help="Append detected values to this GitHub Actions output file")
    args = parser.parse_args(argv)
    try:
        result = discover(args.root)
        if args.github_output:
            with args.github_output.open("a") as output:
                for key, value in result.items():
                    formatted = json.dumps(value, separators=(",", ":")) if isinstance(value, dict) else str(value).lower() if isinstance(value, bool) else value
                    output.write(f"{key}={formatted}\n")
        print(json.dumps(result, sort_keys=True))
    except (ReleaseError, OSError, ValueError, AttributeError) as error:
        print(f"Upstream discovery failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
