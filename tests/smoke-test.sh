#!/bin/sh
set -eu

image=${IMAGE:-ghcr.io/wotnak/farmos:4}
name=farmos-nix-smoke-$$

cleanup() {
    docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker run -d --network none --name "$name" \
    -e FARMOS_DB_PASS=unused-smoke-test-password \
    "$image" >/dev/null

attempt=0
while [ "$attempt" -lt 30 ]; do
    if docker exec "$name" /bin/wget -q -O - http://127.0.0.1:8080/healthz | grep -Fx ok >/dev/null; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done

if [ "$attempt" -eq 30 ]; then
    docker logs "$name"
    exit 1
fi

docker exec "$name" frankenphp php-cli /usr/share/farmos/check-runtime.php
docker exec "$name" frankenphp php-cli /opt/farmos/vendor/drush/drush/drush.php --version

# Both variants use preconfigured settings here. Application pages need a
# database, covered by the database and Compose E2E suites.
docker exec "$name" php -r '
    $path = "/opt/farmos/private_files/hash_salt";
    $salt = file_get_contents($path);
    exit(strlen($salt) === 64 && (fileperms($path) & 0777) === 0600 ? 0 : 1);
'
docker exec "$name" frankenphp version
docker exec "$name" /bin/sh -c 'pidof frankenphp >/dev/null'
docker exec "$name" /bin/sh -c '! command -v nginx >/dev/null'
docker exec "$name" /bin/sh -c '! command -v php-fpm >/dev/null'
test "$(docker inspect --format '{{.Config.User}}' "$name")" = 65532:65532

if [ "${DEV:-0}" = 1 ]; then
    docker exec "$name" test ! -e /usr/bin/php-zts
    docker exec "$name" composer --version
    docker exec "$name" git --version
    docker exec -i -e XDEBUG_MODE=off "$name" /bin/sh -e <<'SH'
    project=$(mktemp -d /tmp/composer-test-XXXXXX)
    trap 'rm -rf "$project"' EXIT
    cd "$project"
    test -x "$(git --exec-path)/git-remote-https"
    mkdir dependency
    cat > dependency/composer.json <<'JSON'
{"name":"fixture/source-test","description":"Local Git dependency for image checks","license":"MIT"}
JSON
    printf GIT_DEPENDENCY_OK > dependency/marker.txt
    git -C dependency init --quiet
    git -C dependency add .
    git -C dependency -c user.name=Fixture -c user.email=fixture@example.test \
        -c commit.gpgsign=false commit --quiet -m 'Fixture package'
    git -C dependency tag v1.0.0
    cat > composer.json <<'JSON'
{"name":"fixture/composer-test","version":"1.0.0","require":{"fixture/source-test":"1.0.0"},"repositories":[{"type":"vcs","url":"./dependency"},{"packagist.org":false}],"scripts":{"post-install-cmd":"@php composer-script.php"}}
JSON
    cat > composer-script.php <<'PHP'
<?php
require __DIR__ . '/vendor/autoload.php';
if (!extension_loaded('geos')) {
    throw new RuntimeException('Composer scripts must use the farmOS PHP runtime');
}
file_put_contents(__DIR__ . '/script-result', 'COMPOSER_SCRIPT_OK');
PHP
    composer update --no-install --no-scripts --no-audit --no-interaction --no-progress
    composer install --prefer-source --no-interaction --no-progress
    test -f composer.lock
    test "$(cat script-result)" = COMPOSER_SCRIPT_OK
    test "$(cat vendor/fixture/source-test/marker.txt)" = GIT_DEPENDENCY_OK
    git -C vendor/fixture/source-test rev-parse --verify HEAD
SH
    docker exec "$name" vendor/bin/phpunit --version
    docker exec "$name" vendor/bin/phpstan --version
    docker exec "$name" vendor/bin/phpcs --version
    docker exec "$name" /bin/sh -c 'cd /tmp && /opt/farmos/vendor/bin/rector --version'
    docker exec "$name" php -r \
        'exit(PHP_BINARY !== "" && extension_loaded("xdebug") && extension_loaded("posix") && posix_geteuid() === 65532 ? 0 : 1);'
    docker exec "$name" frankenphp php-cli -r \
        'exit(extension_loaded("geos") && extension_loaded("xdebug") && extension_loaded("posix") && posix_geteuid() === 65532 ? 0 : 1);'
else
    docker exec "$name" /bin/sh -ec '
        for tool in composer git; do
            if command -v "$tool"; then exit 1; fi
        done
        test ! -e /usr/share/composer/composer.phar
    '
    docker exec "$name" test ! -e /opt/farmos/vendor/phpunit/phpunit
    docker exec "$name" test ! -e /opt/farmos/vendor/phpstan/phpstan
    docker exec "$name" frankenphp php-cli -r '
        require "/opt/farmos/vendor/autoload.php";
        $manifest = json_decode(file_get_contents("/opt/farmos/composer.json"), true, 512, JSON_THROW_ON_ERROR);
        $installed = Composer\InstalledVersions::getPrettyVersion("farmos/farmos");
        if ($installed !== $manifest["require"]["farmos/farmos"]) {
            fwrite(STDERR, "Production farmOS must match its exact Composer constraint.\n");
            exit(1);
        }
        exit(Composer\InstalledVersions::getRootPackage()["dev"] ? 1 : 0);
    '
fi
