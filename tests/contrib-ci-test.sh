#!/usr/bin/env bash
# Verify native module CI tools in the existing development image.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
export IMAGE=${IMAGE:-ghcr.io/wotnak/farmos:4-dev}
parent=${TEST_ARTIFACTS:-$root/build/tests/contrib-ci}
mkdir -p "$parent"
parent=$(cd "$parent" && pwd)
export TEST_ARTIFACTS
TEST_ARTIFACTS=$(mktemp -d "$parent/run-XXXXXXXX")
project="farmos-contrib-ci-$$-$RANDOM"
compose=(docker compose --env-file /dev/null -p "$project" -f "$root/tests/compose.contrib-ci.yaml")
cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/compose.log" 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >"$TEST_ARTIFACTS/cleanup.log" 2>&1 || status=1
  printf 'Development image module CI artifacts: %s\n' "$TEST_ARTIFACTS"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker image inspect "$IMAGE" >"$TEST_ARTIFACTS/image.json"
"${compose[@]}" config >"$TEST_ARTIFACTS/compose.yaml"
"${compose[@]}" up -d --wait --wait-timeout 120
# This fixture owns its CI dependency list. Composer installs runtime requirements
# of the checkout; its additional test requirements are requested explicitly.
"${compose[@]}" exec -T ci /bin/bash -se 2>&1 <<'PREPARE' | tee "$TEST_ARTIFACTS/composer.log"
cd /opt/farmos
chmod -R u+w .
mkdir -p /artifacts/positive/browser-output
cp composer.lock /artifacts/base-composer.lock
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
  composer require --no-interaction --no-progress --prefer-dist "drupal/$module_name:dev-ci"
else
  # Without Composer metadata, install additional dependencies explicitly below.
  mkdir "web/modules/$module_name"
  cp -R "$checkout/." "web/modules/$module_name/"
fi
composer require --dev --no-interaction --no-progress --prefer-dist symfony/clock:7.4.0 drupal/farm_crop_plan:3.0.0-alpha4
cp composer.json composer.lock /artifacts/
cmp /checkout/src/Calculator.php "web/modules/$module_name/src/Calculator.php"
PREPARE
# Check the fixture exercised the packaged farmOS dependency set unchanged.
python3 - "$TEST_ARTIFACTS" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
base, actual = (json.loads((root / name).read_text()) for name in ['base-composer.lock', 'composer.lock'])
packages = {p['name']: p for key in ['packages', 'packages-dev'] for p in actual[key]}
for group in ['packages', 'packages-dev']:
    for package in base[group]:
        for key in ['version', 'source', 'dist']:
            assert packages[package['name']].get(key) == package.get(key), (package['name'], key)
assert packages['drupal/farm_ci_example']['version'] == 'dev-ci'
assert packages['symfony/clock']['version'] == 'v7.4.0'
assert packages['drupal/farm_ledger']['version'] == '3.0.0'
PY
module=/opt/farmos/web/modules/farm_ci_example
"${compose[@]}" exec -T ci /bin/bash -s <<'QA'
set -euo pipefail
module=/opt/farmos/web/modules/farm_ci_example
# An invalid file outside the module must not be checked through core's <file>.</file>.
printf '<?php INVALID {' > /opt/farmos/outside-module-scope.php
for phase in positive fallback; do
  mkdir -p "/artifacts/$phase"
  if [ "$phase" = fallback ]; then
    mv "$module/phpcs.xml.dist" "$module/phpcs.xml.dist.hidden"
    mv "$module/phpstan.neon" "$module/phpstan.neon.hidden"
  fi
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
  printf 'PHPCS=%s\nPHPStan=%s\n' "$phpcs_config" "$phpstan_config" > "/artifacts/$phase/configs.txt"
  if [ "$phase" = fallback ]; then
    # The fixture's level 0 allows this return; farmOS's level 5 must reject it.
    if php vendor/bin/phpstan analyse -c "$phpstan_config" --no-progress --error-format=junit "$module" > /artifacts/policy-core.xml; then
      echo 'Core PHPStan policy unexpectedly accepted the incorrect return type.' >&2
      exit 1
    fi
    rm "$module/src/PolicyProbe.php"
  fi
  php vendor/bin/phpcs --standard="$phpcs_config" --report-full --report-json="/artifacts/$phase/phpcs.json" --report-junit="/artifacts/$phase/phpcs.xml" "$module" </dev/null
  php vendor/bin/phpstan analyse -c "$phpstan_config" --no-progress --error-format=junit "$module" > "/artifacts/$phase/phpstan.xml" 2> "/artifacts/$phase/phpstan.log"
  if [ "$phase" = positive ]; then
    cat > "$module/src/PolicyProbe.php" <<'PHP'
<?php
namespace Drupal\farm_ci_example;
final class PolicyProbe {
  public function value(): int { return "module level zero allows this"; }
}
PHP
    php vendor/bin/phpstan analyse -c "$phpstan_config" --no-progress --error-format=junit "$module" > /artifacts/policy-module.xml
  fi
done
mv "$module/phpcs.xml.dist.hidden" "$module/phpcs.xml.dist"
mv "$module/phpstan.neon.hidden" "$module/phpstan.neon"
rm /opt/farmos/outside-module-scope.php
# An existing malformed module configuration must fail, never fall back to core.
cp "$module/phpcs.xml.dist" /tmp/module-phpcs.xml
cp "$module/phpstan.neon" /tmp/module-phpstan.neon
printf '<ruleset><invalid' > "$module/phpcs.xml.dist"
printf 'parameters: [invalid' > "$module/phpstan.neon"
phpcs_config=/opt/farmos/phpcs.xml
for config in .phpcs.xml phpcs.xml .phpcs.xml.dist phpcs.xml.dist; do
  if [ -f "$module/$config" ]; then phpcs_config="$module/$config"; break; fi
done
phpstan_config=/tmp/farmos-module-phpstan.neon
for config in phpstan.neon phpstan.neon.dist phpstan.dist.neon; do
  if [ -f "$module/$config" ]; then phpstan_config="$module/$config"; break; fi
done
if php vendor/bin/phpcs --standard="$phpcs_config" "$module" </dev/null > /artifacts/phpcs-malformed.log 2>&1; then
  echo 'Malformed module PHPCS configuration unexpectedly succeeded.' >&2
  exit 1
fi
if php vendor/bin/phpstan analyse -c "$phpstan_config" --no-progress "$module" > /artifacts/phpstan-malformed.log 2>&1; then
  echo 'Malformed module PHPStan configuration unexpectedly succeeded.' >&2
  exit 1
fi
mv /tmp/module-phpcs.xml "$module/phpcs.xml.dist"
mv /tmp/module-phpstan.neon "$module/phpstan.neon"
QA
python3 - "$TEST_ARTIFACTS" <<'PY'
import json, pathlib, sys, xml.etree.ElementTree as ET
root = pathlib.Path(sys.argv[1])
assert '/web/modules/farm_ci_example/phpcs.xml.dist' in (root / 'positive/configs.txt').read_text()
assert '/web/modules/farm_ci_example/phpstan.neon' in (root / 'positive/configs.txt').read_text()
assert 'PHPCS=/opt/farmos/phpcs.xml' in (root / 'fallback/configs.txt').read_text()
assert 'PHPStan=/tmp/farmos-module-phpstan.neon' in (root / 'fallback/configs.txt').read_text()
for phase in ['positive', 'fallback']:
    files = json.loads((root / phase / 'phpcs.json').read_text())['files']
    assert files and all('/web/modules/farm_ci_example/' in path for path in files), files
assert ET.parse(root / 'policy-core.xml').getroot().findall('.//failure')
assert not ET.parse(root / 'policy-module.xml').getroot().findall('.//failure')
PY
"${compose[@]}" exec -T ci /bin/bash -ec '
  result=0
  php vendor/bin/phpunit --configuration phpunit.xml --fail-on-empty-test-suite --fail-on-skipped --fail-on-incomplete \
    --log-junit /artifacts/positive/phpunit.xml web/modules/farm_ci_example || result=$?
  cp -R web/sites/simpletest/browser_output/. /artifacts/positive/browser-output/
  exit "$result"
' 2>&1 | tee "$TEST_ARTIFACTS/phpunit.log"
python3 - "$TEST_ARTIFACTS/positive" <<'PY'
import pathlib, sys, xml.etree.ElementTree as ET
root = pathlib.Path(sys.argv[1])
report = ET.parse(root / 'phpunit.xml').getroot()
cases = report.findall('.//testcase')
assert len(cases) == 3, [case.attrib for case in cases]
assert not report.findall('.//failure') and not report.findall('.//error') and not report.findall('.//skipped')
assert {case.attrib['name'] for case in cases} == {'testAddition', 'testDatabaseAndDependency', 'testModulePage'}
assert list((root / 'browser-output').glob('*.html')), 'Retain real Functional browser output.'
PY
"${compose[@]}" exec -T ci php vendor/bin/phpunit --configuration phpunit.xml \
  --fail-on-empty-test-suite --fail-on-skipped --fail-on-incomplete \
  --log-junit /artifacts/crop-plan-kernel.xml web/modules/farm_crop_plan/tests/src/Kernel \
  2>&1 | tee "$TEST_ARTIFACTS/crop-plan-kernel.log"
expect_failure() {
  local name=$1
  shift
  if "${compose[@]}" exec -T ci "$@" >"$TEST_ARTIFACTS/$name.log" 2>&1; then
    echo "Expected $name to fail, but it succeeded." >&2
    return 1
  fi
}
"${compose[@]}" exec -T ci /bin/sh -ec 'cat > /opt/farmos/web/modules/farm_ci_example/src/Broken.php' <<'PHP'
<?php
namespace Drupal\farm_ci_example;
final class Broken {
public function value(): int {return "not an integer";}
}
PHP
expect_failure phpcs-failure php vendor/bin/phpcs --standard="$module/phpcs.xml.dist" --report-junit=/artifacts/phpcs-failure.xml "$module"
expect_failure phpstan-failure php vendor/bin/phpstan analyse --configuration=/tmp/farmos-module-phpstan.neon --error-format=junit --no-progress "$module"
expect_failure phpstan-invalid php vendor/bin/phpstan analyse --configuration=/nonexistent/farmos-ci.neon "$module"
"${compose[@]}" exec -T ci /bin/sh -ec 'rm /opt/farmos/web/modules/farm_ci_example/src/Broken.php; sed -i "s/return \$first + \$second;/return \$first - \$second;/" /opt/farmos/web/modules/farm_ci_example/src/Calculator.php'
expect_failure phpunit-failure php vendor/bin/phpunit --configuration phpunit.xml --fail-on-empty-test-suite --filter testAddition --log-junit /artifacts/phpunit-failure.xml "$module"
expect_failure phpunit-empty php vendor/bin/phpunit --configuration phpunit.xml --fail-on-empty-test-suite --filter NoSuchTestInThisModule --log-junit /artifacts/phpunit-empty.xml "$module"
python3 - "$TEST_ARTIFACTS" <<'PY'
import pathlib, sys, xml.etree.ElementTree as ET
artifacts = pathlib.Path(sys.argv[1])
for path in ['phpcs-failure.xml', 'phpstan-failure.log', 'phpunit-failure.xml']:
    report = ET.parse(artifacts / path).getroot()
    assert report.findall('.//failure') or report.findall('.//error'), path
assert 'farmos-ci.neon' in (artifacts / 'phpstan-invalid.log').read_text()
assert not ET.parse(artifacts / 'phpunit-empty.xml').getroot().findall('.//testcase')
assert 'No tests executed' in (artifacts / 'phpunit-empty.log').read_text()
PY
printf 'Development image passed module quality/tests and rejected deliberate failures.\n'
