# apps/api/services/agents/runtime/tools/web/fetch_url.py

"""Returns one URL's content through the shared Praxis web transport, with no model call.

Every hop is validated, pinned, and denylist-checked by `services.web.fetch`. A
status such as `404` is a result; only transport failures retry. Strings from
the remote server cross dispatch as `web_fetch` provenance nodes.
"""

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ApprovalRequired, ModelRetry, RunContext, ToolReturn

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.agents.runtime.code_mode.metadata import called_from_script, script_text_max_chars
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import ENVELOPE_DENIAL_MESSAGE, ROLE_DENIAL_MESSAGE
from services.agents.runtime.entity_references.domain import (
    FileReference,
    KnowledgeDocumentReference,
)
from services.agents.runtime.tools import (
    TOOL_EGRESS_ARBITRARY_URL,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.agents.runtime.tools.web.nodes import WebRedirect, redirect_nodes, untrusted
from services.agents.runtime.untrusted import UntrustedNode
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.integrations.files.create_copy import create_copy
from services.kb.create_document import create_kb_document
from services.kb.domain import KB_DOCUMENT_TITLE_MAX_CHARS, KB_SOURCE_URL
from services.kb.write_policy import KBProvenance
from services.web import fetch_url as fetch_public_url, read_page
from services.web.domain import FetchedResponse, UserAgent, WebFetchError
from services.web.read_page import DropKind, OutputFormat, PageContent, PagePart, ReturnedFormat
from services.web.utils import configured_blocked_domains, file_content_type, page_file_name
from services.workspaces.utils import EDITOR_ROLES
from utils.document_markdown import DocumentConversionError

_DEFAULT_DROP: tuple[DropKind, ...] = ("styles", "svg", "comments", "data_uris")
_HTML_ONLY_PARTS = frozenset({"head", "full"})
# The transcript copy of a script's fetch: the model-sized cut plus headroom for escaping and hops.
_MAX_PUBLIC_RESULT_CHARS = 6 * (settings.AGENT_TOOL_RESULT_MAX_CHARS or 0) + 200_000


class FetchUrlOutput(BaseModel):
    """Model-visible result returned by `fetch_url`."""

    provider: Literal["http"]
    requested_url: str
    final_url: UntrustedNode
    status: int
    redirects: list[WebRedirect]
    blocked_by_site: bool = Field(
        description="True when the site refused an automated request, not a broken page."
    )
    user_agent: UserAgent
    content_type: UntrustedNode
    format: ReturnedFormat
    title: UntrustedNode | None
    fetched_at: str
    bytes: int = Field(description="Bytes of the response body.")
    truncated: bool
    content: UntrustedNode | None
    note: str | None = Field(description="Guidance about this result, such as a cut or a refusal.")
    file: FileReference | None
    knowledge_base_document: KnowledgeDocumentReference | None


@runtime_tool(
    name="fetch_url",
    provider="web",
    label="Fetch URL",
    code_eligible=True,
    description=(
        "Fetch one public URL and return its content, status, and redirects, with no model "
        "cost. A 404 or 500 returns normally with its status; blocked_by_site means the site "
        "refused an automated request. HTML returns as markdown of the main content by "
        "default. Use part='body' to keep the header, navigation, footer, and links; use "
        "format='html' with part='head' for meta tags, or part='full' for the whole source. "
        "Text, JSON, XML, feeds, JavaScript, and CSS return verbatim; PDF and Office files "
        f"return as markdown. Content over {settings.AGENT_TOOL_RESULT_MAX_CHARS:,} "
        "characters is cut: set save_to_files and read the File in windows instead. In "
        "run_code the script gets the whole text, so parse long pages and sitemaps there. "
        "Set add_to_knowledge_base only when the user wants the page kept and refreshed "
        "in the Knowledge Base; that waits for approval. Use ask_url to answer a question "
        "about a page with a helper model instead."
    ),
    supports_approval=True,
    supports_auto=True,
    default_policy=TOOL_POLICY_AUTO,
    egress=TOOL_EGRESS_ARBITRARY_URL,
    takes_ctx=True,
    timeout=None,
    output_model=FetchUrlOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    presentation=ToolPresentation(
        icon="link",
        running_label="Fetching {url}",
        completed_label="Fetched {url}",
        failed_label="Couldn't Fetch URL",
        approval_title="Fetch URL",
        approval_prompt="The agent wants to fetch this URL: {url}.",
        approve_label="Approve & Fetch",
        arg_fields=(
            ToolFieldPresentation(
                key="url",
                label="URL",
                editable=True,
                placeholder="https://example.com/page",
            ),
            ToolFieldPresentation(
                key="add_to_knowledge_base",
                label="Add to Knowledge Base",
                format="boolean",
                editable=True,
            ),
            ToolFieldPresentation(key="save_to_files", label="Save to Files", format="boolean"),
            ToolFieldPresentation(key="format", label="Format", secondary=True),
            ToolFieldPresentation(key="part", label="Part", secondary=True),
            ToolFieldPresentation(key="user_agent", label="Browser", secondary=True),
        ),
    ),
)
async def fetch_url(
    ctx: RunContext[RuntimeDeps],
    url: Annotated[str, Field(min_length=1, max_length=2_048, description="HTTP(S) URL.")],
    format: Annotated[OutputFormat, Field(description="markdown, text, or html.")] = "markdown",
    part: Annotated[
        PagePart,
        Field(
            description=(
                "main (default, page chrome removed), body (everything in the body), head "
                "(html only), or full (the whole document, html only)."
            )
        ),
    ] = "main",
    drop: Annotated[
        list[DropKind] | None,
        Field(
            description=(
                "For html: what to leave out. Omit to drop styles, svg, comments, and "
                "data_uris; pass [] for the source as served."
            )
        ),
    ] = None,
    user_agent: Annotated[
        UserAgent,
        Field(
            description=(
                "praxis (default, an honest agent), desktop_browser, mobile_browser, "
                "googlebot_desktop, or googlebot_mobile. Googlebot presets only change the "
                "header; sites that verify Googlebot by address still treat the request as "
                "a stranger."
            )
        ),
    ] = "praxis",
    save_to_files: Annotated[
        bool, Field(description="Also save the response body to workspace Files.")
    ] = False,
    add_to_knowledge_base: Annotated[
        bool,
        Field(description="Also add the URL as a refreshed Knowledge Base source. Needs approval."),
    ] = False,
    provider: Annotated[Literal["http"], Field(description="Fetch backend.")] = "http",
) -> dict[str, Any] | ToolReturn:
    """Fetches one URL and optionally saves it to Files or the Knowledge Base."""
    if part in _HTML_ONLY_PARTS and format != "html":
        raise ModelRetry(f"part='{part}' needs format='html'.")
    if save_to_files or add_to_knowledge_base:
        _require_write(ctx.deps)
    if add_to_knowledge_base and not ctx.tool_call_approved:
        raise ApprovalRequired(metadata={"url": url, "add_to_knowledge_base": True})
    if not ctx.deps.web_fetch_budget.take():
        raise ModelRetry(
            f"This run has fetched its limit of {ctx.deps.web_fetch_budget.max_urls} URLs."
        )

    response, page = await _fetch_and_read(
        ctx.deps,
        url,
        output_format=format,
        part=part,
        drop=_DEFAULT_DROP if drop is None else tuple(drop),
        user_agent=user_agent,
    )
    file, file_note = await _save_to_files(ctx.deps, response) if save_to_files else (None, None)
    document = (
        await _add_to_knowledge_base(ctx.deps, response, page) if add_to_knowledge_base else None
    )
    shown = _result(response, page, settings.AGENT_TOOL_RESULT_MAX_CHARS, file, file_note, document)
    if not called_from_script(ctx) or not shown["truncated"]:
        return shown
    # A script reads the whole text; the transcript keeps the model-sized cut.
    full = _result(response, page, script_text_max_chars(), file, file_note, document)
    return ToolReturn(return_value=full, metadata={"public_result": shown})


def _result(
    response: FetchedResponse,
    page: PageContent,
    limit: int | None,
    file: dict[str, Any] | None,
    file_note: str | None,
    document: dict[str, Any] | None,
) -> dict[str, Any]:
    content, truncated = _bounded(page.content, limit)
    notes = (_page_note(response, page, truncated, limit), file_note)
    return {
        "provider": "http",
        "requested_url": response.requested_url,
        "final_url": untrusted(response.requested_url, response.final_url),
        "status": response.status,
        "redirects": redirect_nodes(response.requested_url, response.redirects),
        "blocked_by_site": response.blocked_by_site,
        "user_agent": response.user_agent,
        "content_type": untrusted(response.requested_url, response.content_type),
        "format": page.format,
        "title": untrusted(response.requested_url, page.title) if page.title else None,
        "fetched_at": datetime.now(UTC).isoformat(),
        "bytes": len(response.body),
        "truncated": truncated,
        "content": untrusted(response.requested_url, content) if content is not None else None,
        "note": " ".join(note for note in notes if note) or None,
        "file": file,
        "knowledge_base_document": document,
    }


def _require_write(deps: RuntimeDeps) -> None:
    if deps.envelope.side_effect_policy == "deny":
        raise ModelRetry(ENVELOPE_DENIAL_MESSAGE)
    if deps.membership.role not in EDITOR_ROLES:
        raise ModelRetry(ROLE_DENIAL_MESSAGE)


async def _fetch_and_read(
    deps: RuntimeDeps,
    url: str,
    *,
    output_format: OutputFormat,
    part: PagePart,
    drop: tuple[DropKind, ...],
    user_agent: UserAgent,
) -> tuple[FetchedResponse, PageContent]:
    # One deadline covers resolution, redirects, reading, and conversion.
    try:
        async with asyncio.timeout(settings.WEB_FETCH_TIMEOUT_SECONDS):
            response = await fetch_public_url(
                url,
                timeout_seconds=settings.WEB_FETCH_TIMEOUT_SECONDS,
                max_redirects=settings.WEB_FETCH_MAX_REDIRECTS,
                max_bytes=settings.WEB_FETCH_MAX_BYTES,
                user_agent=user_agent,
                gunzip=True,
                standard_ports_only=True,
                blocked_domains=configured_blocked_domains(),
                limiter=deps.web_fetch_budget.limiter,
            )
            try:
                page = await read_page(response, output_format=output_format, part=part, drop=drop)
            except DocumentConversionError:
                page = PageContent(format="unsupported", content=None)
    except WebFetchError as exc:
        raise ModelRetry(
            f"fetch_url couldn't fetch that URL ({exc.error_class}): {exc.message}."
        ) from None
    except TimeoutError:
        raise ModelRetry("fetch_url couldn't fetch that URL (timeout): it took too long.") from None
    return response, page


def _bounded(content: str | None, limit: int | None) -> tuple[str | None, bool]:
    if content is None or limit is None or len(content) <= limit:
        return content, False
    return content[:limit], True


def _page_note(
    response: FetchedResponse, page: PageContent, truncated: bool, limit: int | None
) -> str | None:
    if response.blocked_by_site:
        return "The site refused an automated request; the page itself may be fine."
    if page.format == "unsupported":
        return "fetch_url doesn't return this content type; content_type names it."
    if truncated:
        return (
            f"The content was cut at {limit or 0:,} characters. "
            "Set save_to_files and read the File in windows for the rest."
        )
    return None


async def _save_to_files(
    deps: RuntimeDeps, response: FetchedResponse
) -> tuple[dict[str, Any] | None, str | None]:
    content_type = file_content_type(response)
    if content_type is None:
        return None, "Only a page or document that loads successfully is saved to Files."
    try:
        # A File that can't be saved rolls back alone, and the fetch result still returns.
        async with deps.db.begin_nested():
            saved = await create_copy(
                deps.db,
                workspace=deps.workspace,
                user=deps.user,
                conversation_id=deps.conversation.id,
                agent=deps.agent,
                # Trusted fields name pages by the requested URL; redirects are server-chosen.
                name=page_file_name(response.requested_url),
                content=response.body,
                content_type=content_type,
            )
    except AppValidationError as exc:
        return None, f"The page wasn't saved to Files. {exc.message}"
    reference = FileReference(entity_id=saved.file.id, label=saved.file.name)
    return reference.model_dump(mode="json"), None


async def _add_to_knowledge_base(
    deps: RuntimeDeps, response: FetchedResponse, page: PageContent
) -> dict[str, Any]:
    title = (page.title or page_file_name(response.requested_url))[:KB_DOCUMENT_TITLE_MAX_CHARS]
    try:
        async with deps.db.begin_nested():
            # The source is the requested URL; the Knowledge Base worker fetches and refreshes it.
            document = await create_kb_document(
                deps.db,
                workspace_id=deps.workspace.id,
                source_type=KB_SOURCE_URL,
                title=title,
                created_by_user_id=deps.user.id,
                url=response.requested_url,
                provenance=KBProvenance(
                    actor_kind="agent",
                    user_id=deps.user.id,
                    agent_id=deps.agent.id,
                    run_id=deps.run.id,
                    source_type=KB_SOURCE_URL,
                    origin_ref=response.requested_url,
                ),
            )
            await record_workspace_audit_event(
                deps.db,
                request=None,
                workspace_id=deps.workspace.id,
                action=AuditAction.CREATE,
                resource_type=AuditResourceType.KB_DOCUMENT,
                resource_id=document.id,
                actor=deps.user,
                details={
                    "source_type": KB_SOURCE_URL,
                    "is_private": False,
                    "agent_id": str(deps.agent.id),
                    "run_id": str(deps.run.id),
                },
            )
    except AppValidationError as exc:
        raise ModelRetry(f"The URL wasn't added to the Knowledge Base. {exc.message}") from None
    # The page title stays out of the model-visible label; it is server-controlled.
    label = page_file_name(response.requested_url)
    return KnowledgeDocumentReference(entity_id=document.id, label=label).model_dump(mode="json")
