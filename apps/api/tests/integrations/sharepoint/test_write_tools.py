# apps/api/tests/integrations/sharepoint/test_write_tools.py

"""SharePoint write validation, scope selection, approvals, and audit evidence."""

import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import ModelRetry

from integrations.sharepoint.operations.write_utils import ItemName, TextContent
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.tools import TOOL_DEFINITIONS
from tests.integrations.sharepoint.support import context, entry, file_metadata
from utils.quickxorhash import quickxorhash

CONTENT = "PRIVATE_CONTENT_MARKER\n界"
NAME = "PRIVATE_NAME_MARKER.txt"
FILE = SharePointDriveItemReference(drive_id="drive", item_id="file", kind="file")
FOLDER = SharePointDriveItemReference(drive_id="drive", item_id="folder", kind="folder")
ARGS = {
    "create_folder": {"name": "PRIVATE_FOLDER_MARKER"},
    "write_file": {"name": NAME, "content": CONTENT},
    "update_file": {"file": FILE, "expected_version": '"version-1"', "content": CONTENT},
}
WRITES = tuple(
    definition
    for definition in TOOL_DEFINITIONS
    if definition.effect_scope == "external" and definition.effect == "write"
)


def writable(drive_id="drive"):
    return replace(entry(drive_id), write_allowed=True)


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.approved_display_args",
        lambda ctx: ctx.reviewed_display,
    )
    item = file_metadata(
        name=NAME,
        size=len(CONTENT.encode()),
        file={"mimeType": "text/plain", "hashes": {"quickXorHash": quickxorhash(CONTENT.encode())}},
    )
    item["parentReference"]["id"] = "folder"
    folder = {**item, "id": "folder", "folder": {}}
    folder.pop("file")

    async def get(path, **kwargs):
        return folder if path.endswith("/folder") else item

    async def post(path, **kwargs):
        if path.endswith("/children"):
            return {**folder, "name": kwargs["json"]["name"]}
        return {"uploadUrl": "https://example.sharepoint.com/upload?PRIVATE_UPLOAD_SECRET"}

    client = SimpleNamespace(
        get=AsyncMock(side_effect=get),
        post=AsyncMock(side_effect=post),
        upload_fragment=AsyncMock(return_value={**item, "eTag": '"version-2"'}),
        upload_status=AsyncMock(),
        cancel_upload=AsyncMock(),
    )
    factory = AsyncMock(return_value=client)
    audit = AsyncMock(return_value=uuid4())
    monkeypatch.setattr("integrations.sharepoint.tools.write_utils.drive_client", factory)
    monkeypatch.setattr(
        "services.integrations.operations.record_integration_operation_audit_event", audit
    )
    return SimpleNamespace(client=client, factory=factory, audit=audit, item=item, folder=folder)


async def invoke(name, *, args=None, entries=None):
    module = importlib.import_module(f"integrations.sharepoint.tools.{name}")
    ctx = context(*(entries if entries is not None else [writable()]))
    ctx.tool_name = f"sharepoint_{name}"
    values = ARGS[name] if args is None else args
    ctx.reviewed_display = await module.DEFINITION.approval_display_args(ctx.deps, values)
    return await getattr(module, ctx.tool_name)(ctx, **values)


@pytest.mark.parametrize("name", ARGS)
async def test_writes_record_private_pending_intent_and_correlated_terminal_evidence(
    provider, name
):
    result = await invoke(name)
    definition = next(value for value in WRITES if value.name == f"sharepoint_{name}")
    definition.output_model.model_validate(result)
    data = result["results"][0]["data"]
    assert data["outcome"] == "applied" and data["item"]["version"]
    pending, terminal = [call.kwargs for call in provider.audit.await_args_list]
    assert str(pending["status"]) == "pending" and str(terminal["status"]) == "success"
    assert terminal["related_event_id"] == provider.audit.return_value
    intent = pending["operation_detail"]
    assert intent.target.external_id == "drive"
    intent_fields = intent.intent_groups[0].items[0].fields
    assert intent_fields["action"] == name
    assert intent_fields["size_bytes"] == (0 if name == "create_folder" else len(CONTENT.encode()))
    assert intent_fields["content_type"] == (None if name == "create_folder" else "text/plain")
    assert not any(
        marker in intent.model_dump_json() for marker in [NAME, CONTENT, "PRIVATE_FOLDER_MARKER"]
    )
    evidence = terminal["operation_detail"].outcome_groups[0].outcomes[0].effects[0].fields
    assert evidence["committed"] is True
    assert evidence["etag_after"] == data["item"]["version"]
    assert evidence["etag_before"] == ('"version-1"' if name == "update_file" else None)
    assert evidence["hash_matched"] == (None if name == "create_folder" else True)
    assert "PRIVATE_UPLOAD_SECRET" not in str(result) + str(terminal)


@pytest.mark.parametrize("name", ARGS)
async def test_unapproved_calls_cannot_use_live_context_as_approval(provider, monkeypatch, name):
    from services.integrations.approved_display_args import approved_display_args

    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.approved_display_args", approved_display_args
    )
    module = importlib.import_module(f"integrations.sharepoint.tools.{name}")
    ctx = context(writable())
    ctx.tool_name = f"sharepoint_{name}"
    ctx.tool_call_approved = False
    result = await getattr(module, ctx.tool_name)(ctx, **ARGS[name])
    assert "approved details are unavailable" in result["results"][0]["error_message"]
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize("name", ARGS)
async def test_readonly_library_records_shared_denial_before_credentials(provider, name):
    result = await invoke(name, entries=[entry()])
    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider.factory.assert_not_awaited()
    provider.client.post.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert provider.audit.await_args.kwargs["error_code"] == "write_not_permitted"
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize("name", ["create_folder", "write_file"])
@pytest.mark.parametrize(
    "drives",
    [
        [],
        ["first", "second"],
    ],
)
async def test_root_write_requires_exactly_one_writable_library(provider, name, drives):
    with pytest.raises(ModelRetry):
        await invoke(name, entries=[writable(drive) for drive in drives])
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


@pytest.mark.parametrize("name,field", [("create_folder", "parent"), ("write_file", "folder")])
@pytest.mark.parametrize(
    "change",
    [
        "drive",
        "resource",
    ],
)
async def test_cleared_destination_requires_review_when_root_binding_changes(
    provider, name, field, change
):
    module = importlib.import_module(f"integrations.sharepoint.tools.{name}")
    selected = writable()
    reviewed = await module.DEFINITION.approval_display_args(
        context(selected).deps, {**ARGS[name], field: FOLDER}
    )
    changed = {
        "drive": replace(selected, external_id="other"),
        "resource": replace(selected, integration_resource_id=uuid4()),
        "connection": replace(selected, connection_id=uuid4()),
    }[change]
    ctx = context(changed)
    ctx.tool_name = f"sharepoint_{name}"
    ctx.reviewed_display = reviewed

    result = await getattr(module, ctx.tool_name)(ctx, **{**ARGS[name], field: None})

    assert "Prepare the action for approval again" in result["results"][0]["error_message"]
    provider.factory.assert_not_awaited()
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()


@pytest.mark.parametrize(
    "name,field,reference",
    [
        ("create_folder", "parent", FOLDER),
    ],
)
async def test_reference_cannot_select_unselected_library(provider, name, field, reference):
    with pytest.raises(ModelRetry):
        await invoke(name, args={**ARGS[name], field: reference}, entries=[writable("other")])
    provider.factory.assert_not_awaited()


async def test_changed_version_fails_before_pending_intent_or_upload(provider):
    provider.item["eTag"] = '"version-2"'
    result = await invoke("update_file")
    assert result["results"][0]["error_code"] == "version_conflict"
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize(
    "name",
    [".", ".."],
)
def test_name_rules_reject_invalid_names(name):
    with pytest.raises(ValidationError):
        TypeAdapter(ItemName).validate_python(name)


@pytest.mark.parametrize(
    "content",
    ["\x00", "\x1b"],
)
def test_text_rules_reject_controls_and_invalid_unicode(content):
    with pytest.raises(ValidationError):
        TypeAdapter(TextContent).validate_python(content)
