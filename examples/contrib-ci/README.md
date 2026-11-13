# Module CI with the farmOS development image

The existing `-dev` image already supplies farmOS, Composer, native PHP CLI,
PHPUnit, Drupal Coder/PHPCS and PHPStan with Drupal support. A module can run these
tools directly. No additional image or shared CI helper framework is needed.

Copy [.github/workflows/farmos.yml](.github/workflows/farmos.yml) or the job in
[.gitlab-ci.yml](.gitlab-ci.yml) into your module repository. `FARMOS_DEV_IMAGE` defaults to
`ghcr.io/wotnak/farmos:4-dev`, following the latest tracked farmOS 4 development release.
Use an immutable image digest to pin the environment.
The image must be published or loaded into the runner before running the job.
Use the GitHub repository variable or GitLab CI/CD variable `FARMOS_DEV_IMAGE`
to select another image.

The project name is read from `composer.json` when present, using its
`drupal/NAME` package name. This also supports projects containing several modules.
Without `composer.json`, detection uses the single root `*.info.yml` filename;
nested submodule and test-fixture files are ignored. Ambiguous filenames and
invalid Composer metadata fail with a clear error.

The jobs prefer module-owned configurations: `.phpcs.xml`, `phpcs.xml`,
`.phpcs.xml.dist`, `phpcs.xml.dist` for PHPCS; `phpstan.neon`, `phpstan.neon.dist`,
`phpstan.dist.neon` for PHPStan. Otherwise they use the configurations shipped by
farmOS at `/opt/farmos/phpcs.xml` and `/opt/farmos/phpstan.neon`. Explicit command
line module paths keep both tools scoped to the checkout.

When Composer metadata is present, the jobs use a Composer path repository to
install the checked-out `drupal/NAME` package under `web/modules/NAME`. Assigning
it `dev-ci` ensures Composer tests that checkout rather than a published release.
Without a Composer manifest, the checkout is copied directly into that directory.

Composer installs declared runtime dependencies, but does not install a
package's `require-dev`. Add explicit `composer require` or
`composer require --dev` commands for dependencies not installed through the
module manifest.
An `.info.yml` dependency declaration alone does not download another module.
Add any private repositories or custom test autoload configuration your project
needs explicitly. The templates do not rewrite module manifests.

Composer runs inside the disposable development container and keeps its resolved
lock as an artifact. The checkout is not modified. The normal partial update
keeps existing farmOS dependencies locked where compatible; an incompatible
module constraint fails resolution. Avoid `--with-all-dependencies` when the
purpose is to test the image's farmOS version. For reproducible jobs, pin
additional dependency versions or use a reviewed module-specific application
lock in your own CI project.

PHPCS and PHPStan analyze only the installed module. PHPUnit uses the image's
Drupal bootstrap/configuration and the module directory as its test scope. Change
`-c phpunit.xml` to the installed module's own configuration when it has one,
checking that bootstrap paths fit this application layout. Use `--filter` for a
class or method. Do not combine a positional module directory with `--testsuite`:
PHPUnit's directory selection takes precedence over the configured suite.
Empty PHPUnit selections fail these jobs. The module/core PHPUnit configuration
controls skipped, incomplete and deprecated-test policy.

Unit tests do not need a database. Kernel and ordinary Functional tests use the
provided PostgreSQL service; Functional tests also use the bundled FrankenPHP
server. They install their own Drupal test sites, so no normal farmOS browser
installation is required. Browser HTML is copied from
`web/sites/simpletest/browser_output`: `BROWSERTEST_OUTPUT_DIRECTORY` controls
Drupal's temporary link log, not the location of those HTML files.

GitHub runs checkout/upload actions on the host and executes the PHP tools in
Docker. This avoids requiring GitHub's Node runtime inside the Nix image; service
networking follows [GitHub's PostgreSQL example](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
The GitLab job can coexist with Drupal.org's standard templates and explicitly
replaces inherited setup/teardown. It uses [GitLab's image Docker user setting](https://docs.gitlab.com/ci/yaml/#imagedocker)
(Runner 16.8+) so the job can write its checkout/artifacts. Both examples run as
root only inside disposable CI containers; the image normally uses UID 65532.
See Drupal's [template customization guide](https://project.pages.drupalcode.org/gitlab_templates/info/customizations/)
for adding this job alongside standard Drupal compatibility jobs.

## Running locally

The [Compose example](compose.yaml) starts the same development image and a
disposable database. From this container repository:

```sh
export MODULE_PATH=/absolute/path/to/module
export ARTIFACTS_PATH="$PWD/artifacts"
mkdir -p "$ARTIFACTS_PATH"
docker compose -f examples/contrib-ci/compose.yaml up -d --wait ci
docker compose -f examples/contrib-ci/compose.yaml exec ci bash
```

Inside the container, run the standard commands directly:

```sh
cd /opt/farmos
chmod -R u+w .
checkout=/checkout
if [ -f "$checkout/composer.json" ]; then
  module_name=$(php -r '
    $package = json_decode(file_get_contents($argv[1]), true, flags: JSON_THROW_ON_ERROR);
    if (!preg_match("~^drupal/([a-z][a-z0-9_]*)$~D", $package["name"] ?? "", $match)) {
      fwrite(STDERR, "Expected a drupal/MACHINE_NAME package name in composer.json.\n");
      exit(1);
    }
    echo $match[1];
  ' "$checkout/composer.json")
else
  set -- "$checkout"/*.info.yml
  if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo 'Without composer.json, expected exactly one *.info.yml in the checkout root.' >&2
    exit 1
  fi
  module_name=$(basename "$1" .info.yml)
fi
case "$module_name" in
  ''|[!a-z]*|*[!a-z0-9_]*) echo 'Invalid module machine name.' >&2; exit 1 ;;
esac
if [ -f "$checkout/composer.json" ]; then
  composer config repositories.module-ci "$(printf '{"type":"path","url":"%s","options":{"symlink":false,"versions":{"drupal/%s":"dev-ci"}}}' "$checkout" "$module_name")"
  composer require --no-interaction --prefer-dist "drupal/$module_name:dev-ci"
else
  # Without Composer metadata, install additional dependencies explicitly below.
  mkdir "web/modules/$module_name"
  cp -R "$checkout/." "web/modules/$module_name/"
fi
# Add your module's test-only dependencies here, if needed.
module="web/modules/$module_name"
phpcs_config=/opt/farmos/phpcs.xml
for config in .phpcs.xml phpcs.xml .phpcs.xml.dist phpcs.xml.dist; do
  if [ -f "$module/$config" ]; then phpcs_config="$module/$config"; break; fi
done
phpstan_config=
for config in phpstan.neon phpstan.neon.dist phpstan.dist.neon; do
  if [ -f "$module/$config" ]; then phpstan_config="$module/$config"; break; fi
done
if [ -z "$phpstan_config" ]; then
  # Core ignores apply to its full codebase; an unused ignore is harmless here.
  printf '%s\n' 'includes:' '  - /opt/farmos/phpstan.neon' 'parameters:' '  reportUnmatchedIgnoredErrors: false' > /tmp/farmos-module-phpstan.neon
  phpstan_config=/tmp/farmos-module-phpstan.neon
fi
php vendor/bin/phpcs --standard="$phpcs_config" "$module" </dev/null
php vendor/bin/phpstan analyse -c "$phpstan_config" "$module"
mkdir -p /artifacts/browser-output
php vendor/bin/phpunit -c phpunit.xml --fail-on-empty-test-suite --log-junit /artifacts/phpunit.xml "$module"
if [ -d web/sites/simpletest/browser_output ]; then
  cp -R web/sites/simpletest/browser_output/. /artifacts/browser-output/
fi
exit
```

Remove the disposable containers/database afterward:

```sh
docker compose -f examples/contrib-ci/compose.yaml down --volumes
```

For FunctionalJavascript tests, also start `chrome` with
`docker compose -f examples/contrib-ci/compose.yaml --profile browser up -d chrome`
and wait for Selenium's status endpoint to report ready. The example supplies
`MINK_DRIVER_ARGS_WEBDRIVER`, and Chromium can reach the application at
`http://ci:8080`. The GitHub/GitLab templates omit Selenium; add that service and
appropriate networking when the module needs it. JavaScript lint/build work
belongs in a separate Node job.

## Validation and compatibility findings

`tests/contrib-ci-test.sh` verifies these native tools against the stock `-dev`
image. Its fixture requires Ledger plus test-only Symfony Clock and Crop Plan
packages, runs Unit/Kernel/Functional tests, and checks the checkout's source and
unchanged base dependency lock. It also runs Crop Plan's real upstream Kernel
test and verifies nonzero exits for coding violations, static-analysis errors,
failed assertions and empty test selections. It checks both module-owned and
farmOS fallback configurations, rejects malformed module configurations, and
verifies that files outside the module are not analyzed. Functional HTML is retained.

The fixture passed 3 tests and 12 assertions, with 71 farmOS/Drupal dependency
deprecations reported. Crop Plan `3.0.0-alpha4` passed 1 test and 143 assertions,
with 15 Drupal/dependency deprecations and 2 PHPUnit metadata deprecations.
These concern legacy constraint annotations, future return types and docblock
metadata. Reports retain them; no suppression was added. Projects can choose a
stricter deprecation policy in their own PHPUnit configuration.

The shipped farmOS PHPStan config enables unmatched-ignore reporting for its
whole codebase. For the fallback only, the examples include it from a temporary
config with `reportUnmatchedIgnoredErrors: false`: a module can legitimately lack
the core code covered by its `Unsafe usage of new static` ignore. This does not
ignore additional findings or change module-owned configurations. The shipped
PHPCS config also still declares `drupal_core_version=10` despite Drupal 11.3.14.
The examples preserve that upstream setting; this is a configuration observation,
not a reproduced runtime defect.
