#!/usr/bin/env python3
"""Offline regression tests for upstream discovery and its Actions outputs."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import urllib.error


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import discover_upstream as discovery
FARMOS_SHA = "a" * 40
PROJECT_SHA = "b" * 40


def release(version, **overrides):
    result = {
        "tag_name": version,
        "draft": False,
        "prerelease": False,
    }
    result.update(overrides)
    return result


def branch(sha):
    return {"ref": "refs/heads/4.x", "object": {"type": "commit", "sha": sha}}


class Response(io.BytesIO):
    def __init__(self, data, next_page=False):
        super().__init__(json.dumps(data).encode())
        self.headers = {"Link": '<https://api.github.com/next>; rel="next"'} if next_page else {}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {
            "minimum_major": 4,
            "versions": {"4.x": {
                "constraint": "4.x-dev", "farmosRev": FARMOS_SHA,
                "farmosSourceHash": "source-hash", "composerProjectRev": PROJECT_SHA,
                "composerProjectHash": "project-hash", "devHash": "development-hash",
            }},
        }
        self.pin_release("4.0.4")
        self.requests = []
        self.responses = [Response([release("4.0.4")]), Response(branch(FARMOS_SHA)), Response(branch(PROJECT_SHA))]
        mock = patch.object(discovery.urllib.request, "urlopen", side_effect=self.open)
        mock.start()
        self.addCleanup(mock.stop)

    def pin_release(self, version):
        self.data["versions"][version.split(".", 1)[0]] = {
            "version": version, "prodHash": "prod-hash", "devHash": "dev-hash",
        }
        self.save()

    def save(self):
        (self.root / "versions.json").write_text(json.dumps({"minimum_major": 4, "development_branch": "4.x"}))
        (self.root / ".build-inputs").mkdir(exist_ok=True)
        (self.root / ".build-inputs/versions.json").write_text(json.dumps(self.data))

    def open(self, request, timeout):
        self.assertEqual(timeout, 30)
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def run_discovery(self):
        return discovery.discover(self.root)

    def test_no_change(self):
        self.assertEqual(self.run_discovery(), {
            "release_version": "4.0.4",
            "release_matrix": {"include": [{"major": "4", "version": "4.0.4"}]},
            "farmos_rev": FARMOS_SHA, "composer_project_rev": PROJECT_SHA,
        })
        self.assertEqual([request.full_url for request in self.requests], [
            "https://api.github.com/repos/farmOS/farmOS/releases?per_page=100&page=1",
            "https://api.github.com/repos/farmOS/farmOS/git/ref/heads/4.x",
            "https://api.github.com/repos/farmOS/composer-project/git/ref/heads/4.x",
        ])

    def test_pagination_semantic_order_and_release_filters(self):
        self.responses[0:1] = [
            Response([release("4.9.0"), release("99.0.0", draft=True), release("98.0.0", prerelease=True),
                      release("4.11.0-rc1"), release("v97.0.0"), release("04.99.0")], next_page=True),
            Response([release("4.10.9"), release("4.10.10"), release("4.10.0"), release("4.8.99")]),
        ]
        result = self.run_discovery()
        self.assertEqual(result["release_version"], "4.10.10")
        self.assertEqual(result["release_matrix"], {"include": [{"major": "4", "version": "4.10.10"}]})
        self.assertTrue(self.requests[1].full_url.endswith("page=2"))

    def test_new_major_is_discovered(self):
        self.responses[0] = Response([release("10.0.0"), release("9.99.99"), release("5.1.0"),
                                      release("5.0.9"), release("4.99.99")])
        result = self.run_discovery()
        self.assertEqual(result["release_version"], "10.0.0")
        self.assertEqual(result["release_matrix"]["include"], [
            {"major": "4", "version": "4.99.99"}, {"major": "5", "version": "5.1.0"},
            {"major": "9", "version": "9.99.99"}, {"major": "10", "version": "10.0.0"},
        ])

    def test_later_patch_to_older_minor_is_ignored(self):
        self.pin_release("4.1.0")
        self.responses[0] = Response([release("4.0.99"), release("4.1.0"), release("4.0.4")])
        result = self.run_discovery()
        self.assertEqual(result["release_version"], "4.1.0")
        self.assertEqual(result["release_matrix"]["include"], [
            {"major": "4", "version": "4.1.0"},
        ])

    def test_tracking_excludes_legacy_and_ignores_local_majors(self):
        self.pin_release("4.1.2")
        self.pin_release("5.2.3")
        self.responses[0] = Response([release("3.99.99"), release("4.0.3"), release("6.0.0")])
        rows = self.run_discovery()["release_matrix"]["include"]
        self.assertEqual(rows, [{"major": "4", "version": "4.0.3"},
                                {"major": "6", "version": "6.0.0"}])

    def test_local_pins_do_not_override_current_upstream(self):
        self.pin_release("4.10.2")
        self.pin_release("5.1.3")
        self.pin_release("9.0.1")
        self.responses[0] = Response([release("4.9.99"), release("5.1.2"), release("9.0.2")])
        result = self.run_discovery()
        self.assertEqual(result["release_matrix"]["include"], [
            {"major": "4", "version": "4.9.99"}, {"major": "5", "version": "5.1.2"},
            {"major": "9", "version": "9.0.2"},
        ])

    def test_previous_snapshot_is_ignored(self):
        self.pin_release("4.0.5")
        result = self.run_discovery()
        self.assertEqual(result["release_version"], "4.0.4")

    def test_latest_release_without_assets_is_selected(self):
        self.responses[0] = Response([release("4.0.4"), release("4.0.5", assets=[])])
        result = self.run_discovery()
        self.assertEqual(result["release_version"], "4.0.5")

    def test_release_selection_does_not_depend_on_bundles(self):
        for asset in [{"name": "farmOS-4.0.5.tar.gz", "state": "new"},
                      {"name": "farmOS-4.0.4.tar.gz", "state": "uploaded"}]:
            with self.subTest(asset=asset):
                self.responses = [Response([release("4.0.5", assets=[asset])]),
                                  Response(branch(FARMOS_SHA)), Response(branch(PROJECT_SHA))]
                self.assertEqual(self.run_discovery()["release_version"], "4.0.5")

    def test_no_stable_release_fails(self):
        self.responses[0] = Response([release("4.0.5-rc1"), release("4.0.4", draft=True)])
        with self.assertRaisesRegex(discovery.DiscoveryError, "No published stable"):
            self.run_discovery()

    def test_each_branch_change_is_detected(self):
        for position, output_key in [(1, "farmos_rev"), (2, "composer_project_rev")]:
            with self.subTest(repository=output_key):
                self.responses = [Response([release("4.0.4")]), Response(branch(FARMOS_SHA)), Response(branch(PROJECT_SHA))]
                self.responses[position] = Response(branch("c" * 40))
                result = self.run_discovery()
                self.assertEqual(result[output_key], "c" * 40)

    def test_malformed_commit_rejected(self):
        for sha in ["abc1234", "g" * 40, None, "a" * 40 + "\n", "a" * 40 + "\nchanged=true"]:
            with self.subTest(sha=sha):
                self.responses = [Response([release("4.0.4")]), Response(branch(sha))]
                with self.assertRaises(discovery.DiscoveryError):
                    self.run_discovery()

    def test_wrong_ref_or_object_rejected(self):
        for result in [[], {"ref": "refs/heads/main", "object": {"type": "commit", "sha": FARMOS_SHA}},
                       {"ref": "refs/heads/4.x", "object": {"type": "tag", "sha": FARMOS_SHA}}]:
            with self.subTest(result=result):
                self.responses = [Response([release("4.0.4")]), Response(result)]
                with self.assertRaises(discovery.DiscoveryError):
                    self.run_discovery()

    def test_invalid_release_response_rejected(self):
        for response in [{"message": "error"}, [None], [{"tag_name": "4.0.5"}]]:
            with self.subTest(response=response):
                self.responses = [Response(response)]
                with self.assertRaises(discovery.DiscoveryError):
                    self.run_discovery()

    def test_api_failures_return_nonzero_without_partial_output(self):
        for error in [urllib.error.HTTPError("url", 403, "secret-token", {}, None),
                      urllib.error.URLError("secret-token"), TimeoutError("secret-token")]:
            with self.subTest(error=type(error).__name__):
                self.responses = [error]
                output_file = self.root / "outputs"
                output_file.write_text("existing=value\n")
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = discovery.main(["--root", str(self.root), "--github-output", str(output_file)])
                self.assertEqual(code, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertNotIn("secret-token", stderr.getvalue())
                self.assertEqual(output_file.read_text(), "existing=value\n")

    def test_invalid_json_fails(self):
        response = io.BytesIO(b"not json")
        self.responses = [response]
        with self.assertRaisesRegex(discovery.DiscoveryError, "invalid JSON"):
            self.run_discovery()

    def test_actions_output_and_auth(self):
        output_file = self.root / "outputs"
        output_file.write_text("existing=value\n")
        stdout = io.StringIO()
        with patch.dict(discovery.os.environ, {"GH_TOKEN": "secret-token"}), redirect_stdout(stdout):
            code = discovery.main(["--root", str(self.root), "--github-output", str(output_file)])
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertNotIn("changed", result)
        self.assertTrue(output_file.read_text().startswith("existing=value\n"))
        self.assertNotIn("changed=", output_file.read_text())
        self.assertIn("release_version=4.0.4\n", output_file.read_text())
        outputs = dict(line.split("=", 1) for line in output_file.read_text().splitlines())
        self.assertEqual(json.loads(outputs["release_matrix"]), result["release_matrix"])
        self.assertNotIn("secret-token", stdout.getvalue() + output_file.read_text())
        self.assertEqual(self.requests[0].get_header("Authorization"), "Bearer secret-token")

    def test_invalid_previous_snapshot_is_ignored(self):
        (self.root / ".build-inputs/versions.json").write_text("broken old snapshot")
        self.assertEqual(self.run_discovery()["release_version"], "4.0.4")

    def test_invalid_policy_fails_before_query(self):
        (self.root / "versions.json").write_text('{"minimum_major":true,"development_branch":"4.x"}')
        with self.assertRaises(discovery.ReleaseError):
            self.run_discovery()
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
