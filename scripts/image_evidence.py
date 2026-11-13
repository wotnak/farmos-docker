#!/usr/bin/env python3
"""Record the checked-out source and generate SLSA v1 image provenance predicates."""

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


SYSTEMS = {"aarch64-linux", "x86_64-linux"}
IMAGE = re.compile(r"([a-z0-9][a-z0-9.-]*(?::[0-9]+)?/[a-z0-9]+(?:[._/-][a-z0-9]+)*)@sha256:([0-9a-f]{64})")
OUTPUT = re.compile(r"farmos-(?:0|[1-9][0-9]*)(?:-dev-runtime|-dev|-runtime)?|farmos-4x-dev")
SHA = re.compile(r"[0-9a-f]{40}")
INPUT_FILES = ("versions.json", "flake.lock", ".build-inputs/versions.json")
GENERATED_ROOT = ".build-inputs"


class EvidenceError(Exception):
    """Evidence does not describe a consistent build."""


def run(root, *command):
    return subprocess.check_output(command, cwd=root, text=True).strip()


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"Expected a regular evidence input: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source(root):
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not server.startswith("https://") or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise EvidenceError("GITHUB_SERVER_URL and GITHUB_REPOSITORY must identify the build repository")
    revision = run(root, "git", "rev-parse", "HEAD")
    if not SHA.fullmatch(revision):
        raise EvidenceError("Expected a full Git commit SHA")
    expected = os.environ.get("SOURCE_REVISION")
    if expected and expected != revision:
        raise EvidenceError("SOURCE_REVISION does not match the actual checked-out HEAD")
    return {"source": server.rstrip("/") + "/" + repository, "revision": revision}


def is_generated(path):
    return path == "flake.lock" or path.startswith(GENERATED_ROOT + "/")


def check_tracked_source(root, allow_metadata=False):
    changed = subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only", "-z", "--no-renames"], cwd=root
    ).decode().split("\0")
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    unexpected = [path for path in changed + untracked if path and not is_generated(path)
                  and not (allow_metadata and path == "images/source.json")]
    if unexpected:
        raise EvidenceError("Unrecorded changes outside generated build inputs: " + ", ".join(unexpected))


def prepare_source(root):
    check_tracked_source(root, allow_metadata=True)
    build_input_inventory(root)
    metadata = source(root)
    path = root / "images/source.json"
    if path.is_symlink():
        raise EvidenceError("Source metadata must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metadata, indent=2) + "\n")


def build_input_inventory(root):
    directory = root / GENERATED_ROOT
    if directory.is_symlink() or not directory.is_dir():
        raise EvidenceError("Missing regular build input directory: " + GENERATED_ROOT)
    if (directory / ".preparing").exists() or (directory / ".preparing").is_symlink():
        raise EvidenceError("Build input preparation is incomplete")
    paths = {root / name for name in INPUT_FILES}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise EvidenceError(f"Build input inventory must not contain symlinks: {path}")
        if path.is_file():
            paths.add(path)
        elif not path.is_dir():
            raise EvidenceError(f"Expected a regular build input: {path}")
    # Read the generated selection, rather than assuming every publication includes the branch.
    snapshot = root / ".build-inputs/versions.json"
    digest(snapshot)
    versions = json.loads(snapshot.read_text()).get("versions")
    if not isinstance(versions, dict) or not versions:
        raise EvidenceError("Generated versions.json must select build inputs")
    for key in versions:
        if key != "4.x" and not re.fullmatch(r"0|[1-9][0-9]*", key):
            raise EvidenceError("Invalid generated build selection: " + key)
        prefix = "4.x" if key == "4.x" else "releases/" + key
        for name in ("composer.json", "composer.lock"):
            paths.add(directory / "composer" / prefix / name)
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


def checkout_identity(root):
    check_tracked_source(root, allow_metadata=True)
    metadata = source(root)
    metadata_path = root / "images/source.json"
    metadata_digest = digest(metadata_path)
    if json.loads(metadata_path.read_text()) != metadata:
        raise EvidenceError("images/source.json does not match the actual checked-out source")
    return {**metadata, "buildInputs": build_input_inventory(root), "sourceMetadataSha256": metadata_digest}


def image_parts(value):
    match = IMAGE.fullmatch(value)
    if not match:
        raise EvidenceError(f"Expected an immutable repository@sha256 image reference: {value!r}")
    return match.groups()


def output_name(value):
    if not OUTPUT.fullmatch(value):
        raise EvidenceError(f"Unsupported Nix image output: {value!r}")
    return value


def invocation():
    values = {name: os.environ.get(name, "") for name in
              ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW_REF", "GITHUB_SHA")}
    if not values["GITHUB_RUN_ID"].isdigit() or not values["GITHUB_RUN_ATTEMPT"].isdigit():
        raise EvidenceError("GITHUB_RUN_ID and GITHUB_RUN_ATTEMPT are required")
    if not values["GITHUB_WORKFLOW_REF"]:
        raise EvidenceError("GITHUB_WORKFLOW_REF is required")
    return values


def materials(identity):
    return [{"uri": "git+" + identity["source"], "digest": {"gitCommit": identity["revision"]}}] + [
        {"name": path, "uri": "file:" + path, "digest": {"sha256": value}}
        for path, value in sorted(identity["buildInputs"].items())
    ] + [{"name": "images/source.json", "uri": "file:images/source.json",
          "digest": {"sha256": identity["sourceMetadataSha256"]}}]


def predicate(identity, kind, dependencies, parameters):
    context = identity["workflow"]
    return {
        "buildDefinition": {
            "buildType": identity["source"] + "/blob/" + identity["revision"]
                         + "/docs/image-provenance.md#" + kind,
            "externalParameters": {"source": identity["source"], "revision": identity["revision"],
                                   **parameters},
            "internalParameters": context,
            "resolvedDependencies": dependencies,
        },
        "runDetails": {
            "builder": {"id": identity["source"].rsplit("/", 2)[0] + "/"
                               + context["GITHUB_WORKFLOW_REF"]},
            "metadata": {"invocationId": identity["source"] + "/actions/runs/"
                          + context["GITHUB_RUN_ID"] + "/attempts/" + context["GITHUB_RUN_ATTEMPT"]},
        },
    }


def provenance_for_identity(identity, kind):
    """Reconstruct every signed claim from the identity that publication validated."""
    image_parts(identity["image"])
    output_name(identity["output"])
    context = identity["workflow"]
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not isinstance(context.get(name), str) or not context[name].isdigit():
            raise EvidenceError("Identity must include its original " + name)
    for name in ("GITHUB_WORKFLOW_REF", "GITHUB_SHA"):
        if not isinstance(context.get(name), str) or not context[name]:
            raise EvidenceError("Identity must include " + name)
    if kind == "architecture":
        if identity["system"] not in SYSTEMS:
            raise EvidenceError("Unsupported architecture identity system")
        derivation = identity["derivation"]
        if not re.fullmatch(r"/nix/store/[0-9a-z]{32}-[^/\n]+\.drv", derivation["path"]) or not re.fullmatch(
                r"[0-9a-f]{64}", derivation["sha256"]):
            raise EvidenceError("Invalid architecture derivation identity")
        dependencies = materials(identity) + [{"uri": "file:" + derivation["path"],
                                              "digest": {"sha256": derivation["sha256"]}}]
        return predicate(identity, "nix-image-v1", dependencies,
                         {"system": identity["system"], "output": identity["output"],
                          "derivation": derivation["path"]})
    if kind != "index":
        raise EvidenceError("Unsupported provenance kind")
    children = identity["children"]
    if [child["system"] for child in children] != sorted(SYSTEMS):
        raise EvidenceError("Index identity must include both architecture children in order")
    dependencies = materials(identity) + [
        {"name": child["system"], "uri": "oci://" + child["image"],
         "digest": {"sha256": image_parts(child["image"])[1]}} for child in children]
    return predicate(identity, "oci-index-v1", dependencies,
                     {"output": identity["output"], "platforms": sorted(SYSTEMS)})


def verify_attestations(identity, image, kind, contents):
    """Check Cosign's verified DSSE output against the validated identity, never a local predicate."""
    repository, sha256 = image_parts(image)
    if identity["image"] != image:
        raise EvidenceError("Expected identity belongs to a different immutable image")
    expected = provenance_for_identity(identity, kind)
    # Cosign versions emit a JSON array or one JSON envelope per line.
    decoder = json.JSONDecoder()
    envelopes = []
    remaining = contents.strip()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        envelopes.extend(value if isinstance(value, list) else [value])
        remaining = remaining[end:].lstrip()
    for envelope in envelopes:
        if not isinstance(envelope, dict) or envelope.get("payloadType") != "application/vnd.in-toto+json":
            continue
        try:
            statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
        except (KeyError, TypeError, ValueError, binascii.Error):
            continue
        if not isinstance(statement, dict):
            continue
        if (statement.get("_type") in ("https://in-toto.io/Statement/v0.1", "https://in-toto.io/Statement/v1")
                and statement.get("subject") == [{"name": repository, "digest": {"sha256": sha256}}]
                and statement.get("predicateType") == "https://slsa.dev/provenance/v1"
                and statement.get("predicate") == expected):
            return
    raise EvidenceError("No verified SLSA statement matches the expected image identity")


def save_identity(path, identity):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EvidenceError("Expected identity output must not be a symlink")
    path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    return path


def write_evidence(root, destination, identity, provenance):
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise EvidenceError("Evidence destination must be outside the source tree")
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (("identity.json", identity), ("provenance.json", provenance)):
        path = destination / name
        if path.is_symlink():
            raise EvidenceError(f"Evidence output must not be a symlink: {path}")
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def architecture(root, args):
    image_parts(args.image)
    output_name(args.output)
    identity = {**checkout_identity(root), "image": args.image, "system": args.system,
                "output": args.output, "workflow": invocation()}
    drv = run(root, "nix", "--extra-experimental-features", "nix-command flakes", "eval",
              "--system", args.system, "--raw", '.#"' + args.output + '".drvPath')
    if not re.fullmatch(r"/nix/store/[0-9a-z]{32}-[^/\n]+\.drv", drv):
        raise EvidenceError("Nix did not return an image derivation path")
    identity["derivation"] = {"path": drv, "sha256": digest(Path(drv))}
    write_evidence(root, args.destination, identity, provenance_for_identity(identity, "architecture"))


def validate_children(root, directory, output):
    output_name(output)
    files = sorted(directory.rglob("identity.json"))
    children = [json.loads(path.read_text()) for path in files]
    children = [child for child in children if child.get("output") == output]
    if len(children) != 2:
        raise EvidenceError("Expected exactly two architecture identity.json artifacts for " + output)
    current = checkout_identity(root)
    systems = set()
    repositories = set()
    for child in children:
        if child.get("system") not in SYSTEMS or child["system"] in systems:
            raise EvidenceError("Expected one aarch64-linux and one x86_64-linux image")
        systems.add(child["system"])
        repositories.add(image_parts(child.get("image", ""))[0])
        if child.get("output") != output:
            raise EvidenceError("Architecture image belongs to a different Nix output")
        for key, value in current.items():
            if child.get(key) != value:
                raise EvidenceError(f"Architecture evidence does not match current {key}")
        workflow = child.get("workflow", {})
        current_workflow = invocation()
        # Successful jobs from an earlier attempt remain usable when failed jobs are retried.
        for key in ("GITHUB_RUN_ID", "GITHUB_WORKFLOW_REF", "GITHUB_SHA"):
            if workflow.get(key) != current_workflow[key]:
                raise EvidenceError(f"Architecture evidence belongs to a different {key}")
    if len(repositories) != 1:
        raise EvidenceError("Architecture images must use the same repository")
    if len({child["image"] for child in children}) != 2:
        raise EvidenceError("Architecture images must have distinct digests")
    return sorted(children, key=lambda child: child["system"])


def index(root, args):
    repository, _ = image_parts(args.image)
    children = validate_children(root, args.children, args.output)
    if image_parts(children[0]["image"])[0] != repository:
        raise EvidenceError("Index and architecture images must use the same repository")
    identity = {**checkout_identity(root), "image": args.image, "output": args.output,
                "children": [{"system": child["system"], "image": child["image"]} for child in children],
                "workflow": invocation()}
    write_evidence(root, args.destination, identity, provenance_for_identity(identity, "index"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare-source")
    arch = commands.add_parser("architecture")
    arch.add_argument("--system", choices=sorted(SYSTEMS), required=True)
    idx = commands.add_parser("index")
    validate = commands.add_parser("validate-children")
    validate.add_argument("--identity-directory", type=Path)
    verify = commands.add_parser("verify-attestation")
    verify.add_argument("--identity", type=Path, required=True)
    verify.add_argument("--image", required=True)
    verify.add_argument("--kind", choices=("architecture", "index"), required=True)
    verify.add_argument("--attestations", type=Path, required=True)
    for subcommand in (arch, idx, validate):
        subcommand.add_argument("--output", required=True)
    for subcommand in (arch, idx):
        subcommand.add_argument("--image", required=True)
        subcommand.add_argument("--destination", type=Path, required=True)
    for subcommand in (idx, validate):
        subcommand.add_argument("--children", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "prepare-source":
            prepare_source(root)
        elif args.command == "architecture":
            architecture(root, args)
        elif args.command == "index":
            index(root, args)
        elif args.command == "verify-attestation":
            verify_attestations(json.loads(args.identity.read_text()), args.image, args.kind,
                                args.attestations.read_text())
        else:
            for child in validate_children(root, args.children, args.output):
                if args.identity_directory is not None:
                    save_identity(args.identity_directory / (child["image"].split("@")[1] + ".json"), child)
                print(child["image"])
    except (EvidenceError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"image-evidence: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
