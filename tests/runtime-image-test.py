#!/usr/bin/env python3
"""Check a runtime image with disposable apps and Task's shared PostgreSQL."""

import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
import uuid


DEV = os.environ.get("DEV", "0") == "1"
IMAGE = os.environ.get("IMAGE", "ghcr.io/wotnak/farmos:4-dev-runtime" if DEV else "ghcr.io/wotnak/farmos:4-runtime")
DOCKER = shutil.which("docker")


def run(*args, check=True, timeout=60, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, check=check,
                          timeout=timeout, **kwargs)


class RuntimeImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if DOCKER is None:
            raise RuntimeError("Docker is required to test the runtime image")
        result = run(DOCKER, "image", "inspect", IMAGE, check=False)
        if result.returncode:
            raise RuntimeError(f"Build and load {IMAGE} before running this test:\n{result.stderr}")
        cls.config = json.loads(result.stdout)[0]["Config"]

    def container_args(self):
        name = "farmos-runtime-test-" + uuid.uuid4().hex[:10]
        self.addCleanup(run, DOCKER, "rm", "-fv", name, check=False)
        return [DOCKER, "run", "--name", name,
                "--read-only", "--tmpfs", "/run", "--tmpfs", "/tmp",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true"], name

    def project(self, *, vendor=True):
        temporary = tempfile.TemporaryDirectory(prefix="farmos-runtime-project-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        # The container user must be able to read host-created fixtures. These
        # permissions apply only to the disposable project, never user code.
        root.chmod(0o755)
        sites = root / "web/sites/default"
        sites.mkdir(parents=True)
        (sites / "settings.php").write_text("<?php // Existing project settings.\n")
        (root / "composer.json").write_text('{"name":"fixture/runtime-test"}\n')
        (root / "web/index.php").write_text(
            '<?php require __DIR__ . "/../vendor/autoload.php"; '
            'echo "RUNTIME_APP_OK";\n')
        if vendor:
            (root / "vendor").mkdir()
            (root / "vendor/autoload.php").write_text("<?php return true;\n")
        # Drupal commonly protects settings.php and its parent after install.
        # Startup must work without trying to chmod or initialize this tree.
        (sites / "settings.php").chmod(0o444)
        sites.chmod(0o555)
        return root

    def test_no_bundled_application(self):
        self.assertEqual(self.config["User"], "65532:65532")
        self.assertEqual(self.config["WorkingDir"], "/opt/farmos")
        args, _ = self.container_args()
        result = run(*args, "--rm", IMAGE, "/bin/sh", "-ec", '''
            test "$(id -u)" = 65532
            test ! -e /opt/farmos/web
            test ! -e /opt/farmos/vendor
            test ! -e /usr/share/farmos/sites
            test ! -e /opt/farmos/composer.json
        ''', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_database_support_does_not_ship_extra_clients_or_servers(self):
        args, _ = self.container_args()
        result = run(*args, "--rm", IMAGE, "/bin/sh", "-ec", '''
            for binary in /nix/store/*/bin/mysql /nix/store/*/bin/mariadb \\
                /nix/store/*/bin/mysqld /nix/store/*/bin/sqlite3 \\
                /nix/store/*/bin/postgres /nix/store/*/bin/initdb; do
                if [ -e "$binary" ]; then
                    echo "Unexpected database executable: $binary" >&2
                    exit 1
                fi
            done
            php -r 'exit(extension_loaded("pdo_mysql") || extension_loaded("mysqli")
                || extension_loaded("mysqlnd") ? 1 : 0);'
        ''', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_php_commands(self):
        for command in (["php", "/usr/share/farmos/check-runtime.php"],
                        ["frankenphp", "php-cli", "/usr/share/farmos/check-runtime.php"]):
            with self.subTest(command=command):
                args, _ = self.container_args()
                result = run(*args, "--rm", IMAGE, *command, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if DEV:
            for command in (["php"], ["frankenphp", "php-cli"]):
                with self.subTest(development_php=command):
                    args, _ = self.container_args()
                    result = run(*args, "--rm", "-e", "XDEBUG_MODE=off", IMAGE,
                                 *command, "-r", '''
                        exit(extension_loaded("xdebug") && extension_loaded("posix")
                            && posix_geteuid() === 65532 ? 0 : 1);
                    ''', check=False)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cron_waits_and_retries_after_failure(self):
        root = self.project()
        drush = root / "vendor/drush/drush"
        drush.mkdir(parents=True)
        (drush / "drush.php").write_text('''<?php
$path = '/tmp/cron-runs';
$attempt = file_exists($path) ? count(file($path)) + 1 : 1;
file_put_contents($path, json_encode([
    'time' => microtime(true), 'command' => $argv[1],
    'attempt' => $attempt,
]) . "\\n", FILE_APPEND);
exit($attempt === 1 ? 1 : 0);
''')
        args, name = self.container_args()
        run(*args, "-d", "--entrypoint", "/bin/sh", "-e", "FARMOS_CRON_INTERVAL=1",
            "--mount", f"type=bind,source={root},target=/opt/farmos,readonly", IMAGE, "-ec", '''
            php -r 'file_put_contents("/tmp/cron-start", (string) microtime(true));'
            exec /usr/bin/farmos-cron
        ''')
        rows = []
        for _ in range(40):
            result = run(DOCKER, "exec", name, "cat", "/tmp/cron-runs", check=False)
            if result.returncode == 0:
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                if len(rows) >= 2:
                    break
            time.sleep(0.2)
        self.assertGreaterEqual(len(rows), 2, run(DOCKER, "logs", name).stderr)
        start = float(run(DOCKER, "exec", name, "cat", "/tmp/cron-start").stdout)
        self.assertGreaterEqual(rows[0]["time"] - start, 0.8)
        self.assertGreaterEqual(rows[1]["time"] - rows[0]["time"], 0.8)
        self.assertEqual([row["command"] for row in rows[:2]], ["cron", "cron"])
        self.assertEqual([row["attempt"] for row in rows[:2]], [1, 2])

    def test_tooling_matches_variant(self):
        args, _ = self.container_args()
        script = '''
            for tool in composer git psql; do
                if command -v "$tool"; then exit 1; fi
            done
            test ! -e /usr/share/composer/composer.phar
            php -r '
                exit(!extension_loaded("xdebug") ? 0 : 1);
            '
        '''
        if DEV:
            script = '''
                # Dump/restore exercises the other client commands below.
                for command in pg_isready createuser dropuser pgbench; do
                    "$command" --version
                done
                # Check the store as well as PATH: hiding a symlink would
                # still leave these executables and dependencies in the image.
                for binary in /nix/store/*/bin/php-fpm /nix/store/*/sbin/php-fpm \\
                    /nix/store/*/bin/php-cgi /nix/store/*/bin/phpdbg \\
                    /nix/store/*/bin/pear /nix/store/*/bin/pecl; do
                    if [ -e "$binary" ]; then
                        echo "Unexpected runtime executable: $binary" >&2
                        exit 1
                    fi
                done
                test -x "$(git --exec-path)/git-remote-https"
            '''
        result = run(*args, "--rm", "-e", "XDEBUG_MODE=off", IMAGE,
                     "/bin/sh", "-ec", script, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(DEV, "PostgreSQL clients are only included in the development runtime")
    def test_postgresql_dump_and_restore(self):
        project = os.environ.get("TEST_COMPOSE_PROJECT")
        if not project:
            raise RuntimeError("Run task test VARIANT=development-runtime SUITE=runtime to start the shared test database")
        compose_file = os.environ.get("TEST_COMPOSE_FILE") or str(Path(__file__).resolve().parent / "compose.yaml")
        compose = [DOCKER, "compose", "--env-file", "/dev/null", "-p", project, "-f", compose_file]
        database = run(*compose, "ps", "-q", "db").stdout.strip()
        if not database:
            raise RuntimeError("The shared test database is not running; run task test VARIANT=development-runtime SUITE=runtime")
        networks = json.loads(run(DOCKER, "inspect", "--format", "{{json .NetworkSettings.Networks}}", database).stdout)
        network = project + "_default"
        if network not in networks:
            raise RuntimeError("The shared test database is not on the Task test network")
        source = "runtime_source_" + uuid.uuid4().hex[:10]
        restored = "runtime_restored_" + uuid.uuid4().hex[:10]
        for name in (source, restored):
            self.addCleanup(run, DOCKER, "exec", database, "dropdb", "--username=farm",
                            "--if-exists", "--force", name, check=False)
        run(DOCKER, "exec", database, "createdb", "--username=farm", source)

        args, _ = self.container_args()
        result = run(*args, "--rm", "--network", network,
                     "--entrypoint", "/bin/sh",
                     "-e", "PGHOST=db", "-e", "PGUSER=farm",
                     "-e", "PGPASSWORD=disposable-password", "-e", f"PGDATABASE={source}",
                     "-e", f"RESTORED_DATABASE={restored}",
                     IMAGE, "-ec", '''
            test "$(psql -Atc 'SHOW password_encryption')" = scram-sha-256
            psql --set ON_ERROR_STOP=1 -c "
                CREATE TABLE fixture (id integer PRIMARY KEY, value text NOT NULL);
                INSERT INTO fixture VALUES (1, 'DUMP_RESTORE_OK');
            "
            pg_dump --format=custom --file=/tmp/source.dump
            createdb "$RESTORED_DATABASE"
            pg_restore --exit-on-error --dbname="$RESTORED_DATABASE" /tmp/source.dump
            test "$(psql --dbname="$RESTORED_DATABASE" -Atc 'SELECT value FROM fixture WHERE id = 1')" = DUMP_RESTORE_OK
            # pg_dumpall must locate the pg_dump shipped beside it after the
            # client package is split from the upstream server package.
            pg_dumpall --no-role-passwords > /tmp/all.sql
            grep DUMP_RESTORE_OK /tmp/all.sql
            dropdb "$RESTORED_DATABASE"
        ''', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(DEV, "Composer is only included in the development runtime")
    def test_composer_installs_git_source_and_runs_php_script(self):
        # A disposable volume provides a writable mounted project for UID 65532
        # on both Linux and Docker Desktop, without changing host permissions.
        volume = "farmos-runtime-composer-" + uuid.uuid4().hex[:10]
        run(DOCKER, "volume", "create", volume)
        self.addCleanup(run, DOCKER, "volume", "rm", volume)
        args, _ = self.container_args()
        result = run(*args, "--rm", "--mount",
                     f"type=volume,source={volume},target=/opt/farmos",
                     "--network", "none", "-e", "XDEBUG_MODE=off",
                     IMAGE, "/bin/sh", "-ec", '''
            chmod u+w .
            mkdir dependency
            cat > dependency/composer.json <<'JSON'
{"name":"fixture/source-test","description":"Local Git dependency for image checks","license":"MIT"}
JSON
            printf GIT_DEPENDENCY_OK > dependency/marker.txt
            git -C dependency init --quiet
            git -C dependency add .
            git -C dependency -c user.name=Fixture -c user.email=fixture@example.test \\
                -c commit.gpgsign=false commit --quiet -m 'Fixture package'
            git -C dependency tag v1.0.0
            cat > composer.json <<'JSON'
{"name":"fixture/runtime-test","version":"1.0.0","require":{"fixture/source-test":"1.0.0"},"repositories":[{"type":"vcs","url":"./dependency"},{"packagist.org":false}],"scripts":{"post-install-cmd":"@php composer-script.php"}}
JSON
            cat > composer-script.php <<'PHP'
<?php
require __DIR__ . '/vendor/autoload.php';
if (!extension_loaded('geos') || !extension_loaded('pdo_pgsql') || !extension_loaded('pdo_sqlite')
    || !extension_loaded('posix') || posix_geteuid() !== 65532
    || PHP_BINARY === '' || str_contains(PHP_BINARY, 'frankenphp')) {
    throw new RuntimeException('Composer scripts must use the native farmOS development PHP runtime');
}
file_put_contents(__DIR__ . '/script-result', 'COMPOSER_SCRIPT_OK');
PHP
            composer update --no-install --no-scripts --no-audit --no-interaction --no-progress
            composer install --prefer-source --no-interaction --no-progress
            test "$(cat script-result)" = COMPOSER_SCRIPT_OK
            test "$(cat vendor/fixture/source-test/marker.txt)" = GIT_DEPENDENCY_OK
            git -C vendor/fixture/source-test rev-parse --verify HEAD
        ''', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_application_fails_clearly(self):
        args, _ = self.container_args()
        result = run(*args, "--rm", IMAGE, check=False)
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("web/index.php", output)
        self.assertRegex(output.lower(), r"mount|copy|provide|supply")

    def test_missing_vendor_fails_clearly(self):
        root = self.project(vendor=False)
        args, _ = self.container_args()
        result = run(*args, "--rm", "--mount",
                     f"type=bind,source={root},target=/opt/farmos,readonly",
                     IMAGE, check=False)
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        self.assertIn("vendor/autoload.php", output)
        self.assertIn("composer install", output.lower())

    def serve_project(self, root, *options):
        args, name = self.container_args()
        result = run(*args, "-d", "--mount",
                     f"type=bind,source={root},target=/opt/farmos,readonly",
                     *options, IMAGE, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = run(DOCKER, "exec", name, "wget", "-q", "-O", "-",
                           "http://127.0.0.1:8080/healthz", check=False)
            if response.returncode == 0:
                self.assertEqual(response.stdout, "ok")
                break
            status = run(DOCKER, "inspect", "--format", "{{.State.Running}}", name)
            if status.stdout.strip() != "true":
                break
            time.sleep(0.5)
        else:
            response = None
        if response is None or response.returncode:
            logs = run(DOCKER, "logs", name, check=False)
            self.fail("Runtime did not become ready:\n" + logs.stdout + logs.stderr)
        return name

    def test_read_only_project_serves_php(self):
        root = self.project()
        name = self.serve_project(root)
        response = run(DOCKER, "exec", name, "wget", "-q", "-O", "-",
                       "http://127.0.0.1:8080/")
        self.assertEqual(response.stdout, "RUNTIME_APP_OK")
        response = run(DOCKER, "exec", name, "wget", "-q", "-O", "-",
                       "http://127.0.0.1:8080/virtual/template")
        self.assertEqual(response.stdout, "RUNTIME_APP_OK",
                         "Virtual routes named template must reach the PHP front controller")
        self.assertEqual(sorted(path.name for path in (root / "web/sites/default").iterdir()),
                         ["settings.php"], "Startup must not initialize the user's sites tree")

    def test_http_warnings_are_logged_and_display_matches_variant(self):
        root = self.project()
        warning = "RUNTIME_WARNING_" + uuid.uuid4().hex
        (root / "web/warning.php").write_text(
            "<?php\n"
            f"trigger_error('{warning}', E_USER_WARNING);\n"
            "echo 'APPLICATION_RESPONSE';\n")
        name = self.serve_project(root)
        response = run(DOCKER, "exec", name, "wget", "-q", "-O", "-",
                       "http://127.0.0.1:8080/warning.php")
        if DEV:
            self.assertIn(warning, response.stdout,
                          "Development images should display PHP diagnostics")
            self.assertIn("APPLICATION_RESPONSE", response.stdout)
        else:
            self.assertEqual(response.stdout, "APPLICATION_RESPONSE",
                             "Production responses must not expose PHP warnings or paths")
        deadline = time.monotonic() + 5
        while True:
            logs = run(DOCKER, "logs", name)
            if warning in logs.stdout + logs.stderr or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        self.assertIn(warning, logs.stdout + logs.stderr,
                      "PHP warnings must remain available in container logs")

    def test_invalid_server_environment_fails_before_listening(self):
        root = self.project()
        cases = [
            ("FARMOS_DOMAIN=https://farmos.test", "FARMOS_DOMAIN"),
            ("FARMOS_DOMAIN=farmos.test/path", "FARMOS_DOMAIN"),
            ("FARMOS_DOMAIN=farmos.test:8443", "FARMOS_DOMAIN"),
            ("FARMOS_DOMAIN=farmos.test {\nrespond injected\n}", "FARMOS_DOMAIN"),
            ("FARMOS_AUTO_HTTPS=yes", "FARMOS_AUTO_HTTPS"),
            ("FARMOS_AUTO_HTTPS=true", "FARMOS_DOMAIN"),
            ("FARMOS_TRUSTED_HOSTS=.*", "FARMOS_TRUSTED_HOSTS"),
            ("FARMOS_TRUSTED_PROXIES=0.0.0.0/0", "FARMOS_TRUSTED_PROXIES"),
            ("FARMOS_TRUSTED_PROXIES=::/0", "FARMOS_TRUSTED_PROXIES"),
        ]
        for environment, error in cases:
            with self.subTest(environment=environment):
                args, _ = self.container_args()
                result = run(*args, "--rm", "--mount",
                             f"type=bind,source={root},target=/opt/farmos,readonly",
                             "-e", environment, IMAGE, check=False, timeout=10)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn(error, output)
                self.assertNotIn("FrankenPHP started", output)
                self.assertNotIn("server running", output)

    def test_automatic_https_redirect_and_certificate_persistence(self):
        root = self.project()
        (root / "private_files").mkdir()
        config_source = (Path(__file__).resolve().parents[1]
                         / "packages/drupal-runtime/config/Caddyfile.https")
        config = config_source.read_text()
        args, _ = self.container_args()
        packaged = run(*args, "--rm", IMAGE, "cat", "/etc/frankenphp/Caddyfile.https")
        self.assertEqual(packaged.stdout, config,
                         "The test override must match the packaged HTTPS configuration")
        # Exercise automatic certificate management without contacting a public
        # ACME service. The internal CA exists only in this mounted test config.
        domain_block = "{$FARMOS_DOMAIN} {"
        self.assertEqual(config.count(domain_block), 1)
        config_path = root / "Caddyfile.https"
        config_path.write_text(config.replace(domain_block,
                                             domain_block + "\n\ttls internal"))
        volume = "farmos-runtime-tls-" + uuid.uuid4().hex[:10]
        run(DOCKER, "volume", "create", volume)
        self.addCleanup(run, DOCKER, "volume", "rm", volume)

        def request_http(port, path):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                connection.request("GET", path, headers={"Host": "farmos.test"})
                response = connection.getresponse()
                return response.status, response.getheader("Location"), response.read()
            finally:
                connection.close()

        ca_path = "/opt/farmos/private_files/caddy/data/caddy/pki/authorities/local"
        persisted = None
        for generation in range(2):
            with self.subTest(generation=generation):
                name = self.serve_project(
                    root, "-e", "FARMOS_DOMAIN=farmos.test", "-e", "FARMOS_AUTO_HTTPS=true",
                    "--mount", f"type=volume,source={volume},target=/opt/farmos/private_files",
                    "--mount", f"type=bind,source={config_path},target=/etc/frankenphp/Caddyfile.https,readonly",
                    "-p", "127.0.0.1::8080", "-p", "127.0.0.1::8443")
                ports = json.loads(run(DOCKER, "inspect", "--format",
                                       "{{json .NetworkSettings.Ports}}", name).stdout)
                http_port = int(ports["8080/tcp"][0]["HostPort"])
                https_port = int(ports["8443/tcp"][0]["HostPort"])
                self.assertEqual(request_http(http_port, "/healthz"), (200, None, b"ok"))
                status, location, _ = request_http(http_port, "/example?value=1")
                self.assertIn(status, (301, 308))
                self.assertEqual(location, "https://farmos.test/example?value=1")

                deadline = time.monotonic() + 30
                tls_error = "Certificate authority is not ready"
                while time.monotonic() < deadline:
                    ca = run(DOCKER, "exec", name, "cat", ca_path + "/root.crt", check=False)
                    if ca.returncode == 0:
                        context = ssl.create_default_context(cadata=ca.stdout)
                        try:
                            with socket.create_connection(("127.0.0.1", https_port), timeout=5) as tcp:
                                with context.wrap_socket(tcp, server_hostname="farmos.test") as tls:
                                    certificate = tls.getpeercert(binary_form=True)
                                    tls.sendall(b"GET / HTTP/1.1\r\nHost: farmos.test\r\nConnection: close\r\n\r\n")
                                    response = http.client.HTTPResponse(tls)
                                    response.begin()
                                    self.assertEqual(response.status, 200)
                                    self.assertEqual(response.read(), b"RUNTIME_APP_OK")
                                    break
                        except (OSError, ssl.SSLError) as error:
                            # The HTTP listener can precede certificate issuance.
                            tls_error = str(error)
                    time.sleep(0.25)
                else:
                    logs = run(DOCKER, "logs", name, check=False)
                    self.fail("Automatic TLS did not become ready: " + tls_error
                              + "\n" + logs.stdout + logs.stderr)

                ca_key_hash = run(DOCKER, "exec", name, "sha256sum", ca_path + "/root.key").stdout.split()[0]
                current = (ca.stdout, ca_key_hash, certificate)
                if persisted is not None:
                    self.assertEqual(current, persisted,
                                     "The certificate and private CA must survive container recreation")
                persisted = current
                run(DOCKER, "stop", "--time", "5", name)
                run(DOCKER, "rm", "-v", name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
