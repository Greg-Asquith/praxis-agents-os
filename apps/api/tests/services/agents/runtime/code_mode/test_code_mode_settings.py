import pytest
from pydantic import ValidationError

from core.settings import Settings


def test_code_mode_defaults_are_bounded() -> None:
    resolved = Settings()

    assert resolved.AGENT_CODE_MODE_POOL_SIZE == 2
    assert resolved.AGENT_CODE_MODE_TIMEOUT_SECONDS == 60
    assert resolved.AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS == 65
    assert resolved.AGENT_CODE_MODE_MAX_NESTED_CALLS == 25
    assert resolved.AGENT_CODE_MODE_OUTPUT_MAX_CHARS == 8_000
    assert resolved.AGENT_CODE_MODE_VALUE_MAX_BYTES == 262_144
    assert resolved.AGENT_CODE_MODE_RESULT_MAX_BYTES == 32_768
    assert resolved.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES == 512 * 1024
    assert resolved.AGENT_CODE_MODE_STATE_MAX_BYTES == 2 * 1024 * 1024
    assert resolved.AGENT_CODE_MODE_MEMORY_MAX_BYTES == 64 * 1024 * 1024
    assert resolved.AGENT_CODE_MODE_MAX_RECURSION_DEPTH == 100


def test_worker_request_backstop_must_exceed_script_timeout() -> None:
    with pytest.raises(ValidationError, match="REQUEST_TIMEOUT_SECONDS must exceed"):
        Settings(
            AGENT_CODE_MODE_TIMEOUT_SECONDS=10,
            AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS=10,
        )


def test_nested_call_budget_cannot_exceed_durable_state_bound() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 25"):
        Settings(AGENT_CODE_MODE_MAX_NESTED_CALLS=26)


def test_state_bound_must_cover_snapshot_and_headroom() -> None:
    with pytest.raises(ValidationError, match="base64 snapshot"):
        Settings(
            AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES=512 * 1024,
            AGENT_CODE_MODE_STATE_MAX_BYTES=700_000,
        )


def test_model_result_bound_cannot_exceed_boundary_value_bound() -> None:
    with pytest.raises(ValidationError, match="RESULT_MAX_BYTES cannot exceed"):
        Settings(
            AGENT_CODE_MODE_RESULT_MAX_BYTES=101,
            AGENT_CODE_MODE_VALUE_MAX_BYTES=100,
        )
