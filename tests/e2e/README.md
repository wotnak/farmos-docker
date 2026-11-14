# farmOS end-to-end tests

This Playwright project tests farmOS through its browser and HTTP interfaces.
Browser-only commands can target an existing disposable site. Container suites
use the parent repository's Task commands and shared Compose services. Tests
create, modify, and delete farm records and test accounts.

`npm test` runs the core feature suite, including the persistence seed scenario.
See [COVERAGE.md](COVERAGE.md) for the scenario matrix and known limits, and
[CONTRIB-TEST-PLAN.md](CONTRIB-TEST-PLAN.md) for module coverage and deferred additions.
Further research is in [CONTRIB-CANDIDATES.md](CONTRIB-CANDIDATES.md).
[USER-JOURNEY-TEST-PLAN.md](USER-JOURNEY-TEST-PLAN.md) proposes workflows across
modules and Manager/Worker/Viewer accounts, with fixtures and implementation stages.
All specs live under `tests/`; feature specs are in `tests/features/`, shared
browser helpers in `support/`, and persistence helpers in `helpers.js`.

## Disposable container suites

Run these commands from the repository root with Task, Docker Compose, and
Python 3 available. Task derives image references from the root `.env` settings
`FARMOS_IMAGE_NAME` and `FARMOS_IMAGE_TAG`, adding the selected variant's suffix.
The configured images must already be loaded in Docker; these commands do not
invoke Nix:

```sh
task test VARIANT=production SUITE=e2e LOADED=true
task test SUITE=contrib LOADED=true
CONTRIB_MODULES=crop_plan task test SUITE=contrib LOADED=true
```

The contrib suite uses both runtime variants from the same profile. Enable them
in `FARMOS_IMAGE_VARIANTS` and load them before running the suite. To test a
different existing image set, override `FARMOS_IMAGE_NAME` or `FARMOS_IMAGE_TAG`
for the Task invocation rather than supplying separate test image variables.

The central [`tests/compose.yaml`](../compose.yaml) defines the `e2e` and `contrib`
profiles alongside the other container test suites. Task creates a fresh Compose
project for each suite, starts its required services, collects reports and logs,
and removes the project's containers, networks, and volumes on success or failure.
This is a disposable test environment, not a persistent development stack.

Task supplies `TEST_COMPOSE_PROJECT`, `TEST_COMPOSE_FILE`, and `TEST_ARTIFACTS` to
the internal shell runners. Use `task test` with `LOADED=true` instead of calling
`scripts/test.sh` or `scripts/contrib-test.sh` directly. Those runners rely on the
Task-provided services and paths. See the
[shared test stack guide](../../docs/guide.md#shared-disposable-test-stack) for
other profiles, including PHPUnit.

## Browser-only runs against a disposable site

From this directory, install the pinned dependencies and Chromium:

```sh
npm ci
npx playwright install chromium
```

The installation phase requires a fresh, disposable farmOS instance and database
that the farmOS server can reach. It installs the site and enables the standard
base modules through the wizard and module form. Google Maps, Mapbox and
localization downloads are excluded. Supply the public URL and the
database hostname as seen by the farmOS server. If the server supplies database
settings, set `FARMOS_DB_PRECONFIGURED=1` to skip that form. Site and account setup
still run through the browser:

```sh
BASE_URL=http://localhost:8080 FARMOS_DB_HOST=db npm run test:install
```

Browser-only commands use the defaults below. The Task-managed stack supplies
its own service settings. Override these values to match a different disposable
test site:

| Variable | Default |
| --- | --- |
| `BASE_URL` | `http://farmos:8080` |
| `FARMOS_DB_PRECONFIGURED` | `0`, set to `1` when the server already supplies database settings |
| `FARMOS_DB_HOST` | `db` |
| `FARMOS_DB_NAME` | `farmos` |
| `FARMOS_DB_USER` | `farm` |
| `FARMOS_DB_PASS` | `farm-test-password` |
| `FARMOS_ADMIN_USER` | `farm-admin` |
| `FARMOS_ADMIN_PASSWORD` | `Container-test-password-938!` |
| `FARMOS_ADMIN_EMAIL` | `admin@example.test` |
| `FARMOS_OAUTH_KEY_DIR` | Derived from the OAuth settings form; Compose supplies `/opt/farmos/private_files/keys` for immutable production settings |
| `TEST_ARTIFACTS` | `./artifacts` |
| `TEST_PHASE` | `core`; also accepts `install`, `smoke`, `persistence`, `contrib`, `contrib-persistence` |
| `CONTRIB_MODULES` | All seven modules; comma-separated module names to select a subset |

Run the core suite against the installed site:

```sh
BASE_URL=http://localhost:8080 npm test
# Or select a feature file while developing:
BASE_URL=http://localhost:8080 npm test -- tests/features/assets.spec.js
# A quick record/upload check without the full feature suite:
BASE_URL=http://localhost:8080 npm run test:smoke
```

The core phase writes saved record URLs to `TEST_ARTIFACTS/records.json` and
public OAuth signing keys to `TEST_ARTIFACTS/oauth-state.json`.
Recreate the farmOS and database containers while retaining their data volumes,
then run the persistence phase with the same artifact directory and account settings:

```sh
BASE_URL=http://localhost:8080 npm run test:persistence
```

The persistence phase opens a fresh browser session, logs in, and verifies the
records, asset/log relationship, exact uploaded bytes and unchanged OAuth public
keys. It fails if the core phase's state files are missing. A smoke-only run does
not produce the OAuth snapshot and cannot replace the core phase here.

Tests use unique record names and fresh browser contexts. Feature tests create
their own data through normal UI/API workflows; there is no prefilled database,
recipe dependency or test-only server endpoint. The suite runs one worker to
avoid concurrent site-configuration and module-installation changes. Retries are
disabled so a partially completed mutation does not hide a failure.

Each phase writes JUnit and HTML reports, and keeps screenshots, video,
and traces on failure. Use `npx playwright show-report artifacts/core/report`
to inspect a report.

The Task-managed E2E suite uses the stock Microsoft Playwright container. The
test project is mounted read-only, and `npm ci` installs its pinned dependencies
once into a disposable volume mounted at `/tests/node_modules`. The stock image
includes browsers and system dependencies, while the project supplies
`@playwright/test` through its own manifest and lock file. See the
[Playwright Docker documentation](https://playwright.dev/docs/docker#introduction).
Keep the Playwright image version in the shared [`tests/compose.yaml`](../compose.yaml)
aligned with `package.json` and `package-lock.json` when upgrading.

The suite installs farmOS, runs core tests, recreates the application and database
containers while retaining their test volumes, then checks persistence and Drush
cron. It reads Drupal's persisted last-cron timestamp to confirm execution. The
shared stack supplies test-only database settings; the image generates and saves
its hash salt in private storage. Only public files and `/opt/farmos/private_files`
are writable application data mounts. The suite checks protected settings and
writable storage before installation and after recreation. Task owns final log
collection and volume removal even if any phase fails, and prints the report
location for that run.

## Contributed modules

The default contrib suite includes Calendar, Ledger, Eggs, Beekeeping, Fungi,
Crop Plan and Grazing Plan. Both planning modules allow alpha releases and
participate in the normal run. Failures fail the suite. Findings are recorded in
[CONTRIB-ISSUES.md](CONTRIB-ISSUES.md).

Use `task test SUITE=contrib LOADED=true` from the repository root as shown above.
`CONTRIB_MODULES` selects a subset for a run; it still gets fresh database and
application storage through its own disposable Task-managed project.

Images must already be available in Docker. A separate image build is not needed
for Playwright or for the contrib codebase. The development runtime resolves fresh compatible dependencies from
`fixtures/contrib/composer.json`, including the latest stable farmOS 4 release,
without Composer development dependencies.
The production runtime serves that project through a read-only mount. The
fixture's `settings.php` uses the runtime's `/usr/share/farmos/environment.php`
contract. Only file volumes and temporary directories are writable. The shared
Compose services and Task lifecycle come from the parent repository.

The suite installs farmOS through the browser, enables selected modules with
Drush, and runs their browser/API workflows. It recreates the application and
database containers, then checks saved records, quantities, relationships, and
uploaded bytes in fresh sessions before running cron. Task collects JUnit/HTML
reports, traces, the exact Composer lock, enabled-module inventory, and container
logs in the run's artifact directory, then removes the disposable stack even on
failure. Default runs prepare a fresh temporary contrib codebase. The Composer
download cache can be reused; `COMPOSER_CACHE_PATH` selects its location.

Against an already installed disposable site with these modules enabled:

```sh
BASE_URL=http://localhost:8080 npm run test:contrib
# After recreating the site's containers while preserving its data volumes:
BASE_URL=http://localhost:8080 npm run test:contrib-persistence
```

Browser-only tests can be moved with this directory's npm manifests, specs,
fixtures, and helpers when a disposable farmOS site is supplied separately. To
retain automatic container orchestration, also retain the parent repository's
Task files, test lifecycle code, and shared `tests/compose.yaml`. Copying only the
E2E directory does not provide the disposable service stack or cleanup lifecycle.

The [Drupal Playwright project](https://git.drupalcode.org/project/playwright)
provides Drupal-specific test-site tooling. This suite keeps its HTTP-only
helpers so it can test a remote farmOS deployment without local Drupal source
or PHP. Reconsider those fixtures for future suites that deliberately need a
local Drupal test site.
