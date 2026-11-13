#!/usr/bin/env bash
# Resolve the test codebase with development tools, then serve it read-only.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
export FARMOS_PROJECT_PATH=${FARMOS_PROJECT_PATH:-$root/artifacts/contrib/project}
COMPOSER_CACHE_PATH=${COMPOSER_CACHE_PATH:-$root/artifacts/contrib/composer-cache}
mkdir -p "$FARMOS_PROJECT_PATH" "$COMPOSER_CACHE_PATH"
FARMOS_PROJECT_PATH=$(cd "$FARMOS_PROJECT_PATH" && pwd)
COMPOSER_CACHE_PATH=$(cd "$COMPOSER_CACHE_PATH" && pwd)
# mktemp uses 0700; the runtime UID differs from the builder UID on Linux.
chmod 0755 "$FARMOS_PROJECT_PATH"
cp "$root/fixtures/contrib/composer.json" "$FARMOS_PROJECT_PATH/"
docker run --rm --user "$(id -u):$(id -g)" --entrypoint composer \
  -e COMPOSER_HOME=/tmp/composer -e COMPOSER_CACHE_DIR=/cache \
  -v "$FARMOS_PROJECT_PATH:/opt/farmos" \
  -v "$COMPOSER_CACHE_PATH:/cache" \
  "${DEV_RUNTIME_IMAGE:-ghcr.io/wotnak/farmos:4-dev-runtime}" \
  update --no-audit --no-dev --prefer-dist --no-interaction --no-progress
mkdir -p "$FARMOS_PROJECT_PATH/web/sites/default/files" "$FARMOS_PROJECT_PATH/private_files" "$FARMOS_PROJECT_PATH/config/sync"
cp "$root/fixtures/contrib/settings.php" "$FARMOS_PROJECT_PATH/web/sites/default/settings.php"
cp "$FARMOS_PROJECT_PATH/web/sites/default/default.services.yml" "$FARMOS_PROJECT_PATH/web/sites/default/services.yml"
printf 'Require all denied\n' > "$FARMOS_PROJECT_PATH/config/sync/.htaccess"
# Named data volumes are initialized from these directories in the mounted project.
chmod 0755 "$FARMOS_PROJECT_PATH/web/sites/default/files" "$FARMOS_PROJECT_PATH/private_files"
printf 'Prepared contrib project: %s\n' "$FARMOS_PROJECT_PATH"
