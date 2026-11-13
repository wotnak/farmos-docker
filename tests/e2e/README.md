# farmOS end-to-end tests

This independent Playwright project tests farmOS through its browser and HTTP
interfaces. Its browser tests can target an existing site. Its Compose runners
can create a disposable site using supplied container images, without Nix or
files from the parent repository. Run it against a
disposable site: tests create, modify and delete farm records and test accounts.

`npm test` runs the core feature suite, including the persistence seed scenario.
See [COVERAGE.md](COVERAGE.md) for the scenario matrix and known limits, and
[CONTRIB-TEST-PLAN.md](CONTRIB-TEST-PLAN.md) for module coverage and deferred additions.
Further research is in [CONTRIB-CANDIDATES.md](CONTRIB-CANDIDATES.md).
[USER-JOURNEY-TEST-PLAN.md](USER-JOURNEY-TEST-PLAN.md) proposes workflows across
modules and Manager/Worker/Viewer accounts, with fixtures and implementation stages.
All specs live under `tests/`; feature specs are in `tests/features/`, shared
browser helpers in `support/`, and persistence helpers in `helpers.js`.

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

Defaults are for the repository's disposable Compose stack. Override them when
running against another test environment:

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

From this directory, `bash scripts/test.sh` supplies the disposable Compose
stack and the stock Microsoft Playwright container. The test project is mounted
read-only, and `npm ci` installs its pinned dependencies once into a disposable
Compose volume mounted at `/tests/node_modules`. The stock image includes browser
binaries and system dependencies, but the project must install `@playwright/test`
from its own package manifest and lock file, as explained in the
[Playwright Docker documentation](https://playwright.dev/docs/docker#introduction). It runs installation and core tests, recreates
the containers, and runs persistence tests and Drush cron. It checks Drupal's
persisted last-cron timestamp to confirm execution. The Compose stack supplies
fixed test-only database settings through environment variables. The image generates
and persists its hash salt in the private-files volume.
Only public files and `/opt/farmos/private_files` use writable application data
volumes. The runner checks that `settings.php` and its parent stay read-only while
both file directories remain writable before installation and after recreation.
farmOS and PostgreSQL use an internal network; only the Playwright service also
has an external network for installing npm dependencies and loading browser assets. It collects container logs and removes its containers and volumes.
The Playwright image tag in `compose.yaml` and npm dependency use matching
versions; update both
along with `package-lock.json` when upgrading.

## Contributed modules

The default contrib suite includes Calendar, Ledger, Eggs, Beekeeping, Fungi,
Crop Plan and Grazing Plan. Both planning modules allow alpha releases and
participate in the normal run. Failures fail the suite. Findings are recorded in
[CONTRIB-ISSUES.md](CONTRIB-ISSUES.md).

With Docker Compose and Python 3 available, run from this directory:

```sh
# The base suite uses a complete farmOS image.
IMAGE=ghcr.io/wotnak/farmos:4 bash scripts/test.sh
# Contrib uses the supplied runtime images and its own Composer project.
RUNTIME_IMAGE=ghcr.io/wotnak/farmos:4-runtime \
DEV_RUNTIME_IMAGE=ghcr.io/wotnak/farmos:4-dev-runtime bash scripts/contrib-test.sh
# Select a module while developing. It gets its own fresh database and volumes.
CONTRIB_MODULES=crop_plan bash scripts/contrib-test.sh
```

Images must already be available in Docker. A separate image build is not needed
for Playwright or for the contrib codebase. The development runtime resolves fresh compatible dependencies from
`fixtures/contrib/composer.json`, including the latest stable farmOS 4 release,
without Composer development dependencies.
The production runtime serves that project through a read-only mount. The
fixture's `settings.php` uses the runtime's `/usr/share/farmos/environment.php`
contract. It is part of this project, so no parent-repository settings file is
needed. Only file volumes and temporary directories are writable.

The runner installs farmOS through the browser, enables the selected contrib
modules with Drush, runs their browser/API workflows, recreates both application
and database containers, then checks saved records, quantities, relationships
and uploaded bytes in fresh sessions. It runs cron and removes its containers
and volumes, including on failure. JUnit/HTML reports, traces, exact Composer
locks, enabled-module inventory and container logs are saved under
`artifacts/contrib/run-*`. Each run prepares a fresh codebase, then removes it
during cleanup. Only the Composer download cache is reused under
`artifacts/contrib/composer-cache/`. `TEST_ARTIFACTS` changes the report parent;
`COMPOSER_CACHE_PATH` overrides the download-cache directory. For local module
development, `FARMOS_PROJECT_PATH` opts into reusing a prepared project and keeps
it after the run. That mode can retain local package edits, so leave it unset
when validating fresh dependencies. Do not prepare a shared project concurrently.

Against an already installed disposable site with these modules enabled:

```sh
BASE_URL=http://localhost:8080 npm run test:contrib
# After recreating the site's containers while preserving its data volumes:
BASE_URL=http://localhost:8080 npm run test:contrib-persistence
```

To extract this suite, copy this entire directory, including its dotfiles.
The `scripts/`, both Compose files, `fixtures/`, browser specs and npm
manifest are self-contained. The parent repository's Task and CI commands are
thin callers. Each contrib run resolves its own compatible dependency set and
saves the generated Composer lock with its reports. Its Docker images need to
implement the paths and environment contract described above.

The [Drupal Playwright project](https://git.drupalcode.org/project/playwright)
provides Drupal-specific test-site tooling. This suite keeps its HTTP-only
helpers so it can test a remote farmOS deployment without local Drupal source
or PHP. Reconsider those fixtures for future suites that deliberately need a
local Drupal test site.
