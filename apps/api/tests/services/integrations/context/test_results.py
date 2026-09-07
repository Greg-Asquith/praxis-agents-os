"""Model and transcript projection of authorized integration results."""

from collections import UserDict
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest

from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import (
    IntegrationContextResult,
    split_fan_out_tool_return,
)


@pytest.fixture
def entry() -> ResolvedContextEntry:
    return ResolvedContextEntry(
        integration_resource_id=uuid4(),
        provider_key="example",
        resource_type="account",
        external_id="first",
        display_name="First account",
        connection_id=uuid4(),
        connection_label="Private connection",
        connection_status="active",
        write_allowed=True,
        is_personal=True,
        permissions_metadata={"private": "authorization evidence"},
    )


@pytest.mark.parametrize(
    ("data", "model_data", "display_data"),
    [
        (
            {"model_result": {"count": 2}, "display_result": {"rows": [1, 2]}, "audit": "private"},
            {"count": 2},
            {"rows": [1, 2]},
        ),
        (UserDict(model_result=[], display_result=[1]), [], [1]),
        ({"display_result": [1]}, None, [1]),
        ({"model_result": [1]}, [1], None),
        ({}, None, None),
        (None, None, None),
        ([1, 2], [1, 2], [1, 2]),
        ("legacy result", "legacy result", "legacy result"),
        (0, 0, 0),
    ],
)
def test_split_preserves_only_public_fields(
    entry: ResolvedContextEntry, data: Any, model_data: Any, display_data: Any
) -> None:
    result = split_fan_out_tool_return(
        [IntegrationContextResult(entry=entry, status="success", data=data)]
    )

    envelope = {
        "provider_key": "example",
        "external_id": "first",
        "display_name": "First account",
        "status": "success",
        "error_code": None,
        "error_message": None,
    }
    assert result.return_value == {"results": [{**envelope, "data": model_data}]}
    assert result.metadata == {"public_result": {"results": [{**envelope, "data": display_data}]}}


def test_split_preserves_order_and_error_evidence(entry: ResolvedContextEntry) -> None:
    items = [
        IntegrationContextResult(
            entry=entry,
            status="error",
            error_code="permission_denied",
            error_message="Access denied.",
        ),
        IntegrationContextResult(
            entry=replace(entry, external_id="second", display_name="Second account"),
            status="success",
            data={"model_result": {"count": 1}, "display_result": {"rows": ["Applied"]}},
        ),
        IntegrationContextResult(
            entry=replace(entry, external_id="third", display_name="Third account"),
            status="error",
            data={"model_result": {"count": 1}, "display_result": {"rows": ["Unverified"]}},
            error_code="unverified_mutation",
            error_message="Check the provider before retrying.",
        ),
    ]
    result = split_fan_out_tool_return(items)

    denied = {
        "provider_key": "example",
        "external_id": "first",
        "display_name": "First account",
        "status": "error",
        "data": None,
        "error_code": "permission_denied",
        "error_message": "Access denied.",
    }
    applied = {
        "provider_key": "example",
        "external_id": "second",
        "display_name": "Second account",
        "status": "success",
        "data": {"count": 1},
        "error_code": None,
        "error_message": None,
    }
    unverified = {
        "provider_key": "example",
        "external_id": "third",
        "display_name": "Third account",
        "status": "error",
        "data": {"count": 1},
        "error_code": "unverified_mutation",
        "error_message": "Check the provider before retrying.",
    }
    assert result.return_value == {"results": [denied, applied, unverified]}
    assert result.metadata == {
        "public_result": {
            "results": [
                denied,
                {**applied, "data": {"rows": ["Applied"]}},
                {**unverified, "data": {"rows": ["Unverified"]}},
            ]
        }
    }
    assert items[1].data == {"model_result": {"count": 1}, "display_result": {"rows": ["Applied"]}}


def test_split_empty_results() -> None:
    result = split_fan_out_tool_return([])
    assert result.return_value == {"results": []}
    assert result.metadata == {"public_result": {"results": []}}
