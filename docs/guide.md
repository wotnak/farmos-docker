# farmOS image guide

This repository builds farmOS OCI images with Nix and nix2container. Images run as UID and GID 65532 and serve farmOS on port 8080 with FrankenPHP in classic mode.

The production PHP 8.4 runtime enables ZTS and the embed SAPI; CGI, FPM, phpdbg, PEAR, systemd, and Valgrind support are disabled. In production and codebase-free runtime images, `/usr/bin/php` invokes `frankenphp php-cli`. Development images put a native PHP CLI at `/usr/bin/php`, with those unused SAPIs and integrations also disabled. PHPUnit needs a populated `PHP_BINARY` for isolated test processes, and Composer scripts can require PHP CLI flags such as `-d`. Use `frankenphp php-cli` to run the embedded PHP CLI directly.

All variants currently include BusyBox and `/bin/sh` for startup, the PHP wrapper, and the Compose cron service. Drush's standard launcher also requires a shell. Production has no `bash` command on `PATH`, but Nix runtime dependencies still include a Bash executable in `/nix/store`; these are not shell-free images.

GD retains its image formats, including AVIF. The AVIF desktop thumbnailer and command-line tools are excluded from the runtime dependency closure.

The farmOS runtime disables `fastcgi_finish_request` so Drupal finishes deferred route rebuilds before sending a response. This prevents a following request from missing newly created quick forms, at the cost of waiting for request termination work.

## Image variants and tags

For the latest stable release within major 4, the build publishes:

| Variant | Contents | Tags |
| --- | --- | --- |
| Production | farmOS and its runtime closure | `4` |
| Development | Composer, Xdebug, Git, PostgreSQL client, and farmOS test tools | `4-dev` |
| Runtime | Production PHP and FrankenPHP; bring your own installed codebase | `4-runtime` |
| Development runtime | Development PHP, Composer, Git, Xdebug, and PostgreSQL client; bring your own codebase and test tools | `4-dev-runtime` |

Each supported major builds its latest stable minor and patch release. Minor and
patch tags are not published. Every build resolves fresh compatible Composer
dependencies and refreshes the Nix inputs. The exact farmOS version is recorded
in the generated build metadata and `org.opencontainers.image.version` label.
Pin an image digest for a fixed deployment or rollback.

The latest upstream 4.x checkout produces only `4.x-dev`. There is no production `4.x` image.

## Prerequisites

- Nix with flakes enabled
- A Linux builder for `aarch64-linux` or `x86_64-linux`
- Docker for loading, testing, and running images
- [Task](https://taskfile.dev/docs/installation) v3

Apple Silicon macOS can use a remote Linux builder. Set `NIX_SYSTEM=aarch64-linux`. Intel macOS is not exposed by some nixpkgs revisions, but it can still submit either Linux system to a remote builder.

Enter the development shell with:

```sh
nix develop
```

## Build and test

```sh
task release-images       # all four variants for the newest line
task images               # selected major plus 4.x-dev
task test                 # production runtime and HTTP checks
task dev-test             # release development tools and Xdebug
task runtime-test         # PHP runtime and mounted projects
task dev-runtime-test     # development runtime, Git, and Composer with a supplied project
task database-test        # PostgreSQL, SQLite, and environment-driven settings
task branch-dev-test      # latest 4.x checkout
task e2e-test             # browser installation, core farmOS workflows, persistence, cron
task contrib-test         # all seven contributed modules, including Crop/Grazing Plan
task contrib-ci-test      # contrib CI examples using the development image
task phpunit-test         # upstream farmOS tests in the release development image
task branch-phpunit-test  # upstream farmOS tests in the latest 4.x development image
task tests                # all image and application checks above
task regression-test      # build and publishing logic, without image builds
python3 tests/test-docker-setup.py  # HTTP protections and cron configuration
```

Override the Linux target when needed:

```sh
task images NIX_SYSTEM=x86_64-linux
task images NIX_SYSTEM=aarch64-linux
```

Local Task commands default to major 4. Select a major explicitly, for example `task release-images load RELEASE_MAJOR=4`. Each invocation prepares fresh dependencies once and shares them across its build targets.

Run `task --list` to see available commands. Task is included in `nix develop`.

### Contributed module CI

Use the existing `-dev` image to run a contributed module's Composer, PHPCS,
PHPStan, and PHPUnit commands. The [contrib CI guide](../examples/contrib-ci/README.md)
includes a local Compose setup, a [GitHub Actions workflow](../examples/contrib-ci/.github/workflows/farmos.yml),
and a [Drupal.org GitLab job](../examples/contrib-ci/.gitlab-ci.yml).
The examples detect the module name and default to `ghcr.io/wotnak/farmos:4-dev`.
Adapt dependencies and tool configurations where the module needs them.

### Docker Nix build cache

When using `farmos-nix-build-cache` as `/nix` in a Linux builder container, old
toolchains, source trees, Composer vendors, and image outputs accumulate there.
This is separate from Docker image storage and farmOS application data.

Run `task cache-info` to inspect it, or `task cache-prune` when builds have stopped.
Pruning first retains the current four release variants, `4.x-dev` and their
Docker loaders, then removes unreferenced Nix paths and deduplicates identical
files. It keeps the builder's
registered roots and does not touch database, upload, or Docker image storage.
Changing sources after pruning can require downloading or rebuilding build tools.
Use `NIX_CACHE_VOLUME` to select a different existing build-cache volume. These
tasks do not prune a native host Nix installation.

### Application acceptance tests

The two application suites use separate, disposable Compose projects. They test the farmOS code packaged in the images and require Docker Compose. The runners collect reports and container logs, then remove their own containers, networks, and volumes. They do not use the deployment's `.env` file or volumes.

To test images already loaded into Docker without invoking Nix:

```sh
IMAGE=ghcr.io/wotnak/farmos:4 bash tests/e2e/scripts/test.sh
IMAGE=ghcr.io/wotnak/farmos:4-dev bash tests/phpunit-test.sh
IMAGE=ghcr.io/wotnak/farmos:4.x-dev TEST_ARTIFACTS=build/tests/phpunit-4x bash tests/phpunit-test.sh
```

The equivalent Task commands are `task e2e-test-loaded IMAGE=ghcr.io/wotnak/farmos:4` and `task phpunit-test-loaded IMAGE=ghcr.io/wotnak/farmos:4-dev`. These skip image builds and loading.

The Playwright suite installs farmOS through the browser and tests standard assets, logs, quantities, inventory, quick forms, farms, imports/exports, attachments, comments, revision history, roles, JSON:API and OAuth. It checks records, uploaded files and OAuth signing keys after recreating the application and database containers, then verifies Drush cron. The production application runs read-only with only public-file and private-data volumes writable. Playwright uses the stock Microsoft image with the test project mounted read-only and dependencies installed into a disposable Compose volume. See the [coverage matrix](../tests/e2e/COVERAGE.md) for scenarios and limits, and the [contrib coverage](../tests/e2e/CONTRIB-TEST-PLAN.md) for the seven-module suite.

Run `task contrib-test-loaded` with the runtime and development runtime images already loaded. This tests Calendar, Ledger, Eggs, Beekeeping, Fungi, Crop Plan and Grazing Plan against a separately resolved Composer project. Both planning modules participate in the default suite. `CONTRIB_MODULES=crop_plan,grazing_plan` selects a subset. The contrib project is served read-only by the production runtime; Composer runs only during preparation in the development runtime. Findings and reproduction steps are kept in [the contrib issues file](../tests/e2e/CONTRIB-ISSUES.md). `task tests` includes this suite. A dedicated CI workflow runs all seven modules on relevant pull requests and manual dispatches.

The [candidate research](../tests/e2e/CONTRIB-CANDIDATES.md) ranks further modules
and their compatibility checks. The [user journey plan](../tests/e2e/USER-JOURNEY-TEST-PLAN.md)
describes market-garden, grazing, poultry, apiary and fungi workflows across
modules and user roles. These documents propose future E2E work; they do not
add dependencies to the current fixture.

The browser suite is a self-contained project in [`tests/e2e/`](../tests/e2e/README.md), with its own dependencies and configuration. It accepts a target URL and credentials for a disposable farmOS test deployment outside this repository. Its Compose files, shell runners and contrib manifest also live in that directory, so it can be extracted to a separate repository. The shell runner owns Compose startup, container recreation, and cron; the browser tests contain no Docker orchestration. Feature specs live under `tests/e2e/tests/features/`, with reusable HTTP/browser helpers under `tests/e2e/support/`.

The PHPUnit suite runs the upstream tests under `web/profiles/farm` in the matching development image, with PostgreSQL, a browser service, and Xdebug disabled. It uses a separate database from the Playwright suite. Extra PHPUnit arguments can select tests while debugging:

```sh
IMAGE=ghcr.io/wotnak/farmos:4-dev bash tests/phpunit-test.sh --filter Asset
```

Reports go into a new run directory under `build/tests/e2e/`, `build/tests/contrib/` or `build/tests/phpunit/`. Set `TEST_ARTIFACTS` to choose another parent directory. CI runs core E2E and PHPUnit on native AMD64 and ARM64 runners and requires them to pass before publishing image candidates. The contrib workflow runs separately on AMD64 for pull requests and manual dispatches. All retain failure artifacts. The existing release-selection, dependency-update and publishing regression tests remain separate from application acceptance.

The flake also exposes the underlying outputs:

| Output | Purpose |
| --- | --- |
| `farmos` | Production nix2container image for the newest tracked major |
| `farmos-dev` | Release development image |
| `farmos-runtime` | Runtime image without an application codebase |
| `farmos-dev-runtime` | Development runtime without an application codebase |
| `farmos-4`, `farmos-4-dev`, `farmos-4-runtime`, `farmos-4-dev-runtime` | Images for the latest stable release in a tracked major |
| `farmos-4-app`, `farmos-4-dev-app` | Production and development application trees for that major |
| `farmos-4x-dev` | 4.x checkout development image |
| `frankenphp-drupal` | FrankenPHP with the generic Drupal runtime |
| `php-drupal` | Native PHP CLI with the generic Drupal runtime |
| `skopeo-nix2container` | Host-native tool for copying Nix images into Docker or a registry |

Build targets create symlinks such as `build/farmos-4` to image descriptions in the
Nix store. They do not export tar files. `task load` copies the production image
directly into Docker with its major tag. `task load-dev`, `task load-runtime`,
and `task load-dev-runtime` load the other variants.

To export a portable tar file when needed:

```sh
task load RELEASE_MAJOR=4
docker save --output farmos-4.tar ghcr.io/wotnak/farmos:4
```

Images default to `ghcr.io/wotnak/farmos`. Override `IMAGE_REPOSITORY` to publish
to another repository:

```sh
task push IMAGE_REPOSITORY=registry.example.com/team/farmos
task push-branch-dev IMAGE_REPOSITORY=registry.example.com/team/farmos
```

The workflows under `.github/workflows/` build and test both Linux architectures, push architecture-specific temporary tags, and create multi-platform major tags in `ghcr.io/wotnak/farmos`. The `IMAGE_REPOSITORY` GitHub repository variable overrides this destination without changing the source repository or signing identity. They sign architecture images and indexes with Cosign and publish SLSA v1 provenance before promoting public tags. See [image provenance and verification](image-provenance.md) for verification commands and source metadata. Local `task push` targets publish unsigned images. The release and 4.x workflows can also be run manually. A manual release run requires a `release-major` such as `4`.

Publishing requires the tested source revision to remain the default branch's current revision. If it advances during a build, rerun from the latest revision; an older queued run cannot publish its moving tags.

`hourly-images.yaml` runs at minute 17 of every hour in UTC, or manually on the
default branch. Each run selects the latest stable farmOS release in each tracked
major, checks current 4.x commits, runs `nix flake update`, and refreshes each
major's Composer snapshot plus the 4.x snapshot. Root `versions.json` sets
`minimum_major` to 4, so discovery includes future stable major versions.
When 4.1 becomes available, it replaces 4.0 as major 4's release; subsequent
4.0 patches do not create additional builds. Dependencies refresh even when
upstream releases and commits have not changed. The workflow builds all four
stable variants for each major, plus `4.x-dev`, and moves public tags only after
the complete set passes tests and signature/provenance verification.

Build inputs are generated for each run and shared through a CI artifact. They
are never committed back to the source branch. GitHub Actions needs
`packages: write` to publish images and `id-token: write` for keyless signing.

## Run farmOS

Deployment examples live under `examples/`, each with its own configuration and instructions:

- [PostgreSQL](../examples/prod/README.md) runs the published farmOS image.
- [SQLite](../examples/prod-sqlite/README.md) keeps the database in the private-files volume.
- [Contributed modules](../examples/prod-contrib/README.md) builds a custom image with additional modules and fresh compatible dependencies.

Copy an example directory to your server. Nix and the build tools are not required.
The PostgreSQL and SQLite examples configure HTTP, automatic HTTPS, and cron through
one Compose file and `.env`. See [database configuration](database.md) for the
shared environment variables.

To try a locally built image from this repository, prepare the production example:

```sh
cp examples/prod/.env.example examples/prod/.env
# Set FARMOS_DB_PASS in examples/prod/.env.
chmod 600 examples/prod/.env
task run
```

`task run` builds and loads the selected major's release, then starts `examples/prod` with
that image. For public HTTPS, set `FARMOS_DOMAIN` in the example's `.env`, point
DNS at the server, allow TCP ports 80 and 443, and run `task run-https`.
This enables automatic certificates and publishes those ports on all host interfaces.

Drupal cron uses the image's `farmos-cron` command in a separate container.
`FARMOS_CRON_INTERVAL` defaults to 900 seconds. Public uploads and private data,
including the generated hash salt and certificates, persist in volumes.
See the chosen example for storage, networking, proxy settings, and backups.

Docker setup tests use their own disposable web-only configuration at
[`tests/compose.docker-setup.yaml`](../tests/compose.docker-setup.yaml).
They also render the deployment examples to check their configuration.
Other test suites keep their Compose fixtures under `tests/`.

Development images include Git with HTTPS support and PCRE matching. Optional
Python and Perl integrations and bundled manuals are omitted. PostgreSQL client
tools include `psql`, `pg_dump`, and `pg_restore`; the database server is excluded.

## Run your own Composer project

The `-runtime` image contains the production PHP 8.4 runtime with GEOS and FrankenPHP. Its `php` command uses FrankenPHP's CLI. The `-dev-runtime` image adds native PHP CLI, Composer, Git, PostgreSQL tools, and Xdebug. Both images contain no farmOS, Drupal, or application dependencies; install your own test tools in your project's Composer dependencies. The version in each tag follows this repository's release; your project's Composer lock file determines the application version.

Build and load it with:

```sh
task runtime-image
task load-runtime
```

Use a Composer project with `composer.json` and `composer.lock` at its root and the standard `web/` document root. First load the development runtime with `task load-dev-runtime` from this repository. Then install dependencies from your project directory:

```sh
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp --env COMPOSER_HOME=/tmp/composer --env XDEBUG_MODE=off \
  --mount type=bind,src="$PWD",dst=/opt/farmos \
  ghcr.io/wotnak/farmos:4-dev-runtime composer install --no-dev --optimize-autoloader
```

The default command serves `/opt/farmos/web` on port 8080 and requires `web/index.php` and `vendor/autoload.php`. Passing another command runs it in `/opt/farmos`. The entrypoint does not initialize the project, change its permissions, or replace its settings.

For an existing site, use the standalone [runtime Compose example](../examples/runtime/README.md).
It mounts your installed project read-only, with separate writable file storage.
Your project supplies its own Drupal settings; the runtime preserves them.
You can use the built-in settings template described in [database configuration](database.md).

You can also bake your installed project into a derived image. After installing its Composer dependencies, put this Dockerfile at the project root:

```dockerfile
FROM ghcr.io/wotnak/farmos:4-runtime
COPY --chown=65532:65532 . /opt/farmos
```

Exclude credentials, local files, and Git metadata from the build context with `.dockerignore`. Keep uploaded files and OAuth keys on persistent writable mounts when running the resulting image.

## Fresh build dependencies

Root [`versions.json`](../versions.json) contains only the minimum supported
stable major and upstream development branch. Each build selects the newest
stable release within each supported major, including new minor and patch
releases. It also resolves the current development branch commits.

Task build commands run `scripts/prepare-build` once per invocation. Preparation
refreshes nixpkgs and nix2container, resolves compatible Composer dependencies,
and generates `.build-inputs/versions.json`, Composer manifests and lock files,
and the Nix application output hashes. The generated root `flake.lock` and
`.build-inputs/` are ignored by Git. Preparation leaves the Git index unchanged.
It copies the flake, generated inputs, and required application source files to
`build/nix-source/`. Local Task commands use this filtered path flake so Nix can
read the inputs without staging them. Credentials, Git metadata, and test reports
are excluded from the snapshot.

To prepare inputs explicitly before using raw Nix commands:

```sh
scripts/prepare-build --major 4
nix build 'path:./build/nix-source#farmos-4'
```

Use `scripts/prepare-build --branch-only` for `4.x-dev`, or omit the selector to
prepare all supported stable majors and the development branch. Raw Nix commands
consume the current generated snapshot. Run preparation again to refresh it.
After editing build code or `images/source.json`, run `python3 scripts/nix_source.py`
to refresh the source snapshot without resolving dependencies again. Plain
`nix build .#farmos-4` uses Git's source filter and cannot read ignored inputs.
CI explicitly stages shared generated inputs only in its disposable checkouts.

Production and development install the same freshly generated Composer lock.
Production excludes development packages; development includes the test tools.
The branch source is retained as a local Composer path repository so later
Composer operations inside the development image can use it.

Nix still verifies download and application hashes. These hashes are generated
for the current build, rather than maintained as repository pins. CI resolves
inputs once and distributes them to all variants and architectures. A new build
of the same source commit may use newer dependencies and produce a different
image. Use a published image digest to keep or restore a particular deployment.

## File map

`farmos-runtime` extends `drupal-runtime` with farmOS-specific PHP extensions and settings. The `farmos` package builds the application separately. `images/` combines the farmOS runtime with that application for bundled images, or uses the runtime alone for the codebase-free image. The generic Drupal runtime defaults to `/opt/drupal`; farmOS images use `/opt/farmos`.

- `flake.nix` declares nixpkgs and nix2container and exposes Linux image outputs plus development shells.
- `Taskfile.yml` provides build, load, test, and publishing commands.
- `packages/drupal-runtime/` builds FrankenPHP, PHP CLI, and Composer with common Drupal extensions, Caddy protections, and generic container scripts.
- `packages/farmos-runtime/` extends the Drupal runtime with bcmath, exif, GEOS, and farmOS PHP settings.
- `packages/farmos/` builds the release and development application trees.
- `images/default.nix` assembles OCI images; `images/scripts/` contains the bundled application initializers.
- `images/source.json` supplies optional build repository labels; CI records the actual checkout URL and revision here.
- `versions.json` contains the minimum supported major and development branch policy.
- `.build-inputs/` contains generated release metadata, application hashes, and Composer snapshots for the current build.
- `tests/` contains image smoke tests, Compose application acceptance suites, and build and publishing regression checks.
- `scripts/prepare-build` resolves fresh release, Nix, and Composer dependencies.
- `scripts/nix_source.py` copies the required build source and generated inputs into an ignored path flake without changing Git's index.
- `scripts/discover_upstream.py` finds the latest stable GitHub release in each tracked major and current 4.x commits without changing generated inputs.
- `scripts/releases.py` reads generated release metadata and selects major tags.
- `scripts/image_evidence.py`, `scripts/attest-image`, and `scripts/publish-index` record build inputs and sign immutable candidates. `scripts/promote-images` verifies the complete signature and provenance evidence before moving public tags.
- `docs/image-provenance.md` describes published signatures, provenance, and verification.
- `.github/workflows/hourly-images.yaml` prepares shared inputs, invokes both image workflows, and promotes tested images.
- `examples/` contains standalone deployment configurations.
- `tests/` contains disposable test configurations and image/application tests.
