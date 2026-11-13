#!/usr/bin/env bash
# Each invocation resolves fresh application dependencies and uses a fresh database and volumes.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
allowed='calendar,ledger,eggs,bee,fungi,crop_plan,grazing_plan'
export CONTRIB_MODULES=${CONTRIB_MODULES:-$allowed}
modules=()
IFS=',' read -r -a selected <<< "$CONTRIB_MODULES"
for module in "${selected[@]}"; do
  case ",$allowed," in
    *",$module,"*) modules+=("farm_$module") ;;
    *) echo "Unsupported contrib module: $module" >&2; exit 1 ;;
  esac
done
export COMPOSER_CACHE_PATH=${COMPOSER_CACHE_PATH:-$root/artifacts/contrib/composer-cache}
mkdir -p "$COMPOSER_CACHE_PATH"
COMPOSER_CACHE_PATH=$(cd "$COMPOSER_CACHE_PATH" && pwd)
artifact_root=${TEST_ARTIFACTS:-$root/artifacts/contrib}
mkdir -p "$artifact_root"
artifact_root=$(cd "$artifact_root" && pwd)
export TEST_ARTIFACTS
TEST_ARTIFACTS=$(mktemp -d "$artifact_root/run-XXXXXXXX")
temporary_project=''
if [ -z "${FARMOS_PROJECT_PATH:-}" ]; then
  temporary_project=$(mktemp -d "$artifact_root/project-XXXXXXXX")
  export FARMOS_PROJECT_PATH=$temporary_project
else
  mkdir -p "$FARMOS_PROJECT_PATH"
  export FARMOS_PROJECT_PATH
  FARMOS_PROJECT_PATH=$(cd "$FARMOS_PROJECT_PATH" && pwd)
fi
project="farmos-contrib-$(basename "$TEST_ARTIFACTS" | tr '[:upper:]' '[:lower:]')-$$"
compose=(docker compose --env-file /dev/null -p "$project" -f "$root/compose.yaml" -f "$root/compose.contrib.yaml")
cleanup() {
  status=$?
  trap - EXIT
  "${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/compose.log" 2>&1 || true
  "${compose[@]}" ps --all >"$TEST_ARTIFACTS/containers.txt" 2>&1 || true
  "${compose[@]}" --profile test down --volumes --remove-orphans >"$TEST_ARTIFACTS/cleanup.log" 2>&1 || {
    cat "$TEST_ARTIFACTS/cleanup.log" >&2
    status=1
  }
  if [ -n "$temporary_project" ]; then
    rm -rf -- "$temporary_project"
  fi
  printf 'Contrib test artifacts: %s\n' "$TEST_ARTIFACTS"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
bash "$root/scripts/contrib-prepare.sh" 2>&1 | tee "$TEST_ARTIFACTS/composer-install.log"
cp "$FARMOS_PROJECT_PATH/composer.json" "$FARMOS_PROJECT_PATH/composer.lock" "$TEST_ARTIFACTS/"
"${compose[@]}" --profile test config >"$TEST_ARTIFACTS/compose.yaml"
docker image inspect "${RUNTIME_IMAGE:-ghcr.io/wotnak/farmos:4-runtime}" >"$TEST_ARTIFACTS/image.json"
mkdir -p "$root/node_modules"
"${compose[@]}" run --rm --no-deps playwright npm ci --ignore-scripts --no-audit --no-fund \
  2>&1 | tee "$TEST_ARTIFACTS/dependencies.log"
"${compose[@]}" run --rm --no-deps contrib-storage
"${compose[@]}" up -d --wait --wait-timeout 120 farmos
drush=("${compose[@]}" exec -T farmos /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php --uri=http://farmos:8080)
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=install playwright
"${drush[@]}" en -y "${modules[@]}" 2>&1 | tee "$TEST_ARTIFACTS/modules-install.log"
"${drush[@]}" pm:list --status=enabled --format=json >"$TEST_ARTIFACTS/enabled-modules.json"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=contrib playwright
"${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/before-recreation.log"
"${compose[@]}" down
"${compose[@]}" up -d --wait --wait-timeout 120 farmos
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=contrib-persistence playwright
"${drush[@]}" cron 2>&1 | tee "$TEST_ARTIFACTS/cron.log"
printf 'Contrib acceptance tests passed.\n'
