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
    assert resolved.AGENT_CODE_MODE_MEMORY_MAX_BYTES == 64 * 1024 * 1024
    assert resolved.AGENT_CODE_MODE_MAX_RECURSION_DEPTH == 100


def test_worker_request_backstop_must_exceed_script_timeout() -> None:
    with pytest.raises(ValidationError, match="REQUEST_TIMEOUT_SECONDS must exceed"):
        Settings(
            AGENT_CODE_MODE_TIMEOUT_SECONDS=10,
            AGENT_CODE_MODE_REQUEST_TIMEOUT_SECONDS=10,
        )
