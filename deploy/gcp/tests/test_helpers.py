#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

spec = importlib.util.spec_from_file_location(
    "gcp_deploy_helpers", REPO_ROOT / "deploy/gcp/helpers.py"
)
assert spec and spec.loader
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)

from services.secrets.utils import (
    cloud_secret_id as application_cloud_secret_id,
)


class GcpDeploymentHelperTests(unittest.TestCase):
    def test_private_bucket_bootstrap_plans_creation_or_hardening_for_approval(self) -> None:
        source = (REPO_ROOT / "deploy/gcp/bootstrap.sh").read_text()
        block = source.split('echo "Checking platform-private bucket"', 1)[1].split(
            'echo "Checking dedicated service accounts and IAM"', 1
        )[0]
        for exists, location in ((False, ""), (True, "EUROPE-WEST4"), (True, "US")):
            with self.subTest(exists=exists, location=location):
                setup = f"""
set -Eeuo pipefail
GCS_PLATFORM_PRIVATE_BUCKET=example-private
GCP_PROJECT_ID=example-project
GCP_REGION=europe-west4
public_assets_cors_file=/tmp/explicit-cors.json
exists={str(exists).lower()}
location={shlex.quote(location)}
gcs_value() {{
  if [[ "$*" == *"value(name)"* ]]; then "$exists";
  else printf '%s' "$location"; fi
}}
plan_gcs() {{ printf 'PLAN %s\\n' "$*"; }}
execute_section() {{ printf 'APPROVAL %s\\n' "$*"; }}
die() {{ echo "$*" >&2; exit 1; }}
"""
                result = subprocess.run(
                    ["bash", "-c", setup + block],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if location == "US":
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("does not match europe-west4", result.stderr)
                    self.assertNotIn("PLAN", result.stdout)
                    continue
                self.assertEqual(result.returncode, 0, result.stderr)
                commands = [
                    line for line in result.stdout.splitlines()
                    if line.startswith("PLAN ")
                ]
                self.assertEqual(len(commands), 1 if exists else 2)
                for command in commands:
                    self.assertIn("gs://example-private", command)
                    self.assertIn("--project=example-project", command)
                    self.assertIn("--uniform-bucket-level-access", command)
                    self.assertIn("--public-access-prevention", command)
                    self.assertIn("--soft-delete-duration=30d", command)
                    self.assertNotIn("allUsers", command)
                    self.assertNotIn("allAuthenticatedUsers", command)
                if not exists:
                    self.assertIn("buckets create", commands[0])
                    self.assertIn("--location=europe-west4", commands[0])
                self.assertIn("buckets update", commands[-1])
                self.assertIn("--versioning", commands[-1])
                self.assertIn("--cors-file=/tmp/explicit-cors.json", commands[-1])
                self.assertTrue(
                    result.stdout.endswith("APPROVAL Platform-private bucket\n")
                )

    def test_private_bucket_approval_rejection_does_not_execute_mutations(self) -> None:
        source = (REPO_ROOT / "deploy/gcp/bootstrap.sh").read_text()
        approval = "execute_section() {" + source.split("execute_section() {", 1)[1].split(
            "\ngcs_value() {", 1
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mutation"
            setup = (
                "set -Eeuo pipefail\n"
                "die() { echo \"$*\" >&2; exit 1; }\n"
                f"planned_commands=({shlex.quote('touch ' + shlex.quote(str(marker)))})\n"
                "planned_metrics_env=('')\n"
            )
            result = subprocess.run(
                ["bash", "-c", setup + approval + '\nexecute_section "Platform-private bucket"'],
                input="no\n", capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("authorization not granted", result.stderr)
            self.assertFalse(marker.exists())

    def test_secret_id_matches_application_mapping(self) -> None:
        for logical_name in (
            "application-encryption-keys",
            "credential-master-key",
            "workspaces/00000000-0000-0000-0000-000000000000/provider-key",
        ):
            self.assertEqual(
                helpers.cloud_secret_id(logical_name),
                application_cloud_secret_id(logical_name),
            )

    def test_audit_policy_merge_preserves_bindings_and_is_idempotent(self) -> None:
        policy = {
            "version": 1,
            "etag": "abc",
            "bindings": [
                {"role": "roles/viewer", "members": ["user:test@example.invalid"]}
            ],
        }
        first = helpers.add_data_access_audit_configs(policy)
        second = helpers.add_data_access_audit_configs(first)
        self.assertEqual(first, second)
        self.assertEqual(first["etag"], "abc")
        self.assertEqual(len(first["bindings"]), 1)
        for service in helpers.AUDIT_SERVICES:
            config = next(
                item for item in first["auditConfigs"] if item["service"] == service
            )
            self.assertEqual(
                {entry["logType"] for entry in config["auditLogConfigs"]},
                set(helpers.AUDIT_LOG_TYPES),
            )

    def test_privileged_members_flags_owner_and_editor_only(self) -> None:
        policy = {
            "bindings": [
                {"role": "roles/owner", "members": ["serviceAccount:a@p.iam.gserviceaccount.com"]},
                {"role": "roles/editor", "members": ["serviceAccount:b@p.iam.gserviceaccount.com"]},
                {"role": "roles/viewer", "members": ["serviceAccount:c@p.iam.gserviceaccount.com"]},
            ]
        }
        members = [
            f"serviceAccount:{name}@p.iam.gserviceaccount.com" for name in ("a", "b", "c")
        ]
        self.assertEqual(helpers.privileged_members(policy, members), members[:2])
        self.assertEqual(helpers.privileged_members({"bindings": []}, members), [])

    def test_gcs_browser_cors_config_is_explicit_and_covers_signed_upload_headers(
        self,
    ) -> None:
        config = helpers.gcs_browser_cors_config(
            "https://app.example.invalid, https://admin.example.invalid/,"
            "https://app.example.invalid/"
        )

        self.assertEqual(
            config,
            [
                {
                    "origin": [
                        "https://app.example.invalid",
                        "https://admin.example.invalid",
                    ],
                    "method": ["GET", "HEAD", "PUT"],
                    "responseHeader": [
                        "Content-Length",
                        "Content-Type",
                        "ETag",
                        "x-goog-generation",
                        "x-goog-if-generation-match",
                    ],
                    "maxAgeSeconds": 3600,
                }
            ],
        )

    def test_gcs_browser_cors_config_rejects_wildcards_and_non_origins(self) -> None:
        for origins in ("", "*", "https://app.example.invalid/path", "file://local"):
            with self.subTest(origins=origins), self.assertRaises(ValueError):
                helpers.gcs_browser_cors_config(origins)

    def test_render_template_substitutes_only_allowlisted_variables(self) -> None:
        template = "image: ${API_IMAGE}\nother: ${NOT_ALLOWED}\n"
        rendered = helpers.render_template(
            template, {"API_IMAGE": "registry/app:abc", "NOT_ALLOWED": "x"}, ["API_IMAGE"]
        )
        self.assertEqual(rendered, "image: registry/app:abc\nother: ${NOT_ALLOWED}\n")

    def test_render_template_rejects_unset_or_empty_allowlisted_variables(self) -> None:
        for values in ({}, {"API_IMAGE": ""}):
            with self.assertRaises(ValueError):
                helpers.render_template("${API_IMAGE}", values, ["API_IMAGE"])

    def test_render_template_treats_replacement_values_literally(self) -> None:
        rendered = helpers.render_template(
            "value: ${RAW}", {"RAW": "back\\slash ${AND} &1"}, ["RAW"]
        )
        self.assertEqual(rendered, "value: back\\slash ${AND} &1")

    def test_microsoft_graph_settings_use_defaults_and_preserve_tenant_overrides(self) -> None:
        entries = yaml.safe_load(helpers.microsoft_graph_env_yaml({
            "MICROSOFT_GRAPH_TENANT": "shared.example.com",
            "OUTLOOK_MAIL_OAUTH_TENANT": "mail.example.com",
        }, ""))
        values = {entry["name"]: entry["value"] for entry in entries}
        self.assertEqual(values["MICROSOFT_GRAPH_TENANT"], "shared.example.com")
        self.assertEqual(values["OUTLOOK_MAIL_OAUTH_TENANT"], "mail.example.com")
        self.assertEqual(values["OUTLOOK_CALENDAR_OAUTH_TENANT"], "")
        self.assertEqual(values["MICROSOFT_GRAPH_REQUESTS_PER_SECOND"], "4.0")
        self.assertEqual(values["SHAREPOINT_DISCOVERY_MAX_SITES"], "50")

    def test_microsoft_graph_settings_can_all_use_secret_bindings(self) -> None:
        bindings = ",".join(
            f"{name}=example-{index}"
            for index, name in enumerate(helpers.MICROSOFT_GRAPH_ENV_DEFAULTS)
        )
        rendered = helpers.microsoft_graph_env_yaml({"RUNTIME_SECRET_BINDINGS": bindings}, "")
        self.assertTrue(rendered)
        self.assertIsNone(yaml.safe_load(rendered))

    def test_microsoft_graph_secret_bindings_render_without_raw_configuration(self) -> None:
        bound_names = (
            "MICROSOFT_GRAPH_TENANT", "OUTLOOK_MAIL_OAUTH_CLIENT_ID", "OUTLOOK_MAIL_OAUTH_TENANT",
        )
        example = (REPO_ROOT / "deploy/gcp/.env.example").read_text()
        base = "\n".join(
            line for line in example.splitlines()
            if line.split("=", 1)[0] not in helpers.MICROSOFT_GRAPH_ENV_DEFAULTS
        )
        bindings = ",".join(f"{name}=example-{name.lower()}" for name in bound_names)
        environment = {
            key: value for key, value in os.environ.items()
            if key not in helpers.MICROSOFT_GRAPH_ENV_DEFAULTS
        }
        for stale_raw_value in (False, True):
            with self.subTest(stale_raw_value=stale_raw_value), tempfile.TemporaryDirectory() as tmp:
                env_file = Path(tmp) / "deployment.env"
                content = base + f'\nRUNTIME_SECRET_BINDINGS="${{RUNTIME_SECRET_BINDINGS}},{bindings}"\n'
                if stale_raw_value:
                    content += "\n".join(f"{name}=stale-raw-value" for name in bound_names)
                env_file.write_text(content)
                rendered = Path(tmp) / "rendered"
                result = subprocess.run(
                    [str(REPO_ROOT / "deploy/gcp/deploy.sh"), "--render-only", str(rendered),
                     str(env_file), "abcdef0123456789"],
                    env=environment, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                for manifest in ("services/praxis-api.yaml", "jobs/praxis-worker.yaml"):
                    source = (rendered / manifest).read_text()
                    self.assertNotIn("stale-raw-value", source)
                    document = yaml.safe_load(source)
                    spec = document["spec"]["template"]["spec"]
                    if manifest.startswith("jobs/"):
                        spec = spec["template"]["spec"]
                    entries = spec["containers"][0]["env"]
                    for name in bound_names:
                        self.assertEqual([entry for entry in entries if entry["name"] == name], [{
                            "name": name,
                            "valueFrom": {"secretKeyRef": {
                                "name": f"example-{name.lower()}", "key": "latest",
                            }},
                        }])
                    values = {entry["name"]: entry.get("value") for entry in entries}
                    self.assertEqual(values["OUTLOOK_CALENDAR_OAUTH_TENANT"], "")
                    self.assertEqual(values["SHAREPOINT_OAUTH_CLIENT_ID"], "")
                    self.assertEqual(values["MICROSOFT_GRAPH_REQUESTS_PER_SECOND"], "4.0")
                migration = (rendered / "jobs/praxis-migrate.yaml").read_text()
                for name in bound_names:
                    self.assertNotIn(name, migration)

    def test_audit_policy_cli_reports_changed_then_unchanged(self) -> None:
        def run_cli(input_path: Path, output_path: Path) -> str:
            stdout = io.StringIO()
            argv = ["helpers.py", "audit-policy", str(input_path), str(output_path)]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
                helpers.main()
            return stdout.getvalue().strip()

        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare.json"
            merged = Path(tmp) / "merged.json"
            remerged = Path(tmp) / "remerged.json"
            bare.write_text(json.dumps({"bindings": []}), encoding="utf-8")
            self.assertEqual(run_cli(bare, merged), "changed")
            self.assertEqual(run_cli(merged, remerged), "unchanged")


if __name__ == "__main__":
    unittest.main()
