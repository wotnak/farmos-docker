#!/usr/bin/env python3
"""Test shipped settings and PostgreSQL and SQLite in disposable containers.

Requires Docker and a bundled farmOS image with pdo_pgsql and pdo_sqlite.
DB_TEST_IMAGE selects the image; config-only checks can run as SettingsTests.
"""

import json
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import time
import unittest
import uuid


IMAGE = os.environ.get("DB_TEST_IMAGE", "ghcr.io/wotnak/farmos:4")
SALT = "disposable-stable-salt-at-least-32-characters"
LOAD = r'''
$app_root = '/opt/farmos/web';
$site_path = 'sites/default';
$loader = require '/opt/farmos/vendor/autoload.php';
require '/opt/farmos/web/sites/default/settings.php';
$options = $databases['default']['default'];
'''
CONNECT = LOAD + r'''
$loader->addPsr4($options['namespace'] . '\\', $app_root . '/' . $options['autoload']);
\Drupal\Core\Database\Database::addConnectionInfo('default', 'default', $options);
$database = \Drupal\Core\Database\Database::getConnection();
'''


def run(*args, timeout=120, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, **kwargs)


class ContainerTest(unittest.TestCase):
    def php(self, script="", *, network="none", volume=None, startup=False,
            command=None, timeout=120, **environment):
        args = ["docker", "run", "--rm", "--read-only", "--network", network,
                "--tmpfs", "/tmp:mode=1777", "--tmpfs", "/run:mode=1777",
                "--tmpfs", "/opt/farmos/web/sites/default/files:mode=1777"]
        if volume:
            args += ["--mount", f"type=volume,source={volume},target=/opt/farmos/private_files"]
        else:
            args += ["--tmpfs", "/opt/farmos/private_files:mode=1777"]
        settings = dict(FARMOS_HASH_SALT=SALT, FARMOS_DB_PASS="disposable-password",
                        FARMOS_DOMAIN="localhost", XDEBUG_MODE="off") | environment
        for key, value in settings.items():
            if value is not None:
                args += ["-e", f"{key}={value}"]
        command = command or ["-r", script]
        if startup:
            args += ["--entrypoint", "/bin/sh", IMAGE, "/usr/share/farmos/farmos-init", "/usr/bin/php", *command]
        else:
            args += ["--entrypoint", "/usr/bin/php", IMAGE, *command]
        return run(*args, timeout=timeout)

    def config(self, **environment):
        result = self.php(LOAD + "echo json_encode($options, JSON_THROW_ON_ERROR);", **environment)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return json.loads(result.stdout)


class SettingsTests(ContainerTest):
    def test_default_postgresql_and_custom_server(self):
        options = self.config()
        self.assertEqual(options["driver"], "pgsql")
        self.assertEqual(options["database"], "farmos")
        self.assertEqual(options["port"], "5432")
        self.assertEqual(options["host"], "db")
        options = self.config(FARMOS_DB_DRIVER="pgsql", FARMOS_DB_HOST="external-db",
                              FARMOS_DB_PORT="5544", FARMOS_DB_NAME="custom_db",
                              FARMOS_DB_USER="custom_user", FARMOS_DB_PASS="0")
        self.assertEqual(options["host"], "external-db")
        self.assertEqual(options["port"], "5544")
        self.assertEqual(options["database"], "custom_db")
        self.assertEqual(options["username"], "custom_user")
        self.assertEqual(options["password"], "0")

    def test_sqlite_uses_private_file_without_server_credentials(self):
        options = self.config(FARMOS_DB_DRIVER="sqlite", FARMOS_DB_PASS="",
                              FARMOS_DB_HOST="ignored", FARMOS_DB_PORT="ignored")
        self.assertEqual(options["database"], "/opt/farmos/private_files/database/farmos.sqlite")
        self.assertFalse({"host", "port", "username", "password"} & options.keys())

    def test_unsupported_drivers_fail_in_settings_and_startup(self):
        for driver in ("mysql", "mariadb", "postgresql", "unknown"):
            for startup in (False, True):
                with self.subTest(driver=driver, startup=startup):
                    result = self.php(LOAD, startup=startup, FARMOS_DB_DRIVER=driver)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Unsupported FARMOS_DB_DRIVER. Supported drivers: pgsql, sqlite.",
                                  result.stderr + result.stdout)
                    self.assertNotIn("disposable-password", result.stderr + result.stdout)

    def test_invalid_configuration_fails_without_exposing_password(self):
        for environment, message in [
            ({"FARMOS_DB_PORT": "65536"}, "FARMOS_DB_PORT"),
            ({"FARMOS_DB_PORT": "5432;bad"}, "FARMOS_DB_PORT"),
            ({"FARMOS_DB_DRIVER": "sqlite", "FARMOS_DB_NAME": "relative.sqlite"}, "absolute"),
            ({"FARMOS_DB_PASS": ""}, "FARMOS_DB_PASS"),
            ({"FARMOS_HASH_SALT": "short"}, "FARMOS_HASH_SALT"),
        ]:
            with self.subTest(environment=environment):
                result = self.php(LOAD, **environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr + result.stdout)
                self.assertNotIn("disposable-password", result.stderr + result.stdout)

    def test_startup_rejects_missing_postgresql_password(self):
        result = self.php("echo 'UNEXPECTED';", startup=True, FARMOS_DB_PASS="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FARMOS_DB_PASS", result.stderr + result.stdout)
        self.assertNotIn("UNEXPECTED", result.stdout)

    def test_private_file_tree_is_separate_from_oauth_keys(self):
        result = self.php(LOAD + r'''
$directory = $settings['file_private_path'];
file_put_contents($directory . '/report.csv', 'GENERATED_REPORT');
echo json_encode([$directory, file_get_contents($directory . '/report.csv'),
                  $config['simple_oauth.settings']['private_key']]);
''', startup=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout), [
            '/opt/farmos/private_files/files', 'GENERATED_REPORT',
            '/opt/farmos/private_files/keys/private.key',
        ])

    def test_default_template_uses_the_same_private_paths(self):
        result = self.php(r'''
$app_root = '/opt/farmos/web';
$site_path = 'sites/default';
require '/opt/farmos/web/sites/default/default.settings.php';
echo json_encode([$settings['file_private_path'],
                  $config['simple_oauth.settings']['public_key'],
                  $config['simple_oauth.settings']['private_key']]);
''')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout), [
            '/opt/farmos/private_files/files',
            '/opt/farmos/private_files/keys/public.key',
            '/opt/farmos/private_files/keys/private.key',
        ])


class SaltTests(ContainerTest):
    def volume(self):
        volume = "farmos-settings-test-" + uuid.uuid4().hex[:10]
        self.addCleanup(run, "docker", "volume", "rm", "-f", volume)
        result = run("docker", "run", "--rm", "--user", "0:0", "--entrypoint", "/bin/sh",
                     "--mount", f"type=volume,source={volume},target=/data", IMAGE,
                     "-ec", "chown 65532:65532 /data")
        self.assertEqual(result.returncode, 0, result.stderr)
        return volume


    def salt(self, volume, **environment):
        result = self.php(LOAD + "echo $settings['hash_salt'];", volume=volume, **environment)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_generated_salt_persists_with_restrictive_permissions(self):
        volume = self.volume()
        generated = self.salt(volume, FARMOS_HASH_SALT=None)
        self.assertRegex(generated, r"^[a-f0-9]{64}$")
        self.assertEqual(self.salt(volume, FARMOS_HASH_SALT="", startup=True), generated)
        result = self.php("echo decoct(fileperms('/opt/farmos/private_files/hash_salt') & 0777);",
                          volume=volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "600")

    def test_override_takes_precedence_without_changing_saved_salt(self):
        volume = self.volume()
        self.assertEqual(self.salt(volume), SALT)
        result = self.php("exit(file_exists('/opt/farmos/private_files/hash_salt') ? 1 : 0);", volume=volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        generated = self.salt(volume, FARMOS_HASH_SALT="")
        self.assertEqual(self.salt(volume), SALT)
        self.assertEqual(self.salt(volume, FARMOS_HASH_SALT=""), generated)

    def test_concurrent_startups_share_one_salt(self):
        volume = self.volume()
        with ThreadPoolExecutor(max_workers=4) as pool:
            salts = list(pool.map(lambda _: self.salt(volume, FARMOS_HASH_SALT="", startup=True), range(4)))
        self.assertRegex(salts[0], r"^[a-f0-9]{64}$")
        self.assertEqual(len(set(salts)), 1)

    def test_corrupt_saved_salt_fails_without_regenerating(self):
        volume = self.volume()
        result = self.php("file_put_contents('/opt/farmos/private_files/hash_salt', 'bad');", volume=volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.php(LOAD, volume=volume, FARMOS_HASH_SALT="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("persistent hash salt is unreadable or invalid", result.stderr + result.stdout)
        result = self.php("echo file_get_contents('/opt/farmos/private_files/hash_salt');", volume=volume)
        self.assertEqual(result.stdout, "bad")

    def test_unwritable_storage_fails_clearly(self):
        volume = self.volume()
        result = self.php("chmod('/opt/farmos/private_files', 0500);", volume=volume)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.php(LOAD, volume=volume, FARMOS_HASH_SALT="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Mount private_files writable", result.stderr + result.stdout)


class ConnectionTests(ContainerTest):
    def server(self):
        suffix = uuid.uuid4().hex[:10]
        network = "farmos-db-test-" + suffix
        name = network + "-server"
        result = run("docker", "network", "create", network)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(run, "docker", "network", "rm", network)
        self.addCleanup(run, "docker", "rm", "-fv", name)
        args = ["-e", "POSTGRES_DB=farmos", "-e", "POSTGRES_USER=farm",
                "-e", "POSTGRES_PASSWORD=disposable-password", "postgres:17-alpine"]
        result = run("docker", "run", "-d", "--name", name, "--network", network,
                     "--network-alias", "db", *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = self.php(CONNECT + "echo $database->query('SELECT 1')->fetchField();",
                              network=network, FARMOS_DB_DRIVER="pgsql")
            if result.returncode == 0:
                return network
            time.sleep(0.5)
        self.fail("Database did not become ready: " + result.stderr + result.stdout)

    def round_trip(self):
        network = self.server()
        result = self.php(CONNECT + r'''
$database->schema()->createTable('connection_probe', [
    'fields' => ['id' => ['type' => 'serial', 'not null' => TRUE],
                 'value' => ['type' => 'varchar', 'length' => 255]],
    'primary key' => ['id'],
]);
$database->insert('connection_probe')->fields(['value' => 'farm 🌱'])->execute();
$value = $database->select('connection_probe', 'p')->fields('p', ['value'])->execute()->fetchField();
if ($value !== 'farm 🌱') { throw new RuntimeException('Database round trip failed.'); }
$database->schema()->dropTable('connection_probe');
echo 'DATABASE_OK';
''', network=network, FARMOS_DB_DRIVER="pgsql")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout, "DATABASE_OK")

    def test_postgresql_drupal_connection(self):
        self.round_trip()

    def test_farmos_installation_with_each_database_driver(self):
        for driver in ("pgsql", "sqlite"):
            with self.subTest(driver=driver):
                network = "none" if driver == "sqlite" else self.server()
                result = self.php(command=["/opt/farmos/vendor/drush/drush/drush.php", "site:install", "farm",
                                           "--yes", "--account-name=admin", "--account-pass=disposable-admin-password",
                                           "--site-name=Database integration test"],
                                  startup=True, network=network, timeout=240,
                                  FARMOS_DB_DRIVER=driver,
                                  FARMOS_HASH_SALT="",
                                  FARMOS_DB_PASS="" if driver == "sqlite" else "disposable-password")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_sqlite_startup_and_persistence_across_containers(self):
        volume = "farmos-sqlite-test-" + uuid.uuid4().hex[:10]
        self.addCleanup(run, "docker", "volume", "rm", "-f", volume)
        result = run("docker", "run", "--rm", "--user", "0:0", "--entrypoint", "/bin/sh",
                     "--mount", f"type=volume,source={volume},target=/data", IMAGE,
                     "-ec", "chown 65532:65532 /data")
        self.assertEqual(result.returncode, 0, result.stderr)
        for script in [
            "$database->query('CREATE TABLE persistence_probe (value TEXT)'); "
            "$database->insert('persistence_probe')->fields(['value' => 'PERSISTED'])->execute();",
            "echo $database->query('SELECT value FROM persistence_probe')->fetchField();",
        ]:
            result = self.php(CONNECT + script, startup=True, volume=volume,
                              FARMOS_DB_DRIVER="sqlite", FARMOS_DB_PASS="")
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout, "PERSISTED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
