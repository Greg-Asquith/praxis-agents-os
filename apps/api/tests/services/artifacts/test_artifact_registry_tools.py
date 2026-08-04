# apps/api/tests/services/artifacts/test_artifact_registry_tools.py

"""Artifact registry and CSP contract tests."""

from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from pydantic import ValidationError

from core.exceptions.general import NotFoundError
from core.settings import Settings
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_POLICY_AUTO,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.artifacts.create_view_url import require_valid_artifact_view_signature
from services.artifacts.domain import (
    ARTIFACT_CSP_CDN_HOSTS,
    CREATABLE_ARTIFACT_TYPES,
    artifact_frame_ancestors,
    build_html_csp,
)
from services.artifacts.schemas import ArtifactToolResult


def test_artifact_tools_are_auto_mounted_auto_default_external_writes() -> None:
    assert [name for name in sorted(RUNTIME_TOOL_CATALOG) if "artifact" in name] == [
        "create_artifact",
        "update_artifact",
    ]
    for name in ("create_artifact", "update_artifact"):
        definition = RUNTIME_TOOL_CATALOG[name]
        assert definition.effect == TOOL_EFFECT_WRITE
        assert definition.effect_scope == TOOL_EFFECT_SCOPE_EXTERNAL
        assert definition.default_policy == TOOL_POLICY_AUTO
        assert definition.supports_approval is True
        assert definition.supports_auto is True
        assert definition.output_model is ArtifactToolResult
        assert definition.configurable is False
        assert definition.auto_mount is True
    assert "image-ref" not in CREATABLE_ARTIFACT_TYPES


def test_html_csp_has_no_external_content_hosts() -> None:
    csp = build_html_csp(
        connect_src="'none'",
        frame_ancestors=artifact_frame_ancestors(),
    )
    assert ARTIFACT_CSP_CDN_HOSTS == ()
    assert "cdn.jsdelivr.net" not in csp
    assert "unpkg.com" not in csp
    directives = {
        parts[0]: parts[1:] for directive in csp.split(";") if (parts := directive.strip().split())
    }
    for name in ("script-src", "style-src", "font-src", "img-src", "connect-src"):
        for source in directives[name]:
            parsed = urlsplit(source)
            assert not (parsed.scheme and parsed.netloc)
    assert directives["connect-src"] == ["'none'"]
    assert directives["sandbox"] == ["allow-scripts"]


def test_expired_view_capability_fails_before_lookup() -> None:
    with pytest.raises(NotFoundError):
        require_valid_artifact_view_signature(
            workspace_id=uuid4(),
            artifact_id=uuid4(),
            version_id=uuid4(),
            expires=0,
            signature="v1." + ("0" * 64),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ARTIFACT_VIEW_URL_TTL_SECONDS", 0),
        ("ARTIFACT_VIEW_URL_TTL_SECONDS", 3601),
        ("ARTIFACT_MAX_CONTENT_BYTES", 0),
        ("ARTIFACT_MAX_CONTENT_BYTES", 10_485_761),
    ],
)
def test_artifact_limits_reject_unsafe_values(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
