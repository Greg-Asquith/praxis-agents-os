"""Checks configuration that bounds execution ownership."""

import pytest
from pydantic import ValidationError

from core.settings import Settings


@pytest.mark.parametrize("interval,ttl", [(30, 30), (31, 30)])
def test_heartbeat_must_precede_lease_expiry(interval: int, ttl: int) -> None:
    with pytest.raises(ValidationError, match="AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS"):
        Settings(
            AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS=interval,
            AGENT_RUN_LEASE_TTL_SECONDS=ttl,
        )


@pytest.mark.parametrize("depth", [-1, 2])
def test_unsupported_delegation_depth_is_rejected(depth: int) -> None:
    with pytest.raises(ValidationError, match="AGENT_MAX_DELEGATION_DEPTH"):
        Settings(AGENT_MAX_DELEGATION_DEPTH=depth)


@pytest.mark.parametrize("depth", [0, 1])
def test_supported_execution_settings(depth: int) -> None:
    resolved = Settings(
        AGENT_MAX_DELEGATION_DEPTH=depth,
        AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS=29,
        AGENT_RUN_LEASE_TTL_SECONDS=30,
    )
    assert depth == resolved.AGENT_MAX_DELEGATION_DEPTH
    assert resolved.AGENT_RUN_MAX_DURATION_SECONDS == 1200
