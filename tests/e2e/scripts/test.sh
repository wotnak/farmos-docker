#!/usr/bin/env bash
# Run production acceptance phases in the disposable stack created by Task.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
: "${TEST_COMPOSE_PROJECT:?Run this phase through Task}"
: "${TEST_COMPOSE_FILE:?Task must supply the shared Compose file}"
: "${TEST_ARTIFACTS:?Task must supply the artifact directory}"
: "${TEST_SUITE:?Task must select the Compose profile}"
: "${TEST_SERVICE:?Task must select the application service}"
: "${BASE_URL:?Task must supply the application URL}"
compose=(docker compose --env-file /dev/null -p "$TEST_COMPOSE_PROJECT" -f "$TEST_COMPOSE_FILE" --profile "$TEST_SUITE")

check_storage() {
  "${compose[@]}" exec -T "$TEST_SERVICE" /usr/bin/php -r '
    $settings = "/opt/farmos/web/sites/default/settings.php";
    foreach ([$settings, dirname($settings)] as $path) {
      if (!file_exists($path) || is_writable($path)) {
        fwrite(STDERR, "Expected an existing read-only path: $path\n");
        exit(1);
      }
      echo "Read-only: $path\n";
    }
    foreach (["/opt/farmos/web/sites/default/files", "/opt/farmos/private_files"] as $path) {
      $probe = $path . "/.acceptance-write-" . bin2hex(random_bytes(8));
      if (!is_dir($path) || !is_writable($path)
          || file_put_contents($probe, "write test") !== 10 || !unlink($probe)) {
        fwrite(STDERR, "Expected a writable data directory: $path\n");
        exit(1);
      }
      echo "Writable: $path\n";
    }
  '
}

printf '%s\n' "$TEST_COMPOSE_PROJECT" >"$TEST_ARTIFACTS/project.txt"
# Docker needs the nested volume mount point to exist inside the read-only bind.
mkdir -p "$root/node_modules"
"${compose[@]}" run --rm --no-deps playwright npm ci --ignore-scripts --no-audit --no-fund \
  2>&1 | tee "$TEST_ARTIFACTS/dependencies.log"
check_storage | tee "$TEST_ARTIFACTS/storage-before.log"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=install playwright
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=core playwright
"${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/before-recreation.log"
# Recreate both application and database containers without deleting their volumes.
"${compose[@]}" down
"${compose[@]}" up -d --wait --wait-timeout 120 "$TEST_SERVICE"
check_storage | tee "$TEST_ARTIFACTS/storage-after.log"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=persistence playwright
cron_started=$("${compose[@]}" exec -T "$TEST_SERVICE" /bin/date +%s)
"${compose[@]}" exec -T "$TEST_SERVICE" /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php \
  "--uri=$BASE_URL" cron 2>&1 | tee "$TEST_ARTIFACTS/cron.log"
# Read Drupal's persisted state in a separate process, not just the command exit code.
cron_last=$("${compose[@]}" exec -T "$TEST_SERVICE" /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php \
  "--uri=$BASE_URL" state:get system.cron_last --format=string)
printf 'cron_started=%s\nsystem.cron_last=%s\n' "$cron_started" "$cron_last" | tee -a "$TEST_ARTIFACTS/cron.log"
case "$cron_last" in
  ''|*[!0-9]*) echo 'Drush did not return a numeric last-cron timestamp.' >&2; exit 1 ;;
esac
if [ "$cron_last" -lt "$cron_started" ]; then
  echo 'Drush cron did not persist a current successful-run timestamp.' >&2
  exit 1
fi
printf 'Production acceptance test passed.\n'
