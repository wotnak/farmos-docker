# Image signatures and provenance

The GitHub publishing workflows sign each architecture image and its multi-platform index by immutable digest. Each architecture image also has a signed SLSA v1 provenance attestation. The index has its own provenance attestation identifying both architecture images.

This applies to production, development, runtime, development runtime, and `4.x-dev` images published by GitHub Actions. Local `task push` targets only copy images to a registry; they do not generate or sign this evidence.

## What is published

| Subject | Evidence |
| --- | --- |
| Each amd64 or arm64 image digest | Cosign signature and SLSA v1 provenance attestation |
| Multi-platform index digest | Cosign signature and SLSA v1 provenance attestation referencing both child digests |
| GitHub Actions artifacts | Image identities, predicates, Sigstore bundles, and verification results |

Cosign 3.1.3 signs the images and publishes the attestations using GitHub's OIDC identity. No signing key secret is required. The installer and version are pinned in [setup-image-evidence](../.github/actions/setup-image-evidence/action.yaml).

## Publication sequence

1. Record the actual checkout URL and SHA, then build and smoke-test the image.
2. Push an architecture candidate with OCI media types and capture its registry digest.
3. Record provenance, sign the image digest, attach the signed provenance predicate, and verify the evidence.
4. Download both architecture artifacts, check their source, build inputs, output, and workflow run, and verify their registry signatures and attestations.
5. Assemble an index from those exact child digests, then sign and attest the index.
6. Verify the complete requested image set against the current source, build inputs, workflow run, architecture digests, signatures, and provenance. Confirm the default branch still points to the tested source revision, then move public tags to the signed index digests.

A signing, attestation, or evidence verification failure blocks tag promotion. Hourly builds wait for every tracked major and `4.x-dev` to pass before changing any public tag. Registry tag writes are not atomic across variants. Build inputs remain CI artifacts and are never committed back to the source branch.

The workflows require `packages: write` to publish and `id-token: write` to obtain the signing identity, including on reusable-workflow caller jobs.

## Verify an image

Install Cosign 3.1.3 or a compatible version, Docker Buildx, and jq. Authenticate to GHCR if the repository is private. Set the repository, expected publishing branch, and a full index digest from your deployment or the workflow's `promotion.json` report:

```sh
REPOSITORY=ghcr.io/wotnak/farmos
INDEX="$REPOSITORY@sha256:REPLACE_WITH_64_HEX_DIGEST"
IDENTITY=https://github.com/OWNER/REPO/.github/workflows/release-images.yaml@refs/heads/BRANCH
ISSUER=https://token.actions.githubusercontent.com

cosign verify "$INDEX" \
  --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER"
cosign verify-attestation "$INDEX" --type slsaprovenance1 \
  --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER" \
  > index-provenance.verified.json
```

Use the actual lowercase GHCR repository path. In `IDENTITY`, use the GitHub owner and repository spelling and branch that you trust. For `4.x-dev`, replace `release-images.yaml` with `branch-image.yaml`. Keep the exact workflow identity and issuer checks; accepting any GitHub workflow does not identify this publisher. See [Cosign signature verification](https://docs.sigstore.dev/cosign/verifying/verify/).

Select a child from the verified index, then verify its signature and provenance. This example selects arm64; use `amd64` for the other platform:

```sh
CHILD_DIGEST=$(docker buildx imagetools inspect --raw "$INDEX" |
  jq -er '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "arm64") | .digest')
CHILD="$REPOSITORY@$CHILD_DIGEST"

cosign verify "$CHILD" \
  --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER"
cosign verify-attestation "$CHILD" --type slsaprovenance1 \
  --certificate-identity "$IDENTITY" --certificate-oidc-issuer "$ISSUER" \
  > image-provenance.verified.json
```

These commands verify signatures and bind the statements to the requested digest. Inspect the verified provenance for the expected source revision, resolved dependencies, platform, and build type before applying your deployment policy. Cosign's verified attestation output contains the signed statement payload; decoding an unverified payload alone does not verify it. See [Cosign attestation verification](https://docs.sigstore.dev/cosign/verifying/attestation/).

## Source labels and refreshed dependencies

Architecture image configs include `org.opencontainers.image.title`, `description`, `licenses`, and `version`. CI also sets `source` to this build repository and `revision` to its actual checked-out commit. The index carries source and revision annotations. The farmOS version label remains separate from the build repository revision.

Each publication resolves fresh dependencies once, then shares those inputs across all variants and architectures. Provenance records the actual checkout SHA, SHA-256 hashes of the generated Nix lock, release metadata and Composer snapshots, the release policy, source metadata, and the GitHub invocation context. Rebuilding the same checkout can select newer dependencies.

Download the run's `build-inputs` artifact for its generated `flake.lock`, resolved versions, hashes, and Composer snapshots. Standalone runs use `build-inputs-release-MAJOR` or `build-inputs-branch`. Build-input artifacts are retained for 7 days. Image and index evidence artifacts are retained for 14 days. Registry signatures and attestations remain attached to their digests subject to registry retention and deletion policies.

Local builds read [images/source.json](../images/source.json), which defaults to `{}`. To label a local build, supply its source identity before building:

```json
{
  "source": "https://github.com/OWNER/REPO",
  "revision": "FULL_CHECKOUT_COMMIT_SHA"
}
```

Local Task builds copy `images/source.json` into the filtered source snapshot;
staging is unnecessary. Supply an explicit revision for local path-flake builds,
which have no Git revision metadata. After changing the metadata for an already
prepared build, run `python3 scripts/nix_source.py` to refresh the snapshot.
CI stages the metadata only in its disposable checkout. With the default empty
file, the source label retains the upstream farmOS URL and the revision label is
omitted. Metadata changes are explicit build inputs; image evaluation does not
read CI environment variables or add timestamps. Labels alone do not create
signatures or provenance attestations.

## Provenance build types

The predicates follow the [SLSA v1 provenance schema](https://slsa.dev/spec/v1.0/provenance), published with Cosign's `slsaprovenance1` type. This repository makes no SLSA build-level claim. The build type URLs point to the following definitions at the exact source revision that generated them.

### nix-image-v1

Build one OCI architecture image using the selected Nix flake output and Linux system. `externalParameters` identifies the source URL, checkout revision, Nix system, output name, and image derivation path. `resolvedDependencies` contains the checkout Git commit, SHA-256 hashes of resolved build-input files and `images/source.json`, and the image derivation file's SHA-256 hash.

`internalParameters` records `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, `GITHUB_WORKFLOW_REF`, and `GITHUB_SHA`. `runDetails` identifies the workflow and links to its run attempt. The in-toto statement's subject is the pushed image digest. The separate artifact `identity.json` retains the same build identity for promotion checks.

### oci-index-v1

Assemble a multi-platform OCI index from the verified `aarch64-linux` and `x86_64-linux` architecture digests for one Nix output. `externalParameters` identifies the source, revision, output, and platforms. `resolvedDependencies` contains the source and pin materials above plus both immutable child image references and their SHA-256 digests. The statement's subject is the resulting index digest.

The index does not rebuild either image. Its provenance links to each child's build provenance through that child's digest. Successful architecture artifacts from an earlier attempt of the same workflow run can be reused when failed jobs are retried, provided their source, build inputs, output, and workflow identities still match and their signatures and provenance verify.
