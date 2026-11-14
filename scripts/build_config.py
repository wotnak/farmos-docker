#!/usr/bin/env python3
"""Read and validate image build settings from the environment."""

import json
import os
import re
import unicodedata
from urllib.parse import urlsplit


VARIANTS = {
    "production": {"suffix": "", "output": "farmos"},
    "development": {"suffix": "-dev", "output": "farmos-dev"},
    "runtime": {"suffix": "-runtime", "output": "farmos-runtime"},
    "development-runtime": {"suffix": "-dev-runtime", "output": "farmos-dev-runtime"},
}
PROFILE_KEYS = {"farmos-version", "image-name", "image-tag", "repository", "variants"}
VARIABLES = {
    "farmos-version": "FARMOS_VERSION",
    "image-name": "FARMOS_IMAGE_NAME",
    "image-tag": "FARMOS_IMAGE_TAG",
    "repository": "FARMOS_REPOSITORY",
    "variants": "FARMOS_IMAGE_VARIANTS",
}
DEFAULT_IMAGE_NAME = "ghcr.io/wotnak/farmos"
TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
COMPONENT = r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*"
IMAGE_NAME = re.compile(r"(?:[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/)?" + COMPONENT + r"(?:/" + COMPONENT + r")*")


class ConfigurationError(ValueError):
    """Image build settings cannot safely describe a build."""


def _controls(value):
    return any(unicodedata.category(character) in {"Cc", "Cs"} for character in value)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError("Repository JSON contains duplicate fields")
        result[key] = value
    return result


def _reject_url_credentials(value):
    if isinstance(value, dict):
        for entry in value.values():
            _reject_url_credentials(entry)
    elif isinstance(value, list):
        for entry in value:
            _reject_url_credentials(entry)
    elif isinstance(value, str) and "://" in value:
        try:
            parsed = urlsplit(value)
            if parsed.username is not None or parsed.password is not None or _controls(value):
                raise ConfigurationError("Repository URLs must not contain credentials or control characters")
        except ValueError:
            raise ConfigurationError("Repository JSON contains an invalid URL") from None


def _repository(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigurationError("FARMOS_REPOSITORY must be a Composer repository JSON object")
    try:
        repository = json.loads(value, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError):
        raise ConfigurationError("FARMOS_REPOSITORY must be a Composer repository JSON object") from None
    if (not isinstance(repository, dict) or not isinstance(repository.get("type"), str)
            or not repository["type"].strip() or _controls(repository["type"])):
        raise ConfigurationError("A custom Composer repository must be an object with a type")
    if "url" in repository and (not isinstance(repository["url"], str) or not repository["url"].strip()):
        raise ConfigurationError("A custom Composer repository URL must be a nonempty string")
    if repository["type"].lower() == "path":
        raise ConfigurationError("Composer path repositories are unavailable inside the isolated Nix build")
    _reject_url_credentials(repository)
    try:
        return json.dumps(repository, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except ValueError:
        raise ConfigurationError("Repository JSON must contain finite JSON values") from None


def _variants(value):
    if value is None or value == "":
        return list(VARIANTS)
    if isinstance(value, str):
        entries = [entry.strip() for entry in value.split(",")]
    elif isinstance(value, list):
        entries = value
    else:
        raise ConfigurationError("FARMOS_IMAGE_VARIANTS must list supported variant names")
    if (not entries or any(not isinstance(entry, str) or entry not in VARIANTS for entry in entries)
            or len(set(entries)) != len(entries)):
        raise ConfigurationError("FARMOS_IMAGE_VARIANTS contains empty, duplicate, or unsupported variants")
    return [name for name in VARIANTS if name in entries]


def normalize(settings):
    """Return exactly the five profile fields, without interpreting Composer constraints."""
    if not isinstance(settings, dict):
        raise ConfigurationError("Build configuration must be an object")
    version = settings.get("farmos-version")
    if not isinstance(version, str) or not version.strip() or _controls(version):
        raise ConfigurationError("FARMOS_VERSION must be a nonempty Composer constraint without control characters")
    image_name = settings.get("image-name")
    if image_name is None or image_name == "":
        image_name = DEFAULT_IMAGE_NAME
    if not isinstance(image_name, str) or len(image_name) > 255 or not IMAGE_NAME.fullmatch(image_name):
        raise ConfigurationError("FARMOS_IMAGE_NAME must be a lowercase container repository name")
    image_tag = settings.get("image-tag")
    if not isinstance(image_tag, str) or not TAG.fullmatch(image_tag):
        raise ConfigurationError("FARMOS_IMAGE_TAG must be a valid container tag")
    variants = _variants(settings.get("variants"))
    if any(len(image_tag + VARIANTS[name]["suffix"]) > 128 for name in variants):
        raise ConfigurationError("FARMOS_IMAGE_TAG and each selected variant suffix must fit in 128 characters")
    return {"farmos-version": version, "image-name": image_name, "image-tag": image_tag,
            "repository": _repository(settings.get("repository")), "variants": variants}


def tags(profile):
    profile = normalize(profile)
    return {variant: profile["image-name"] + ":" + profile["image-tag"] + VARIANTS[variant]["suffix"]
            for variant in profile["variants"]}


def load(environ=None):
    """Read build settings from the process environment."""
    environment = os.environ if environ is None else environ
    return normalize({field: environment.get(name) for field, name in VARIABLES.items()})
