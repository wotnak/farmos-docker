#!/usr/bin/env python3
"""Build, load, and test the configured image variants without shell expansion."""

import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_config
from nix_source import snapshot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NIX_FLAGS = '--extra-experimental-features "nix-command flakes"'


class LocalBuildError(ValueError):
    """The requested local operation does not match its prepared profile."""


def linux_system(machine=None):
    machine = platform.machine() if machine is None else machine
    if machine in {"x86_64", "amd64"}:
        return "x86_64-linux"
    if machine in {"arm64", "aarch64"}:
        return "aarch64-linux"
    raise LocalBuildError("Unsupported architecture; set NIX_SYSTEM explicitly")


def prepared_profile(root, profile):
    path = root / ".build-inputs/build.json"
    if (root / ".build-inputs/.preparing").exists():
        raise LocalBuildError("Build input preparation is still running")
    try:
        metadata = json.loads(path.read_text())
    except (OSError, ValueError):
        raise LocalBuildError("Prepared build inputs are missing or invalid; run task prepare-inputs") from None
    if not isinstance(metadata, dict) or not build_config.PROFILE_KEYS.issubset(metadata):
        raise LocalBuildError("Prepared build inputs are invalid; run task prepare-inputs")
    try:
        prepared = build_config.normalize({key: metadata.get(key) for key in build_config.PROFILE_KEYS})
    except build_config.ConfigurationError:
        raise LocalBuildError("Prepared build profile is invalid; run task prepare-inputs") from None
    if prepared != profile:
        raise LocalBuildError("Build profile changed since preparation; run task prepare-inputs again")
    if not (root / "flake.lock").is_file():
        raise LocalBuildError("Prepared Nix lock is missing; run task prepare-inputs")
    return metadata


class LocalBuild:
    def __init__(self, root, environment=None, *, configuration=None, nix=None, nix_flags=None, system=None, execute=None):
        self.root = Path(root).resolve()
        self.environment = dict(os.environ if environment is None else environment)
        self.profile = (build_config.normalize(json.loads(Path(configuration).read_text()))
                        if configuration is not None else build_config.load(self.environment))
        self.images = build_config.tags(self.profile)
        self.nix = nix if nix is not None else self.environment.get("NIX", "nix")
        self.nix_flags = nix_flags if nix_flags is not None else self.environment.get("NIX_FLAGS", DEFAULT_NIX_FLAGS)
        self.flags = shlex.split(self.nix_flags)
        self.system = system or self.environment.get("NIX_SYSTEM") or linux_system()
        self.execute = subprocess.run if execute is None else execute

    def environment_for(self, **overrides):
        environment = dict(self.environment)
        for field, variable in build_config.VARIABLES.items():
            value = self.profile[field]
            environment[variable] = ",".join(value) if isinstance(value, list) else value or ""
        environment.update(NIX=self.nix, NIX_FLAGS=self.nix_flags, NIX_SYSTEM=self.system)
        environment.update(overrides)
        return environment

    def run(self, *command, **kwargs):
        environment = self.environment_for(**kwargs.pop("environment", {}))
        return self.execute(list(command), cwd=self.root, env=environment, check=True, **kwargs)

    def variants(self, variant=None):
        selected = self.profile["variants"]
        if variant is not None:
            if variant not in selected:
                raise LocalBuildError(f"Variant {variant} is not enabled by FARMOS_IMAGE_VARIANTS")
            return [variant]
        return list(selected)

    def require_runtimes(self):
        for variant in ("runtime", "development-runtime"):
            self.variants(variant)
        return ["runtime", "development-runtime"]

    def prepare(self):
        self.run(sys.executable, str(self.root / "scripts/prepare-build"))

    def source(self):
        prepared_profile(self.root, self.profile)
        return "path:" + str(snapshot(self.root))

    def build(self, variant=None, *, variants=None):
        selected = self.variants(variant) if variants is None else [self.variants(name)[0] for name in variants]
        source = self.source()
        for name in selected:
            output = build_config.VARIANTS[name]["output"]
            self.run(self.nix, *self.flags, "build", "--system", self.system,
                     source + "#" + output, "--out-link", str(self.root / "build" / output))

    def load(self, variant=None, *, variants=None):
        selected = self.variants(variant) if variants is None else [self.variants(name)[0] for name in variants]
        self.build(variants=selected)
        source = "path:" + str(self.root / "build/nix-source")
        for name in selected:
            output = build_config.VARIANTS[name]["output"]
            # Use a host-native copier even when the image targets a remote Linux builder.
            self.run(self.nix, *self.flags, "run", source + "#skopeo-nix2container", "--",
                     "--insecure-policy", "copy", "nix:" + str(self.root / "build" / output),
                     "docker-daemon:" + self.images[name])

    def push(self, variant=None):
        selected = self.variants(variant)
        self.load(variants=selected)
        for name in selected:
            self.run("docker", "push", self.images[name])

    def test_variant(self, variant, suite=None, *, loaded=False, arguments=()):
        image = self.images[variant]
        common = {"IMAGE": image, "DEV": "1" if variant in {"development", "development-runtime"} else "0"}
        if suite is None:
            suites = {"production": ["smoke", "database", "e2e"],
                      "development": ["smoke", "phpunit", "contrib-ci"],
                      "runtime": ["runtime"], "development-runtime": ["runtime"]}[variant]
        else:
            allowed = {"smoke": {"production", "development"}, "database": {"production"},
                       "e2e": {"production"}, "http": {"production"}, "phpunit": {"development"},
                       "contrib-ci": {"development"}, "runtime": {"runtime", "development-runtime"}}
            if variant not in allowed.get(suite, set()):
                raise LocalBuildError(f"Test suite {suite} does not apply to variant {variant}")
            suites = [suite]
        for selected in suites:
            if selected == "smoke":
                self.run("sh", "tests/smoke-test.sh", environment=common)
            else:
                arguments_for_suite = tuple(arguments) if selected == "phpunit" else ()
                command = ["task", "test-stack", "SUITE=" + selected]
                if arguments_for_suite:
                    command += ["--", *arguments_for_suite]
                self.run(*command, environment={
                    **common, "DB_TEST_IMAGE": image,
                    "TEST_ARTIFACTS": self.environment.get("TEST_ARTIFACTS") or str(self.root / "build/tests" / selected),
                })

    def contrib(self, *, loaded=False):
        self.require_runtimes()
        runtime = self.images["runtime"]
        development = self.images["development-runtime"]
        self.run("task", "test-stack", "SUITE=contrib", environment={
            "RUNTIME_IMAGE": runtime,
            "DEV_RUNTIME_IMAGE": development,
            "TEST_ARTIFACTS": self.environment.get("TEST_ARTIFACTS") or str(self.root / "build/tests/contrib"),
            "COMPOSER_CACHE_PATH": self.environment.get("COMPOSER_CACHE_PATH") or str(self.root / "build/tests/contrib/composer-cache"),
        })

    def test(self, variant=None, suite=None, *, loaded=False, arguments=()):
        selected = self.require_runtimes() if suite == "contrib" else self.variants(variant)
        if suite is not None and suite != "contrib" and variant is None:
            raise LocalBuildError("Select a variant for an individual test suite")
        if not loaded:
            self.load(variants=selected)
        if suite == "contrib":
            self.contrib(loaded=loaded)
            return
        for name in selected:
            self.test_variant(name, suite, loaded=loaded, arguments=arguments)
        if variant is None and suite is None and all(name in selected for name in ("runtime", "development-runtime")):
            self.contrib(loaded=loaded)

    def run_site(self, *, https=False):
        self.load("production")
        image = self.images["production"]
        configuration = {"services": {service: {"image": image} for service in ("farmos", "cron")}}
        environment = {"FARMOS_AUTO_HTTPS": "true", "FARMOS_BIND_ADDRESS": "0.0.0.0",
                       "FARMOS_PORT": "80", "FARMOS_HTTPS_PORT": "443"} if https else {}
        self.run("docker", "compose", "--project-directory", str(self.root / "examples/prod"),
                 "-f", str(self.root / "examples/prod/compose.yaml"), "-f", "-", "up", "-d",
                 input=json.dumps(configuration), text=True, environment=environment)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--configuration", type=Path, help="Use a resolved build profile JSON file")
    parser.add_argument("--nix")
    parser.add_argument("--nix-flags")
    parser.add_argument("--system")
    parser.add_argument("--prepared", action="store_true")
    parser.add_argument("--variant", choices=tuple(build_config.VARIANTS))
    parser.add_argument("--suite", choices=("smoke", "database", "http", "e2e", "phpunit", "contrib-ci", "runtime", "contrib"))
    parser.add_argument("--loaded", action="store_true")
    parser.add_argument("--https", action="store_true")
    parser.add_argument("operation", choices=("prepare", "image", "validate", "build", "load", "push", "test", "run", "flake-check", "cache-plan", "cache-prune"))
    args, arguments = parser.parse_known_args(argv)
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    if arguments and not (args.operation == "test" and args.suite == "phpunit"):
        parser.error("Extra arguments are supported only for the PHPUnit suite")
    environment = dict(os.environ)
    try:
        local = LocalBuild(args.root, environment, configuration=args.configuration,
                           nix=args.nix, nix_flags=args.nix_flags, system=args.system)
        local.variants(args.variant)
        if args.suite == "contrib":
            local.require_runtimes()
        if args.operation == "prepare":
            local.prepare()
        elif args.operation == "image":
            if args.variant is None:
                raise LocalBuildError("Select a variant to print its image reference")
            print(local.images[args.variant])
        elif args.operation == "validate":
            if args.prepared:
                prepared_profile(local.root, local.profile)
        elif args.operation == "cache-plan":
            local.source()
            print("\n".join(build_config.VARIANTS[name]["output"] for name in local.variants()))
        else:
            if not args.prepared and not (args.operation == "test" and args.loaded):
                local.prepare()
            if args.operation == "build":
                local.build(args.variant)
            elif args.operation == "load":
                local.load(args.variant)
            elif args.operation == "push":
                local.push(args.variant)
            elif args.operation == "test":
                local.test(args.variant, args.suite, loaded=args.loaded, arguments=arguments)
            elif args.operation == "run":
                local.run_site(https=args.https)
            elif args.operation == "flake-check":
                source = local.source()
                local.run(local.nix, *local.flags, "flake", "show", source, "--all-systems")
            elif args.operation == "cache-prune":
                local.source()
                local.run("bash", "scripts/nix-build-cache", "prune")
    except (LocalBuildError, build_config.ConfigurationError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Local image operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
