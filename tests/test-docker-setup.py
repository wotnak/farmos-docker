#!/usr/bin/env python3
"""Regression checks using disposable containers. Requires Docker and Python 3."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parent.parent
IMAGE = os.environ.get("IMAGE", "ghcr.io/wotnak/farmos:4")
DOCKER = shutil.which("docker")
FIXTURE = "tests/compose.docker-setup.yaml"
POSTGRES_EXAMPLES = ("examples/prod/compose.yaml", "examples/prod-contrib/compose.yaml",
                     "examples/runtime/compose.yaml")
EXAMPLES = (*POSTGRES_EXAMPLES, "examples/prod-sqlite/compose.yaml")


def run(*args, check=True, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, check=False, **kwargs)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{result.stderr or result.stdout}")
    return result


def compose_env(**overrides):
    defaults = dict(FARMOS_DB_PASS="disposable-test-password",
                FARMOS_HASH_SALT="disposable-test-salt-with-at-least-32-characters",
                IMAGE=IMAGE, FARMOS_DOMAIN="localhost", FARMOS_AUTO_HTTPS="false",
                FARMOS_TRUSTED_HOSTS="", FARMOS_TRUSTED_PROXIES="",
                FARMOS_BIND_ADDRESS="127.0.0.1", FARMOS_PORT="0",
                FARMOS_HTTPS_PORT="0")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("COMPOSE_", "FARMOS_", "POSTGRES_"))}
    return environment | defaults | overrides


def compose_config(*files, **overrides):
    args = [DOCKER, "compose", "--env-file", "/dev/null"]
    for filename in files or (FIXTURE,):
        args += ["-f", filename]
    result = run(*args, "config", "--format", "json", cwd=ROOT,
                 env=compose_env(**overrides))
    return json.loads(result.stdout)


class ComposeConfigTests(unittest.TestCase):
    def test_fixture_isolation_and_limits(self):
        config = compose_config()
        self.assertEqual(set(config["services"]), {"farmos"})
        self.assertTrue(config["networks"]["default"]["internal"])
        spec = config["services"]["farmos"]
        self.assertEqual(spec["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(float(spec["cpus"]), 2)
        self.assertEqual(int(spec["mem_limit"]), 1024**3)
        self.assertEqual(spec["pids_limit"], 256)
        self.assertEqual(spec["logging"]["options"], {"max-size": "10m", "max-file": "3"})
        self.assertTrue(spec["read_only"])
        self.assertEqual({v["target"] for v in spec["volumes"]}, {
            "/opt/farmos/web/sites/default/files", "/opt/farmos/private_files"})

    def test_runtime_project_readonly_with_explicit_writable_storage(self):
        config = compose_config("examples/runtime/compose.yaml", FARMOS_PROJECT_PATH="/tmp/farmos-fixture")
        for service in ("farmos", "cron"):
            mounts = {v["target"]: v for v in config["services"][service]["volumes"]}
            self.assertTrue(mounts["/opt/farmos"]["read_only"])
            self.assertEqual(set(mounts), {"/opt/farmos", "/opt/farmos/web/sites/default/files",
                                           "/opt/farmos/private_files"})
            self.assertTrue(all(v["type"] == "bind" for v in mounts.values()))
            self.assertTrue(all(not v["bind"]["create_host_path"] for v in mounts.values()))

    def test_cron_interval(self):
        for filename in EXAMPLES:
            with self.subTest(filename=filename):
                config = compose_config(filename, FARMOS_CRON_INTERVAL="37",
                                        FARMOS_PROJECT_PATH="/tmp/farmos-fixture")
                cron = config["services"]["cron"]
                self.assertEqual(cron["environment"]["FARMOS_CRON_INTERVAL"], "37")
                self.assertEqual(cron["entrypoint"], ["/usr/bin/farmos-cron"])
                self.assertFalse(cron.get("command"))

    def test_production_example_local_http_and_networks(self):
        config = compose_config("examples/prod/compose.yaml",
                                FARMOS_PORT="8080", FARMOS_HTTPS_PORT="8443")
        app = config["services"]["farmos"]
        self.assertEqual({(p["host_ip"], p["published"], p["target"]) for p in app["ports"]},
                         {("127.0.0.1", "8080", 8080), ("127.0.0.1", "8443", 8443)})
        self.assertEqual(app["environment"]["FARMOS_AUTO_HTTPS"], "false")
        for service in ("farmos", "cron"):
            self.assertEqual(set(config["services"][service]["networks"]), {"default", "frontend"})
        self.assertTrue(config["networks"]["default"]["internal"])
        self.assertFalse(config["networks"]["frontend"].get("internal", False))
        self.assertEqual(set(config["services"]["db"]["networks"]), {"default"})
        self.assertNotIn("ports", config["services"]["db"])

    def test_production_example_https_without_overlays(self):
        config = compose_config("examples/prod/compose.yaml",
                                FARMOS_DOMAIN="farm.example.test", FARMOS_AUTO_HTTPS="true",
                                FARMOS_BIND_ADDRESS="0.0.0.0", FARMOS_PORT="80", FARMOS_HTTPS_PORT="443")
        app = config["services"]["farmos"]
        self.assertEqual({(p["host_ip"], p["published"], p["target"]) for p in app["ports"]},
                         {("0.0.0.0", "80", 8080), ("0.0.0.0", "443", 8443)})
        self.assertEqual(app["environment"]["FARMOS_AUTO_HTTPS"], "true")
        self.assertEqual(app["environment"]["FARMOS_DOMAIN"], "farm.example.test")

    def test_production_example_environment_mapping(self):
        config = compose_config("examples/prod/compose.yaml",
                                FARMOS_DB_NAME="example_db", FARMOS_DB_USER="example_user",
                                FARMOS_DB_PASS="example-password", FARMOS_CRON_INTERVAL="37",
                                POSTGRES_DB="ignored_db", POSTGRES_USER="ignored_user",
                                POSTGRES_PASSWORD="ignored-password")
        for service in ("farmos", "cron"):
            environment = config["services"][service]["environment"]
            self.assertEqual(environment["FARMOS_DB_NAME"], "example_db")
            self.assertEqual(environment["FARMOS_DB_USER"], "example_user")
            self.assertEqual(environment["FARMOS_DB_PASS"], "example-password")
            self.assertEqual(environment["FARMOS_DB_DRIVER"], "pgsql")
            self.assertNotIn("POSTGRES_PASSWORD", environment)
        database = config["services"]["db"]["environment"]
        self.assertEqual(database["POSTGRES_DB"], "example_db")
        self.assertEqual(database["POSTGRES_USER"], "example_user")
        self.assertEqual(database["POSTGRES_PASSWORD"], "example-password")
        self.assertEqual(config["services"]["cron"]["environment"]["FARMOS_CRON_INTERVAL"], "37")

    def test_database_variables_across_postgresql_examples(self):
        for filename in POSTGRES_EXAMPLES:
            with self.subTest(filename=filename):
                config = compose_config(filename, FARMOS_PROJECT_PATH="/tmp/farmos-fixture",
                                        FARMOS_DB_HOST="db", FARMOS_DB_PORT="5544",
                                        FARMOS_DB_NAME="example_db", FARMOS_DB_USER="example_user")
                for service in ("farmos", "cron"):
                    environment = config["services"][service]["environment"]
                    self.assertEqual(environment["FARMOS_DB_HOST"], "db")
                    self.assertEqual(environment["FARMOS_DB_PORT"], "5544")
                    self.assertEqual(environment["FARMOS_DB_NAME"], "example_db")
                    self.assertEqual(environment["FARMOS_DB_USER"], "example_user")
                    self.assertEqual(environment["FARMOS_DB_PASS"], "disposable-test-password")
                    self.assertFalse(any(key.startswith("POSTGRES_") for key in environment))

    def test_sqlite_example_has_no_server_or_password_requirement(self):
        config = compose_config("examples/prod-sqlite/compose.yaml", FARMOS_DB_PASS="")
        self.assertEqual(set(config["services"]), {"farmos", "cron"})
        for service in ("farmos", "cron"):
            environment = config["services"][service]["environment"]
            self.assertEqual(environment["FARMOS_DB_DRIVER"], "sqlite")
            self.assertEqual(environment["FARMOS_DB_NAME"], "/opt/farmos/private_files/database/farmos.sqlite")
            self.assertNotIn("FARMOS_DB_PASS", environment)

    def test_hash_salt_is_optional_across_examples(self):
        for filename in EXAMPLES:
            with self.subTest(filename=filename):
                config = compose_config(filename, FARMOS_HASH_SALT="", FARMOS_PROJECT_PATH="/tmp/farmos-fixture")
                for service in ("farmos", "cron"):
                    self.assertEqual(config["services"][service]["environment"]["FARMOS_HASH_SALT"], "")


class DockerSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = "farmos-setup-test-" + uuid.uuid4().hex[:10]
        cls.compose = [DOCKER, "compose", "--env-file", "/dev/null", "-p", cls.project,
                       "-f", str(ROOT / FIXTURE)]
        cls.env = compose_env()
        cls.addClassCleanup(run, *cls.compose, "down", "-v", "--remove-orphans",
                            check=False, cwd=ROOT, env=cls.env)
        # Health and static routing do not need a database or an installed site.
        run(*cls.compose, "up", "-d", "--no-deps", "--pull", "never", "farmos",
            cwd=ROOT, env=cls.env)
        cls.web = run(*cls.compose, "ps", "-a", "-q", "farmos", cwd=ROOT, env=cls.env).stdout.strip()
        for _ in range(60):
            if run(DOCKER, "exec", cls.web, "wget", "-q", "-O", "/dev/null",
                   "http://127.0.0.1:8080/healthz", check=False).returncode == 0:
                break
            if run(DOCKER, "inspect", "--format", "{{.State.Running}}", cls.web).stdout.strip() != "true":
                logs = run(DOCKER, "logs", cls.web)
                raise RuntimeError(logs.stdout + logs.stderr)
            time.sleep(0.5)
        else:
            logs = run(DOCKER, "logs", cls.web)
            raise RuntimeError(logs.stdout + logs.stderr)

    def test_running_container_isolation(self):
        spec = json.loads(run(DOCKER, "inspect", self.web).stdout)[0]
        host = spec["HostConfig"]
        self.assertTrue(host["ReadonlyRootfs"])
        self.assertEqual(host["Memory"], 1024**3)
        self.assertEqual(host["NanoCpus"], 2_000_000_000)
        self.assertEqual(host["PidsLimit"], 256)
        self.assertEqual(host["PortBindings"]["8080/tcp"][0]["HostIp"], "127.0.0.1")
        networks = spec["NetworkSettings"]["Networks"]
        self.assertEqual(len(networks), 1)
        network = json.loads(run(DOCKER, "network", "inspect", next(iter(networks))).stdout)[0]
        self.assertTrue(network["Internal"])
        routes = run(DOCKER, "exec", self.web, "cat", "/proc/net/route").stdout.splitlines()[1:]
        self.assertFalse(any(route.split()[1] == "00000000" for route in routes),
                         "The isolated application must have no default IPv4 route")
        run(DOCKER, "exec", self.web, "test", "-f", "/opt/farmos/web/sites/default/settings.php")
        run(DOCKER, "exec", self.web, "test", "!", "-w", "/opt/farmos/web/sites/default/settings.php")
        run(DOCKER, "exec", self.web, "test", "!", "-w", "/opt/farmos/web/sites/default")
        # An actual executable copied into temporary storage must not run.
        result = run(DOCKER, "exec", self.web, "/bin/sh", "-c",
                     "cp /bin/busybox /tmp/noexec-probe && /tmp/noexec-probe true", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Permission denied", result.stderr)

    def test_shipped_settings_restrict_hosts_and_forwarded_headers(self):
        # Exercise the installed settings and Drupal/Symfony request handling
        # without requiring an installed database or duplicating its validation.
        script = r'''<?php
$app_root = '/opt/farmos/web';
$site_path = 'sites/default';
$class_loader = require '/opt/farmos/vendor/autoload.php';
require_once '/opt/farmos/web/core/includes/bootstrap.inc';
require '/opt/farmos/web/sites/default/settings.php';

use Drupal\Core\Session\SessionConfiguration;
use Drupal\Core\Site\Settings;
use Drupal\Core\StackMiddleware\ReverseProxyMiddleware;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Exception\SuspiciousOperationException;

$site = new Settings($settings);
Request::setTrustedHosts($settings['trusted_host_patterns']);
$results = [];
foreach (['trusted' => '192.0.2.10', 'untrusted' => '192.0.2.11'] as $name => $remote) {
    $request = Request::create('http://farm.example.test/', 'GET', [], [], [], [
        'REMOTE_ADDR' => $remote,
        'HTTP_X_FORWARDED_PROTO' => 'https',
        'HTTP_X_FORWARDED_PORT' => '443',
        'HTTP_X_FORWARDED_FOR' => '198.51.100.25',
        'HTTP_X_FORWARDED_HOST' => 'attacker.invalid',
    ]);
    ReverseProxyMiddleware::setSettingsOnRequest($request, $site);
    $options = (new SessionConfiguration())->getOptions($request);
    $results[$name] = [
        'secure' => $request->isSecure(),
        'cookie_secure' => $options['cookie_secure'],
        'host' => $request->getHost(),
        'client_ip' => $request->getClientIp(),
    ];
}
foreach (['attacker.invalid', 'farm.example.test.attacker.invalid', 'farmXexampleXtest'] as $host) {
    try {
        Request::create('http://' . $host . '/')->getHost();
        $results['rejected_hosts'][$host] = false;
    } catch (SuspiciousOperationException $exception) {
        $results['rejected_hosts'][$host] = true;
    }
}
echo json_encode($results, JSON_THROW_ON_ERROR);
'''
        run(DOCKER, "exec", "-i", self.web, "/bin/sh", "-c",
            "cat > /tmp/proxy-settings-test.php", input=script)
        response = run(DOCKER, "exec", "-e", "FARMOS_DOMAIN=farm.example.test",
                       "-e", "FARMOS_TRUSTED_HOSTS=", "-e", "FARMOS_TRUSTED_PROXIES=192.0.2.10",
                       self.web, "/usr/bin/php", "/tmp/proxy-settings-test.php")
        results = json.loads(response.stdout)
        self.assertEqual(results["trusted"], {
            "secure": True, "cookie_secure": True, "host": "farm.example.test",
            "client_ip": "198.51.100.25"})
        self.assertEqual(results["untrusted"], {
            "secure": False, "cookie_secure": False, "host": "farm.example.test",
            "client_ip": "192.0.2.11"})
        self.assertTrue(all(results["rejected_hosts"].values()))

    def test_http_file_protections(self):
        base = "/sites/default/files/docker-review"
        fixtures = {
            "probe.php": '<?php echo "PHP_EXECUTED";',
            "settings.php.bak": '<?php /* BACKUP_SECRET */',
            "settings.php~": '<?php /* BACKUP_SECRET */',
            "settings.php.swp": "BACKUP_SECRET",
            "config_HASH/sync/system.site.yml": "secret: CONFIG_SECRET",
            "services.yaml": "secret: CONFIG_SECRET",
            "source.module.orig": "SOURCE_SECRET",
            "dump.mysql": "DATABASE_SECRET",
            "nested/composer.json": "{}",
            "Template": "METADATA_SECRET",
            ".hidden": "HIDDEN_SECRET",
            "style.css": "body { color: green; }",
        }
        for path, contents in fixtures.items():
            target = "/opt/farmos/web" + base + "/" + path
            run(DOCKER, "exec", self.web, "mkdir", "-p", str(Path(target).parent))
            run(DOCKER, "exec", "-i", self.web, "/bin/sh", "-c", 'cat > "$1"',
                "sh", target, input=contents)
        blocked = [base + "/" + path for path in fixtures if path != "style.css"]
        blocked += [base + "/probe.php/extra", base + "/probe%2ephp/extra",
                    "/sites/default/default.services.yml", "/core/composer.json"]
        for path in blocked + [base + "/style.css", "/healthz"]:
            with self.subTest(path=path):
                response = run(DOCKER, "exec", self.web, "wget", "-S", "-O", "-",
                               "http://127.0.0.1:8080" + path, check=False)
                expected = "404 Not Found" if path in blocked else "200 OK"
                self.assertIn(expected, response.stderr)
                if path in blocked:
                    self.assertNotIn("SECRET", response.stdout)
                    self.assertNotIn("PHP_EXECUTED", response.stdout)



if __name__ == "__main__":
    unittest.main(verbosity=2)
