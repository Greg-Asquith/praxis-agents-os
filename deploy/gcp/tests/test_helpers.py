#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
