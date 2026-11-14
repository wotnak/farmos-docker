#!/usr/bin/env bash
# Resolve the test codebase with development tools, then serve it read-only.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
: "${TEST_COMPOSE_PROJECT:?Run this phase through Task}"
: "${TEST_COMPOSE_FILE:?Task must supply the shared Compose file}"
: "${TEST_ARTIFACTS:?Task must supply the artifact directory}"
: "${TEST_SUITE:?Task must select the Compose profile}"
: "${FARMOS_PROJECT_PATH:?Task must supply the contributed-module project directory}"
: "${COMPOSER_CACHE_PATH:?Task must supply the Composer cache directory}"
compose=(docker compose --env-file /dev/null -p "$TEST_COMPOSE_PROJECT" -f "$TEST_COMPOSE_FILE" --profile "$TEST_SUITE")
mkdir -p "$FARMOS_PROJECT_PATH" "$COMPOSER_CACHE_PATH"
export FARMOS_PROJECT_PATH
FARMOS_PROJECT_PATH=$(cd "$FARMOS_PROJECT_PATH" && pwd)
export COMPOSER_CACHE_PATH
COMPOSER_CACHE_PATH=$(cd "$COMPOSER_CACHE_PATH" && pwd)
# mktemp uses 0700; the runtime UID differs from the builder UID on Linux.
chmod 0755 "$FARMOS_PROJECT_PATH"
cp "$root/fixtures/contrib/composer.json" "$FARMOS_PROJECT_PATH/"
"${compose[@]}" run --rm --no-deps contrib-prepare \
  update --no-audit --no-dev --prefer-dist --no-interaction --no-progress
mkdir -p "$FARMOS_PROJECT_PATH/web/sites/default/files" "$FARMOS_PROJECT_PATH/private_files" "$FARMOS_PROJECT_PATH/config/sync"
cp "$root/fixtures/contrib/settings.php" "$FARMOS_PROJECT_PATH/web/sites/default/settings.php"
cp "$FARMOS_PROJECT_PATH/web/sites/default/default.services.yml" "$FARMOS_PROJECT_PATH/web/sites/default/services.yml"
printf 'Require all denied\n' > "$FARMOS_PROJECT_PATH/config/sync/.htaccess"
# Named data volumes are initialized from these directories in the mounted project.
chmod 0755 "$FARMOS_PROJECT_PATH/web/sites/default/files" "$FARMOS_PROJECT_PATH/private_files"
printf 'Prepared contrib project: %s\n' "$FARMOS_PROJECT_PATH"
