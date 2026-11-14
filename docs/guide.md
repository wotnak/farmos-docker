# farmOS image guide

This repository builds farmOS OCI images with Nix and nix2container. Images run as UID and GID 65532 and serve farmOS on port 8080 with FrankenPHP in classic mode.

The production PHP 8.4 runtime enables ZTS and the embed SAPI; CGI, FPM, phpdbg, PEAR, systemd, and Valgrind support are disabled. In production and codebase-free runtime images, `/usr/bin/php` invokes `frankenphp php-cli`. Development images put a native PHP CLI at `/usr/bin/php`, with those unused SAPIs and integrations also disabled. PHPUnit needs a populated `PHP_BINARY` for isolated test processes, and Composer scripts can require PHP CLI flags such as `-d`. Use `frankenphp php-cli` to run the embedded PHP CLI directly.

All variants currently include BusyBox and `/bin/sh` for startup, the PHP wrapper, and the Compose cron service. Drush's standard launcher also requires a shell. Production has no `bash` command on `PATH`, but Nix runtime dependencies still include a Bash executable in `/nix/store`; these are not shell-free images.

GD retains its image formats, including AVIF. The AVIF desktop thumbnailer and command-line tools are excluded from the runtime dependency closure.

The farmOS runtime disables `fastcgi_finish_request` so Drupal finishes deferred route rebuilds before sending a response. This prevents a following request from missing newly created quick forms, at the cost of waiting for request termination work.

## Image variants and tags

Each build profile selects one Composer constraint and a container base tag.
All four variants are available for that constraint; `FARMOS_IMAGE_VARIANTS`
controls which ones are built.

| Variant | Tag for base `4` | Contents |
| --- | --- | --- |
| `production` | `4` | farmOS and the production PHP runtime |
| `development` | `4-dev` | farmOS, Composer, Xdebug, Git, PostgreSQL client, and test tools |
| `runtime` | `4-runtime` | Production PHP and FrankenPHP; supply your own installed codebase |
| `development-runtime` | `4-dev-runtime` | Development PHP and tools; supply your own codebase and test dependencies |

`FARMOS_VERSION` and the image tag are separate settings. For example, constraint
`^4.0` and base tag `4` select a compatible farmOS release and publish the tags
above. Constraint `4.x-dev`, base tag `4.x`, and variant `development` publish
only `4.x-dev`. A feature branch can use base tag `myfeature` to publish
`myfeature-dev`.

Every preparation resolves fresh compatible Composer dependencies and refreshes
Nix inputs. The lock file records the exact farmOS version and source commit.
Pin an image digest for a fixed deployment or rollback.

## Shared build configuration

The same settings apply to local builds and GitHub Environments:

| Variable | Required/default | Meaning |
| --- | --- | --- |
| `FARMOS_VERSION` | Required | Composer constraint for `farmos/farmos`. |
| `FARMOS_IMAGE_TAG` | Required | Container base tag before variant suffixes. |
| `FARMOS_IMAGE_NAME` | `ghcr.io/wotnak/farmos` | Container repository, including its registry and namespace when needed. |
| `FARMOS_REPOSITORY` | Standard repositories | Unset or empty uses the normal Composer repositories; a custom repository JSON object is prepended when supplied. |
| `FARMOS_IMAGE_VARIANTS` | All four | Unset or empty builds every variant; otherwise use comma-separated `production`, `development`, `runtime`, `development-runtime`. |

For local builds, copy the root example and edit the required settings:

```sh
cp .env.example .env
```

Task loads the root `.env` with its native dotenv support. Process environment
values take precedence, and unset optional settings use the defaults above.
Python build scripts read process environment variables only; use Task to load
`.env`, or export the settings before invoking a script directly. Keep deployment
settings in the selected example directory's separate `.env`.

Composer interprets `FARMOS_VERSION`, including stable constraints such as
`^4.0` and `~4.0.9`, development constraints such as `4.x-dev` and `dev-feature`,
and constraints supported by your custom repository. The configuration layer
requires a nonempty value and leaves constraint grammar to Composer.

### Build a fork or feature branch

A custom repository is prepended to the standard Composer repositories. Drupal's
repository and Packagist remain available for dependencies. A fork must retain
the Composer package name `farmos/farmos`.

For example, build a fork's `feature` branch as `myfeature-dev`:

```sh
FARMOS_VERSION=dev-feature \
FARMOS_IMAGE_TAG=myfeature \
FARMOS_IMAGE_VARIANTS=development \
FARMOS_REPOSITORY='{"type":"vcs","url":"https://github.com/YOUR-ORG/farmOS"}' \
task images
```

Set the same values as GitHub Environment variables to build that profile in CI.
Use a public repository URL without embedded credentials. `FARMOS_REPOSITORY`
accepts a standard Composer repository object, including `vcs` or `composer`.

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

After configuring `.env`:

```sh
task images          # build the selected variants
task load            # build and load the selected variants into Docker
task tests           # run tests applicable to the selected profile
```

`task image`, `task dev-image`, `task runtime-image`, and `task dev-runtime-image`
select an individual variant from the configured profile. That variant must be
enabled in `FARMOS_IMAGE_VARIANTS`. Build preparation runs once per invocation,
and its Composer lock is shared across selected variants.

Override the Linux system or build profile through environment variables:

```sh
NIX_SYSTEM=x86_64-linux task images
NIX_SYSTEM=aarch64-linux task images
FARMOS_VERSION=4.x-dev FARMOS_IMAGE_TAG=4.x FARMOS_IMAGE_VARIANTS=development task images
```

The production checks cover runtime behavior, HTTP protections, database settings,
installation, core workflows, persistence, and cron. Development checks cover
Composer, Xdebug, contributed-module QA, and upstream PHPUnit. Runtime checks
exercise supplied codebases. The contrib suite uses the runtime and development
runtime variants. Run `task --list` for the individual test commands and their
requirements. Task is included in `nix develop`.

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
Pruning first retains the configured image variants and their Docker loaders,
then removes unreferenced Nix paths and deduplicates identical files. It keeps the builder's
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

The equivalent Task commands are `IMAGE=ghcr.io/wotnak/farmos:4 task e2e-test-loaded` and `IMAGE=ghcr.io/wotnak/farmos:4-dev task phpunit-test-loaded`. These skip image builds and loading.

The Playwright suite installs farmOS through the browser and tests standard assets, logs, quantities, inventory, quick forms, farms, imports/exports, attachments, comments, revision history, roles, JSON:API and OAuth. It checks records, uploaded files and OAuth signing keys after recreating the application and database containers, then verifies Drush cron. The production application runs read-only with only public-file and private-data volumes writable. Playwright uses the stock Microsoft image with the test project mounted read-only and dependencies installed into a disposable Compose volume. See the [coverage matrix](../tests/e2e/COVERAGE.md) for scenarios and limits, and the [contrib coverage](../tests/e2e/CONTRIB-TEST-PLAN.md) for the seven-module suite.

Run `task contrib-test-loaded` with the runtime and development runtime images already loaded. This tests Calendar, Ledger, Eggs, Beekeeping, Fungi, Crop Plan and Grazing Plan against a separately resolved Composer project. Both planning modules participate in the default suite. `CONTRIB_MODULES=crop_plan,grazing_plan` selects a subset. The contrib project is served read-only by the production runtime; Composer runs only during preparation in the development runtime. Findings and reproduction steps are kept in [the contrib issues file](../tests/e2e/CONTRIB-ISSUES.md). `task tests` includes this suite when both runtime variants are selected. A dedicated CI workflow runs all seven modules on relevant pull requests and manual dispatches.

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

Reports go into a new run directory under `build/tests/e2e/`, `build/tests/contrib/` or `build/tests/phpunit/`. Set `TEST_ARTIFACTS` to choose another parent directory. CI runs core E2E for production and PHPUnit for development on native AMD64 and ARM64 runners, requiring the applicable checks before publishing image candidates. The contrib workflow runs separately on AMD64 for pull requests and manual dispatches. All retain failure artifacts.

The flake exposes generic image outputs for the selected variants:

| Variant | Nix output |
| --- | --- |
| `production` | `farmos` |
| `development` | `farmos-dev` |
| `runtime` | `farmos-runtime` |
| `development-runtime` | `farmos-dev-runtime` |

Application-only outputs are used during preparation. Output names do not encode
the Composer constraint or image tag. The generated profile determines which
image outputs are enabled. `skopeo-nix2container` copies built images into Docker
or a registry.

Build outputs are Nix image descriptions, rather than exported tar files. To
save a loaded image as a portable archive, use Docker's image name and configured
tag:

```sh
task load
docker save --output farmos-4.tar ghcr.io/wotnak/farmos:4
```

`task push` builds, loads, and pushes the selected variants to
`FARMOS_IMAGE_NAME`. Authenticate to the destination registry first. To choose a
different destination for one invocation:

```sh
FARMOS_IMAGE_NAME=registry.example.com/team/farmos task push
```

GitHub Actions builds and tests both architectures, pushes the architecture
images, and creates multi-platform manifests for the configured public tags.
Each manifest references the exact image digests produced by that run.

### GitHub build environments

Create named Environments in the GitHub repository's Settings and define the
shared build variables in each environment. For example, leave optional settings
unset except the development environment's variant selection:

| Environment | `FARMOS_VERSION` | `FARMOS_IMAGE_TAG` | `FARMOS_IMAGE_VARIANTS` | Published tags |
| --- | --- | --- | --- | --- |
| `4` | `^4.0` | `4` | unset | `4`, `4-dev`, `4-runtime`, `4-dev-runtime` |
| `dev` | `4.x-dev` | `4.x` | `development` | `4.x-dev` |

Environment names are labels. The variables determine the Composer source,
container repository, base tag, and selected variants. Environments can use the
same constraint with different repositories or tags. Choose the container name
and base tag for each environment's intended images.

Jobs use environments for variables and secrets with `deployment: false`, so
image builds and publishing do not create GitHub deployment records.

`refresh-images.yaml` runs on pushes to `main` and once a day at 06:00 in
`Europe/Warsaw`, following local daylight saving time, on the default branch.
It discovers configured environments and invokes `build-images.yaml` for each
one. The build reads the environment's current variables and resolves the latest
farmOS version allowed by its Composer constraint and repository. Every
environment resolves fresh dependencies and builds independently. A development build failure does
not prevent a valid stable build from publishing.

For a manual build, open the **Build images** workflow and select one environment.
Its variables determine the build. Disable the `publish` option to run the
builds and tests without updating public image tags.

CI and local builds share the Task commands. CI runs `task prepare-inputs`, then
`task load-prepared VARIANT=production` and the loaded-image test tasks for each
selected variant. `CONFIGURATION=path/to/build.json` supplies an explicit profile
to these tasks; matrix jobs use `.build-inputs/build.json` to reuse the resolved
dependencies without preparing them again. Matrix generation and multi-platform
publishing remain workflow-specific commands.

For GHCR, workflows use `GITHUB_TOKEN` by default and need `packages: write`.
For another registry, set `FARMOS_IMAGE_NAME` and the environment secrets
`REGISTRY_USERNAME` and `REGISTRY_PASSWORD`. Repository discovery uses the
workflow's GitHub token; no personal access token is needed.

Temporary architecture images and artifacts use the numeric environment ID to
keep profiles separate even when their names contain spaces or punctuation.
Manual, push-triggered, and scheduled runs use the current environment settings when
preparation starts. When publishing is enabled, CI captures the digests of the
tested architecture images. After all selected variants and both
architectures pass, it creates multi-platform manifests from those digests and
updates that environment's public tags. Pin a published digest to keep a specific
build as tags advance.

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

`task run` builds and loads the configured production variant, then starts
`examples/prod` with that image. Enable `production` in the build profile first. For public HTTPS, set `FARMOS_DOMAIN` in the example's `.env`, point
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

The `-runtime` image contains the production PHP 8.4 runtime with GEOS and FrankenPHP. Its `php` command uses FrankenPHP's CLI. The `-dev-runtime` image adds native PHP CLI, Composer, Git, PostgreSQL tools, and Xdebug. Both images contain no farmOS, Drupal, or application dependencies; install your own test tools in your project's Composer dependencies. Their tags follow the configured build profile; your project's Composer lock file determines the application version.

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

`scripts/prepare-build` reads the shared build settings from its process
environment or an explicit configuration file, refreshes the Nix inputs, and
resolves the `farmos/farmos` requirement through Composer. Preparation
uses the normal project manifest with the requested constraint and optional
repository override. There is no separate stable-release or development-branch
source discovery step.

Composer resolution happens once per build. The generated Composer lock records
the exact package version and source commit, and both production and development
application builds consume that lock. Production excludes development packages;
development includes the test tools.

Generated inputs live in:

- `.build-inputs/build.json`: the five profile settings, resolved package metadata,
  and application output hashes `prodHash` and `devHash`.
- `.build-inputs/composer/composer.json` and `composer.lock`: the resolved project
  manifest and its complete dependency lock.
- `flake.lock`: refreshed Nix dependency revisions.

These files are ignored by Git. Preparation leaves the Git index unchanged and
copies required source files and generated inputs to `build/nix-source/`. The
snapshot excludes local credentials, Git metadata, and test reports. Local Task
commands use this explicit path flake so Nix can read generated inputs without
staging them.

To prepare inputs from the root `.env` before using raw Nix commands:

```sh
task prepare-inputs
nix build 'path:./build/nix-source#farmos'
```

To invoke preparation directly, export the required settings first:

```sh
export FARMOS_VERSION='^4.0'
export FARMOS_IMAGE_TAG=4
scripts/prepare-build
```

For an explicit configuration file, use
`scripts/prepare-build --configuration path/to/configuration.json`. The script
does not read `.env` itself. Raw Nix commands consume the current prepared
snapshot. After editing build code, run
`python3 scripts/nix_source.py` to refresh the snapshot without resolving
dependencies again. Root Git-flake references cannot read
ignored generated inputs. CI uses the same filtered path flake.

Nix verifies download and application hashes generated for the build. CI shares
one resolved snapshot across an environment's selected variants and
architectures. Rebuilding the same source commit can select newer compatible
dependencies, so retain a published image digest for a fixed deployment.

## File map

`farmos-runtime` extends `drupal-runtime` with farmOS-specific PHP extensions and
settings. The `farmos` package builds the application separately. `images/`
combines the runtime and application for bundled images, or provides the runtime
alone for a supplied codebase. Generic Drupal runtime paths use `/opt/drupal`;
farmOS images use `/opt/farmos`.

- `flake.nix` declares Nix inputs, selected image outputs, and development shells.
- `Taskfile.yml` provides profile-based build, load, test, and push commands.
- `packages/drupal-runtime/` builds FrankenPHP, PHP CLI, Composer, Caddy
  protections, and generic container scripts.
- `packages/farmos-runtime/` adds farmOS PHP extensions and settings.
- `packages/farmos/` resolves and builds the Composer application.
- `images/default.nix` assembles OCI images with the configured names and tags.
- `scripts/build_config.py` validates build settings from the process environment.
- `scripts/build_environments.py` discovers configured environments and creates
  variant and platform build matrices.
- `scripts/prepare-build` resolves fresh Nix and Composer dependencies and writes
  the generated build snapshot.
- `scripts/nix_source.py` copies filtered source into a path flake without changing
  Git's index.
- `.github/workflows/refresh-images.yaml` discovers configured environments.
- `.github/workflows/build-images.yaml` builds, tests, and publishes one
  selected environment's images and multi-platform manifests.
- `examples/` contains standalone deployment configurations.
- `tests/` contains image checks and application acceptance suites.
