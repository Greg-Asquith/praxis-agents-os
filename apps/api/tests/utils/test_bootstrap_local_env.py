"""Tests for the shared local environment bootstrap."""

from pathlib import Path

from bin.bootstrap_local_env import bootstrap


def test_bootstrap_enables_artifact_sharing_only_in_local_env_files(tmp_path: Path) -> None:
    workspace = tmp_path
    api_dir = workspace / "apps/api"
    api_dir.mkdir(parents=True)
    (api_dir / ".env.example").write_text(
        "ARTIFACT_SHARING_ENABLED=false\nCREDENTIAL_MASTER_KEYS=\n"
    )

    bootstrap(workspace)

    api_env = (api_dir / ".env").read_text()
    generated_env = (workspace / ".local/generated/local.api.env").read_text()
    example_env = (api_dir / ".env.example").read_text()
    assert "ARTIFACT_SHARING_ENABLED=true" in api_env
    assert "ARTIFACT_SHARING_ENABLED=true" in generated_env
    assert "ARTIFACT_SHARING_ENABLED=false" in example_env
