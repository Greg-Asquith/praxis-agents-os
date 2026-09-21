"""SharePoint write validation, scope selection, approvals, and audit evidence."""

import importlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from pydantic_ai import ModelRetry

from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from integrations.sharepoint.operations.write_utils import ItemName, TextContent, text_content_type
from integrations.sharepoint.references import SharePointDriveItemReference
from integrations.sharepoint.settings import sharepoint_settings
from integrations.sharepoint.tools import TOOL_DEFINITIONS
from integrations.sharepoint.tools.mutations import (
    CreateFolderInput,
    UpdateFileInput,
    WriteFileInput,
)
from services.agents.runtime.code_mode.stubs import render_tool_stub
from services.agents.runtime.tools.contract import validate_definition
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
WRITES = tuple(definition for definition in TOOL_DEFINITIONS if definition.effect == "write")


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
    ctx.reviewed_display = module.DEFINITION.approval_display_args(ctx.deps, values)
    return await getattr(module, ctx.tool_name)(ctx, **values)


@pytest.mark.parametrize("definition", WRITES, ids=lambda value: value.name)
def test_write_contracts_and_code_mode_schemas(definition):
    validate_definition(definition)
    assert definition.name in render_tool_stub(definition)
    assert definition.default_policy == "approval" and definition.supports_approval
    assert not definition.supports_auto and definition.code_eligible
    assert definition.integration_binding.requires_write
    assert definition.effect_scope == "external" and definition.egress == "external_write"
    schema = definition.to_pydantic_tool().function_schema.json_schema
    assert set(schema["properties"]) == {field.key for field in definition.presentation.arg_fields}
    assert definition.approval_display_args is not None


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
@pytest.mark.parametrize("pin", [None, {}, {"drive_id": "drive"}])
async def test_missing_approval_target_fails_before_credentials(provider, monkeypatch, name, pin):
    monkeypatch.setattr(
        "integrations.sharepoint.tools.write_utils.approved_display_args",
        lambda _ctx: {"_target": pin},
    )
    result = await invoke(name)
    assert "approved library is unavailable" in result["results"][0]["error_message"]
    provider.factory.assert_not_awaited()


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
@pytest.mark.parametrize("drives", [[], ["first", "second"], ["drive", "drive"]])
async def test_root_write_requires_exactly_one_writable_library(provider, name, drives):
    with pytest.raises(ModelRetry):
        await invoke(name, entries=[writable(drive) for drive in drives])
    provider.factory.assert_not_awaited()
    provider.audit.assert_not_awaited()


@pytest.mark.parametrize("name", ["create_folder", "write_file"])
async def test_root_write_selects_only_writable_library(provider, name):
    result = await invoke(name, entries=[entry("readonly"), writable()])
    assert len(result["results"]) == 1 and result["results"][0]["data"]["outcome"] == "applied"
    assert provider.factory.await_args.args[1].external_id == "drive"


@pytest.mark.parametrize(
    "name,field,reference",
    [
        ("create_folder", "parent", FOLDER),
        ("write_file", "folder", FOLDER),
        ("update_file", "file", FILE),
    ],
)
async def test_reference_cannot_select_unselected_library(provider, name, field, reference):
    with pytest.raises(ModelRetry):
        await invoke(name, args={**ARGS[name], field: reference}, entries=[writable("other")])
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize(
    "name,field,reference",
    [
        ("create_folder", "parent", FOLDER),
        ("write_file", "folder", FOLDER),
        ("update_file", "file", FILE),
    ],
)
async def test_readonly_reference_cannot_fall_back_to_another_writable_library(
    provider, name, field, reference
):
    result = await invoke(
        name, args={**ARGS[name], field: reference}, entries=[entry(), writable("other")]
    )
    assert result["results"][0]["error_code"] == "write_not_permitted"
    provider.factory.assert_not_awaited()
    assert provider.audit.await_args.kwargs["error_code"] == "write_not_permitted"


async def test_hash_mismatch_retains_unverified_terminal_evidence(provider):
    provider.client.upload_fragment.return_value["file"]["hashes"]["quickXorHash"] = "mismatch"
    result = await invoke("write_file")
    failed = result["results"][0]
    assert failed["error_code"] == "unverified_mutation"
    assert failed["data"]["outcome"] == "unverified"
    pending, terminal = [call.kwargs for call in provider.audit.await_args_list]
    assert str(pending["status"]) == "pending" and str(terminal["status"]) == "unverified"
    fields = terminal["operation_detail"].outcome_groups[0].outcomes[0].effects[0].fields
    assert fields["committed"] and fields["hash_matched"] is False
    assert fields["etag_after"] == '"version-2"'


@pytest.mark.parametrize("name,field", [("create_folder", "parent"), ("write_file", "folder")])
async def test_folder_reference_targets_selected_drive_with_multiple_libraries(
    provider, name, field
):
    result = await invoke(
        name, args={**ARGS[name], field: FOLDER}, entries=[writable(), writable("other")]
    )
    assert result["results"][0]["data"]["outcome"] == "applied"
    assert provider.client.get.await_args.args == ("/drives/drive/items/folder",)
    assert provider.client.post.await_args.args[0].startswith("/drives/drive/items/folder")


async def test_changed_version_fails_before_pending_intent_or_upload(provider):
    provider.item["eTag"] = '"version-2"'
    result = await invoke("update_file")
    assert result["results"][0]["error_code"] == "version_conflict"
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize(
    "mime_type",
    [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/png",
        "application/octet-stream",
        "unknown/type",
        "",
        None,
        42,
        {},
        [],
    ],
)
async def test_unsupported_replacement_mime_fails_before_pending_intent(provider, mime_type):
    provider.item["file"]["mimeType"] = mime_type
    result = await invoke("update_file")
    assert result["results"][0]["error_code"] == "unsupported_type"
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize(
    "mime_type,extension",
    [
        ("text/plain", "txt"),
        ("text/markdown", "md"),
        ("text/csv", "csv"),
        ("application/json", "json"),
        ("text/html", "html"),
    ],
)
@pytest.mark.parametrize("case_variant", [False, True])
async def test_replacement_uses_normalised_editable_contract(
    provider, mime_type, extension, case_variant
):
    provider.item["file"]["mimeType"] = mime_type.title() if case_variant else mime_type
    provider.item["name"] = f"notes.{extension}"
    result = await invoke("update_file")
    assert result["results"][0]["data"]["outcome"] == "applied"
    provider.client.upload_fragment.assert_awaited_once()
    pending = provider.audit.await_args_list[0].kwargs["operation_detail"]
    assert pending.intent_groups[0].items[0].fields["content_type"] == mime_type
    assert [str(call.kwargs["status"]) for call in provider.audit.await_args_list] == [
        "pending",
        "success",
    ]


@pytest.mark.parametrize("name", ["notes.docx", "notes.png", "notes.pdf", "notes"])
async def test_replacement_still_requires_text_extension(provider, name, monkeypatch):
    checked = []

    def checked_content_type(value, *, operation):
        with pytest.raises(IntegrationValidationError) as caught:
            text_content_type(value, operation=operation)
        assert caught.value.operation == "update_file"
        checked.append(caught.value)
        raise caught.value

    monkeypatch.setattr(
        "integrations.sharepoint.tools.update_file.text_content_type", checked_content_type
    )
    provider.item["name"] = name
    result = await invoke("update_file")
    assert len(checked) == 1
    assert result["results"][0]["error_code"] == "unsupported_type"
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize("action,field", [("create_folder", "parent"), ("write_file", "folder")])
@pytest.mark.parametrize("kind", ["file", "invalid"])
async def test_parent_validation_preserves_owning_operation(provider, action, field, kind):
    from integrations.sharepoint.tools.write_utils import require_parent

    provider.folder.pop("folder")
    if kind == "file":
        provider.folder["file"] = {"mimeType": "text/plain"}
    with pytest.raises(IntegrationValidationError) as caught:
        await require_parent(provider.client, drive_id="drive", reference=FOLDER, operation=action)
    assert caught.value.operation == action
    if kind == "file":
        assert caught.value.user_message == "Choose a folder as the destination."
    result = await invoke(action, args={**ARGS[action], field: FOLDER})
    assert result["results"][0]["error_code"] == (
        "unsupported_type" if kind == "file" else "IntegrationValidationError"
    )
    provider.client.post.assert_not_awaited()
    provider.client.upload_fragment.assert_not_awaited()
    assert provider.audit.await_count == 1
    assert str(provider.audit.await_args.kwargs["status"]) == "failure"


@pytest.mark.parametrize("definition", WRITES, ids=lambda value: value.name)
def test_approval_display_uses_validated_inputs_and_library_without_provider_reads(
    provider, definition
):
    name = definition.name.removeprefix("sharepoint_")
    display = definition.approval_display_args(context(writable()).deps, ARGS[name])
    assert display["_library"] == "Documents"
    assert display.get("content") == ARGS[name].get("content")
    assert display.get("name") == ARGS[name].get("name")
    with pytest.raises(ModelRetry):
        definition.approval_display_args(
            context(writable()).deps, {**ARGS[name], "unknown": "private"}
        )
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "x" * 256,
        ".",
        "..",
        " leading",
        "trailing ",
        ".leading",
        "trailing.",
        "~$temp",
        ".lock",
        "CON",
        "prn",
        "AUX.txt",
        "NUL",
        "COM0",
        "com9",
        "LPT0",
        "lpt9",
        "_vti_",
        "folder_vti_hidden",
        "desktop.ini",
        "invalid\x00",
        "invalid\n",
        "invalid\x7f",
        "invalid\u0085",
        "\ud800",
        *[f"invalid{char}name" for char in '/\\:*?"<>|'],
    ],
)
def test_name_rules_reject_invalid_names(name):
    with pytest.raises(ValidationError):
        TypeAdapter(ItemName).validate_python(name)


@pytest.mark.parametrize("name", ["A", "x" * 255, "界.txt", "notes (final).md", "summary#1.txt"])
def test_name_rules_accept_supported_names(name):
    assert TypeAdapter(ItemName).validate_python(name) == name


@pytest.mark.parametrize(
    "extension,content_type",
    [
        ("txt", "text/plain"),
        ("mmd", "text/plain"),
        ("md", "text/markdown"),
        ("markdown", "text/markdown"),
        ("mdx", "text/markdown"),
        ("csv", "text/csv"),
        ("json", "application/json"),
        ("html", "text/html"),
    ],
)
def test_text_type_comes_from_editable_file_contract(extension, content_type):
    assert text_content_type(f"notes.{extension.upper()}", operation="write_file") == content_type


@pytest.mark.parametrize("name", ["notes.docx", "notes.xlsx", "notes.png", "notes.pdf", "notes"])
async def test_nontext_extension_fails_before_credentials(provider, name):
    with pytest.raises(ModelRetry):
        await invoke("write_file", args={"name": name, "content": CONTENT})
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize("content", ["", "\x00", "\x1b", "\x7f", "\u0085", "\r", "\ud800"])
def test_text_rules_reject_controls_and_invalid_unicode(content):
    with pytest.raises(ValidationError):
        TypeAdapter(TextContent).validate_python(content)


def test_text_limit_counts_utf8_bytes_and_allows_newline_and_tab(monkeypatch):
    monkeypatch.setattr(settings, "FILES_MAX_TEXT_EDIT_BYTES", 5)
    assert TypeAdapter(TextContent).validate_python("界\n\t") == "界\n\t"
    with pytest.raises(ValidationError):
        TypeAdapter(TextContent).validate_python("界界")


async def test_upload_limit_is_checked_before_credentials(provider, monkeypatch):
    monkeypatch.setattr(sharepoint_settings, "SHAREPOINT_FILE_MAX_UPLOAD_BYTES", 1)
    with pytest.raises(ModelRetry, match="upload limit"):
        await invoke("write_file")
    provider.factory.assert_not_awaited()


@pytest.mark.parametrize(
    "input_model,args",
    [
        (CreateFolderInput, ARGS["create_folder"]),
        (WriteFileInput, ARGS["write_file"]),
        (UpdateFileInput, ARGS["update_file"]),
    ],
)
def test_input_models_forbid_unknown_fields(input_model, args):
    with pytest.raises(ValidationError):
        input_model.model_validate({**args, "source": {"file_id": str(uuid4())}})


@pytest.mark.parametrize(
    "version", ["", "x" * 201, "has space", "invalid\n", "https://example.com/secret"]
)
def test_version_tokens_are_bounded_and_pattern_checked(version):
    with pytest.raises(ValidationError):
        UpdateFileInput.model_validate({**ARGS["update_file"], "expected_version": version})


def test_write_input_reports_nontext_extension_as_typed_provider_error():
    with pytest.raises(IntegrationValidationError) as caught:
        WriteFileInput.model_validate({"name": "notes.docx", "content": CONTENT})
    assert caught.value.error_code == "unsupported_type"
    assert caught.value.operation == "write_file"
