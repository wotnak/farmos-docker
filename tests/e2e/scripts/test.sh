#!/usr/bin/env bash
# Test the loaded production image. Every run gets fresh, isolated volumes.
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
export IMAGE=${IMAGE:-ghcr.io/wotnak/farmos:4}
artifact_root=${TEST_ARTIFACTS:-$root/artifacts/core}
mkdir -p "$artifact_root"
artifact_root=$(cd "$artifact_root" && pwd)
export TEST_ARTIFACTS
TEST_ARTIFACTS=$(mktemp -d "$artifact_root/run-XXXXXXXX")
project="farmos-e2e-$(basename "$TEST_ARTIFACTS" | tr '[:upper:]' '[:lower:]')-$$"
compose=(docker compose --env-file /dev/null -p "$project" -f "$root/compose.yaml")

cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/compose.log" 2>&1 || true
  "${compose[@]}" ps --all >"$TEST_ARTIFACTS/containers.txt" 2>&1 || true
  "${compose[@]}" --profile test down --volumes --remove-orphans >"$TEST_ARTIFACTS/cleanup.log" 2>&1 || {
    cat "$TEST_ARTIFACTS/cleanup.log" >&2
    status=1
  }
  printf 'Acceptance test artifacts: %s\n' "$TEST_ARTIFACTS"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
check_storage() {
  "${compose[@]}" exec -T farmos /usr/bin/php -r '
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

printf '%s\n' "$project" >"$TEST_ARTIFACTS/project.txt"
"${compose[@]}" --profile test config >"$TEST_ARTIFACTS/compose.yaml"
docker image inspect "$IMAGE" >"$TEST_ARTIFACTS/image.json"
# Docker needs the nested volume mount point to exist inside the read-only bind.
mkdir -p "$root/node_modules"
"${compose[@]}" run --rm --no-deps playwright npm ci --ignore-scripts --no-audit --no-fund \
  2>&1 | tee "$TEST_ARTIFACTS/dependencies.log"
"${compose[@]}" up -d --wait --wait-timeout 120 farmos
check_storage | tee "$TEST_ARTIFACTS/storage-before.log"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=install playwright
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=core playwright
"${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/before-recreation.log"
# Recreate both application and database containers without deleting their volumes.
"${compose[@]}" down
"${compose[@]}" up -d --wait --wait-timeout 120 farmos
check_storage | tee "$TEST_ARTIFACTS/storage-after.log"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=persistence playwright
cron_started=$("${compose[@]}" exec -T farmos /bin/date +%s)
"${compose[@]}" exec -T farmos /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php \
  --uri=http://farmos:8080 cron 2>&1 | tee "$TEST_ARTIFACTS/cron.log"
# Read Drupal's persisted state in a separate process, not just the command exit code.
cron_last=$("${compose[@]}" exec -T farmos /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php \
  --uri=http://farmos:8080 state:get system.cron_last --format=string)
printf 'cron_started=%s\nsystem.cron_last=%s\n' "$cron_started" "$cron_last" | tee -a "$TEST_ARTIFACTS/cron.log"
case "$cron_last" in
  ''|*[!0-9]*) echo 'Drush did not return a numeric last-cron timestamp.' >&2; exit 1 ;;
esac
if [ "$cron_last" -lt "$cron_started" ]; then
  echo 'Drush cron did not persist a current successful-run timestamp.' >&2
  exit 1
fi
printf 'Production acceptance test passed.\n'
