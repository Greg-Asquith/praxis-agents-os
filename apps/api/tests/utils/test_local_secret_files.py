"""Safety tests for local environment-file shell tooling."""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
VALIDATE_SCRIPT = REPO_ROOT / "apps/api/bin/validate_sourceable_env.sh"
REPLACE_SCRIPT = REPO_ROOT / "apps/api/bin/replace_env_value.sh"
SHELL = "/bin/sh"


def test_validation_redacts_malformed_assignment_value(tmp_path: Path) -> None:
    env_file = tmp_path / "local.secrets.env"
    secret = "do-not-print-this secret value"
    env_file.write_text(f"OPENAI_API_KEY={secret}\n")

    result = subprocess.run(  # noqa: S603 - fixed shell and repository script
        [SHELL, str(VALIDATE_SCRIPT), str(env_file)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 65
    assert f"{env_file}:1: OPENAI_API_KEY: quote values that contain spaces" in result.stderr
    assert secret not in result.stderr
    assert secret not in result.stdout


def test_validation_redacts_crlf_assignment_value(tmp_path: Path) -> None:
    env_file = tmp_path / "local.secrets.env"
    secret = "do-not-print-this"
    env_file.write_bytes(f"ANTHROPIC_API_KEY={secret}\r\n".encode())

    result = subprocess.run(  # noqa: S603 - fixed shell and repository script
        [SHELL, str(VALIDATE_SCRIPT), str(env_file)],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 65
    assert f"{env_file}:1: ANTHROPIC_API_KEY:" in result.stderr
    assert secret not in result.stderr
    assert secret not in result.stdout


def test_replacement_is_atomic_and_private(tmp_path: Path) -> None:
    env_file = tmp_path / "local.secrets.env"
    env_file.write_text("KEEP=value\nOPENAI_API_KEY=old\nOPENAI_API_KEY=duplicate\n")
    env_file.chmod(0o644)

    subprocess.run(  # noqa: S603 - fixed shell and repository script
        [SHELL, str(REPLACE_SCRIPT), str(env_file), "OPENAI_API_KEY"],
        check=True,
        input="new-secret\n",
        text=True,
    )

    assert env_file.read_text() == "KEEP=value\nOPENAI_API_KEY=new-secret\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert list(tmp_path.glob("local.secrets.env.tmp.*")) == []


def test_interrupted_replacement_preserves_file_and_cleans_temporary_data(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "local.secrets.env"
    original = "OPENAI_API_KEY=old\n"
    env_file.write_text(original)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "move-started"
    fake_mv = fake_bin / "mv"
    fake_mv.write_text('#!/bin/sh\n: > "$MOVE_MARKER"\nwhile :; do sleep 1; done\n')
    fake_mv.chmod(0o755)
    env = os.environ | {
        "MOVE_MARKER": str(marker),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }

    process = subprocess.Popen(  # noqa: S603 - fixed shell and repository script
        [SHELL, str(REPLACE_SCRIPT), str(env_file), "OPENAI_API_KEY"],
        env=env,
        stdin=subprocess.PIPE,
        start_new_session=True,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write("new-secret\n")
    process.stdin.close()
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()
    temporary_files = list(tmp_path.glob("local.secrets.env.tmp.*"))
    assert len(temporary_files) == 1
    assert stat.S_IMODE(temporary_files[0].stat().st_mode) == 0o600

    os.killpg(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5) != 0

    assert env_file.read_text() == original
    assert list(tmp_path.glob("local.secrets.env.tmp.*")) == []


def test_entrypoints_delegate_secret_handling_to_safety_helpers() -> None:
    entrypoint = (REPO_ROOT / "apps/api/bin/compose_entrypoint.sh").read_text()
    deployment_makefile = (REPO_ROOT / "makefiles/deployment.mk").read_text()

    assert "validate_sourceable_env.sh" in entrypoint
    assert "replace_env_value.sh" in deployment_makefile
    assert "local.secrets.env.tmp" not in deployment_makefile
