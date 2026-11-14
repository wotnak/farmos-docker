#!/usr/bin/env bash
# Run contributed-module phases in the disposable stack created by Task.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${TEST_COMPOSE_PROJECT:?Run this phase through Task}"
: "${TEST_COMPOSE_FILE:?Task must supply the shared Compose file}"
: "${TEST_ARTIFACTS:?Task must supply the artifact directory}"
: "${TEST_SUITE:?Task must select the Compose profile}"
: "${TEST_SERVICE:?Task must select the application service}"
: "${BASE_URL:?Task must supply the application URL}"
: "${FARMOS_PROJECT_PATH:?Task must prepare the contributed-module project}"
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
compose=(docker compose --env-file /dev/null -p "$TEST_COMPOSE_PROJECT" -f "$TEST_COMPOSE_FILE" --profile "$TEST_SUITE")
cp "$FARMOS_PROJECT_PATH/composer.json" "$FARMOS_PROJECT_PATH/composer.lock" "$TEST_ARTIFACTS/"
mkdir -p "$root/node_modules"
"${compose[@]}" run --rm --no-deps playwright npm ci --ignore-scripts --no-audit --no-fund \
  2>&1 | tee "$TEST_ARTIFACTS/dependencies.log"
drush=("${compose[@]}" exec -T "$TEST_SERVICE" /usr/bin/php /opt/farmos/vendor/drush/drush/drush.php "--uri=$BASE_URL")
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=install playwright
"${drush[@]}" en -y "${modules[@]}" 2>&1 | tee "$TEST_ARTIFACTS/modules-install.log"
"${drush[@]}" pm:list --status=enabled --format=json >"$TEST_ARTIFACTS/enabled-modules.json"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=contrib playwright
"${compose[@]}" logs --no-color >"$TEST_ARTIFACTS/before-recreation.log"
"${compose[@]}" down
"${compose[@]}" up -d --wait --wait-timeout 120 "$TEST_SERVICE"
"${compose[@]}" run --rm --no-deps -e TEST_PHASE=contrib-persistence playwright
"${drush[@]}" cron 2>&1 | tee "$TEST_ARTIFACTS/cron.log"
printf 'Contrib acceptance tests passed.\n'
