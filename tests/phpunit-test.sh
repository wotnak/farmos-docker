#!/usr/bin/env bash
# Run the upstream farmOS profile tests from the supplied development image.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export IMAGE=${IMAGE:-ghcr.io/wotnak/farmos:4-dev}
project="farmos-phpunit-$(date +%s)-$$-$RANDOM"
artifacts=${TEST_ARTIFACTS:-"$root/build/tests/phpunit"}/$project
mkdir -p "$artifacts"
artifacts=$(cd "$artifacts" && pwd)
compose=(docker compose --env-file /dev/null --project-name "$project" --file "$root/tests/compose.phpunit.yaml")

cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" ps --all >"$artifacts/compose-ps.txt" 2>&1 || true
  "${compose[@]}" logs --no-color >"$artifacts/compose.log" 2>&1 || true
  "${compose[@]}" cp farmos:/tmp/phpunit/. "$artifacts/" >/dev/null 2>&1 || true
  "${compose[@]}" cp farmos:/opt/farmos/web/sites/simpletest/browser_output/. \
    "$artifacts/browser-output/" >/dev/null 2>&1 || true
  if ! "${compose[@]}" down --volumes --remove-orphans >>"$artifacts/cleanup.log" 2>&1; then
    echo "Could not remove Compose project $project; see $artifacts/cleanup.log" >&2
    status=1
  fi
  echo "PHPUnit artifacts: $artifacts"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Never pull a published farmOS image in place of the image being tested.
docker image inspect "$IMAGE" >"$artifacts/image.json"
"${compose[@]}" config >"$artifacts/compose.yaml"
"${compose[@]}" up --detach --wait --wait-timeout 180
"${compose[@]}" exec -T farmos /bin/sh -ec '
  test -f vendor/bin/phpunit
  test -f phpunit.xml
  test -d web/profiles/farm/modules
  chmod -R u+w web/sites
  mkdir -p /tmp/phpunit/browser-output
'

# Positional arguments permit a filtered diagnostic run. The default discovers
# every upstream test in the exact farmOS profile packaged in the image.
"${compose[@]}" exec -T farmos /usr/bin/php vendor/bin/phpunit \
  --configuration /opt/farmos/phpunit.xml \
  --fail-on-empty-test-suite --fail-on-skipped --fail-on-incomplete \
  --display-skipped --display-incomplete \
  --log-junit /tmp/phpunit/junit.xml \
  "$@" /opt/farmos/web/profiles/farm 2>&1 | tee "$artifacts/phpunit.log"
