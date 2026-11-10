# apps/api/integrations/google_ads/tools/create_keywords.py

"""Approval-only tool that adds keywords to Google Ads ad groups, each with its own list."""

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import Field
from pydantic_ai import RunContext, ToolReturn

from core.exceptions.integration import IntegrationError
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.approved_display_args import approved_display_args
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import split_fan_out_tool_return
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.edits import CriterionChange, Edit, apply_edits, prepare_edits
from ..operations.keyword_additions import LiveAdGroup, read_keyword_ad_groups
from ..operations.mutation_outcomes import GoogleAdsMutationLedger
from ..operations.read_search_terms import read_ad_group_keywords
from .schemas.ad_groups import GoogleAdsNewKeyword
from .schemas.keyword_additions import (
    MAX_KEYWORD_AD_GROUPS,
    GoogleAdsCreateKeywordsOutput,
    GoogleAdsCreateKeywordsRequest,
    GoogleAdsKeywordAddition,
)
from .utils.accounts import NOT_SHOWN, account_facts, approval_accounts, writable_entries
from .utils.ad_group_builds import STRATEGY_NAMES
from .utils.bindings import GOOGLE_ADS_WRITE_BINDING, RESULTS_FIELD
from .utils.client import google_ads_available, google_ads_client, google_ads_client_for_principal
from .utils.mutation_evidence import (
    attach_interrupted_evidence,
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)
from .utils.requests import validated_request
from .utils.routing import login_customer_id

_OPERATION = "create_keywords"
_FAMILY = "keyword_additions"
_IDENTITY = ("object",)
# Every keyword with its ad group and campaign names, for the most a call can carry.
_MAX_PUBLIC_RESULT_CHARS = 1_000_000
_MAX_MODEL_OUTCOMES = 50
# Google takes keyword criteria in standard Search and Display ad groups.
_KEYWORD_AD_GROUPS = frozenset({"SEARCH_STANDARD", "DISPLAY_STANDARD"})
_MATCH_NAMES = {"EXACT": "an exact match", "PHRASE": "a phrase match", "BROAD": "a broad match"}

_MISSING = "This ad group no longer exists in Google Ads."
_REMOVED = "This ad group has been removed, so keywords can't be added to it."
_CAMPAIGN_REMOVED = "This ad group's campaign has been removed, so keywords can't be added."
_NOT_KEYWORDS = (
    "This ad group isn't a standard Search or Display ad group, so it can't take keywords."
)
_EXISTS = "“{text}” is already {match} keyword in {ad_group}."
_BID_NOT_USED = "{campaign} uses {strategy}, so Google doesn't use a keyword max CPC."

type _Status = Literal["ENABLED", "PAUSED"]


def _edit(
    entry: GoogleAdsKeywordAddition,
    keyword: GoogleAdsNewKeyword,
    status: _Status,
    refused: str | None,
) -> CriterionChange:
    criterion: dict[str, Any] = {
        "adGroup": entry.resource_name,
        "status": status,
        "negative": False,
        "keyword": {"text": keyword.text, "matchType": keyword.match_type},
    }
    if keyword.cpc_bid_micros:
        criterion["cpcBidMicros"] = str(keyword.cpc_bid_micros)
    if keyword.final_url:
        criterion["finalUrls"] = [keyword.final_url]
    return CriterionChange(
        resource="adGroupCriterion",
        action="add",
        key=entry.key(keyword),
        owner=entry.resource_name,
        criterion=criterion,
        refused=refused,
    )


def _strategy_name(ad_group: LiveAdGroup) -> str:
    name = STRATEGY_NAMES.get(ad_group.strategy_type, "its own bidding")
    return f"a {name} portfolio strategy" if ad_group.portfolio else name


def _ad_group_problem(ad_group: LiveAdGroup | None) -> str | None:
    if ad_group is None:
        return _MISSING
    if ad_group.status == "REMOVED":
        return _REMOVED
    if ad_group.campaign_status == "REMOVED":
        return _CAMPAIGN_REMOVED
    return _NOT_KEYWORDS if ad_group.type not in _KEYWORD_AD_GROUPS else None


def _keyword_problem(
    entry: GoogleAdsKeywordAddition,
    keyword: GoogleAdsNewKeyword,
    ad_group: LiveAdGroup,
    existing: Mapping[str, str],
) -> str | None:
    if entry.key(keyword) in existing:
        return _EXISTS.format(
            text=keyword.text, match=_MATCH_NAMES[keyword.match_type], ad_group=ad_group.name
        )
    if keyword.cpc_bid and not ad_group.uses_cpc_bid:
        return _BID_NOT_USED.format(
            campaign=ad_group.campaign_name, strategy=_strategy_name(ad_group)
        )
    return None


async def google_ads_create_keywords(
    ctx: RunContext[RuntimeDeps],
    entries: Annotated[
        list[GoogleAdsKeywordAddition],
        Field(
            min_length=1,
            max_length=MAX_KEYWORD_AD_GROUPS,
            description="One entry per ad group, with the keywords to add to it.",
        ),
    ],
    status: Annotated[
        _Status,
        Field(description="PAUSED (the default) adds them off; ENABLED adds them live."),
    ] = "PAUSED",
) -> ToolReturn[dict[str, Any]]:
    request = validated_request(
        GoogleAdsCreateKeywordsRequest, {"entries": entries, "status": status}
    )
    display = approved_display_args(ctx)
    checks = display.get("_checks")
    shown: Mapping[str, Any] = checks if isinstance(checks, Mapping) else {}
    groups = display.get("_ad_groups")
    names: Mapping[str, Any] = groups if isinstance(groups, Mapping) else {}
    by_account: dict[str, list[GoogleAdsKeywordAddition]] = defaultdict(list)
    for entry in request.entries:
        by_account[entry.ad_group.customer_id].append(entry)

    async def operation(context: ResolvedContextEntry, _selected: Sequence[Any]) -> Any:
        account = by_account[context.external_id]
        client: GoogleAdsClient | None = None
        edits: list[CriterionChange] = []
        pending: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, edits, pending
            client = await google_ads_client(ctx, context)
            edits = [
                _approved_edit(entry, keyword, request.status, shown.get(entry.card_key(keyword)))
                for entry in account
                for keyword in entry.keywords
            ]
            pending = _pending_detail(context, account)
            return pending

        async def execute() -> IntegrationAuditOutcome[dict[str, Any]]:
            if client is None or pending is None or not edits:
                raise RuntimeError("Google Ads keyword addition preparation did not complete")
            try:
                result = await apply_edits(
                    client,
                    customer_id=context.external_id,
                    login_customer_id=login_customer_id(context),
                    edits=edits,
                    read=_reader(client, context, account),
                    family=_FAMILY,
                    operation=_OPERATION,
                )
            except asyncio.CancelledError as exc:
                attach_interrupted_evidence(exc, pending, identity_keys=_IDENTITY)
                raise
            detail = terminal_operation_detail(pending, result.ledger, identity_keys=_IDENTITY)
            data = _result(context, account, request.status, names, result.ledger)
            outcome_status = audit_status(detail)
            return IntegrationAuditOutcome(
                data,
                status=outcome_status,
                external_ref=",".join(result.ledger.external_refs)[:1000] or None,
                operation_detail=detail,
                unverified_result=data if outcome_status is AuditStatus.UNVERIFIED else None,
            )

        return await run_audited_integration_operation(
            ctx,
            context,
            tool_name="google_ads_create_keywords",
            operation=_OPERATION,
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=[entry.ad_group for entry in request.entries],
        operation=operation,
    )
    return split_fan_out_tool_return(results)


def _approved_edit(
    entry: GoogleAdsKeywordAddition, keyword: GoogleAdsNewKeyword, status: _Status, check: Any
) -> CriterionChange:
    """Sends a keyword only as Google checked it, and never one the card showed a problem for."""
    if (
        not isinstance(check, Mapping)
        or check.get("unavailable") is not False
        or check.get("keyword") != keyword.model_dump(mode="json")
    ):
        return _edit(entry, keyword, status, NOT_SHOWN)
    problem = check.get("problem")
    return _edit(entry, keyword, status, str(problem) if problem else None)


def _reader(
    client: GoogleAdsClient,
    context: ResolvedContextEntry,
    entries: Sequence[GoogleAdsKeywordAddition],
) -> Callable[[Sequence[Edit]], Awaitable[Mapping[str, Mapping[str, Any]]]]:
    """Reads the keywords the ad groups bid on, so one added since approval isn't added twice."""
    ad_group_ids = [entry.ad_group.ad_group_id for entry in entries]

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        existing = await read_ad_group_keywords(
            client,
            customer_id=context.external_id,
            login_customer_id=login_customer_id(context),
            ad_group_ids=ad_group_ids,
        )
        return {key: {"resourceName": name} for key, name in existing.items()}

    return read


def _pending_detail(
    context: ResolvedContextEntry, entries: Sequence[GoogleAdsKeywordAddition]
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(context),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"ad-group:{entry.ad_group.ad_group_id}:add-keywords",
                action="create",
                entity_type="google_ads_keyword",
                external_id=entry.ad_group.ad_group_id,
                display_name=entry.ad_group.label,
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "object": entry.key(keyword),
                            "text": keyword.text,
                            "match_type": keyword.match_type,
                        }
                    )
                    for keyword in entry.keywords
                ],
            )
            for entry in entries
        ],
    )


def _outcome(parent: Any) -> str:
    if parent.decision == "skipped":
        return "already_set"
    effect = parent.effects[0] if parent.effects else None
    if effect is None or effect.outcome == "unverified":
        return "unverified"
    return "added" if effect.outcome == "applied" else "failed"


def _result(
    context: ResolvedContextEntry,
    entries: Sequence[GoogleAdsKeywordAddition],
    status: _Status,
    names: Mapping[str, Any],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    """Returns every keyword for the card, and the counts with what wasn't added for the agent."""
    parents = {dict(parent.identity)["object"]: parent for parent in ledger.parents}
    keywords: list[dict[str, Any]] = []
    for entry in entries:
        seen = names.get(entry.resource_name)
        seen = seen if isinstance(seen, Mapping) else {}
        for keyword in entry.keywords:
            parent = parents[entry.key(keyword)]
            effect = parent.effects[0] if parent.effects else None
            outcome = _outcome(parent)
            keywords.append(
                {
                    "text": keyword.text,
                    "match_type": keyword.match_type,
                    "cpc_bid": keyword.cpc_bid,
                    "final_url": keyword.final_url,
                    "ad_group": entry.resource_name,
                    "ad_group_name": str(seen.get("name") or entry.ad_group.label),
                    "campaign_name": str(
                        seen.get("campaign_name") or entry.ad_group.scope_label or ""
                    ),
                    "resource_name": effect.external_ref
                    if effect is not None and outcome == "added"
                    else None,
                    "outcome": outcome,
                    "error_code": effect.error_code if effect is not None else None,
                    "message": effect.message if effect is not None else None,
                }
            )
    counts = Counter(keyword["outcome"] for keyword in keywords)
    missed = [keyword for keyword in keywords if keyword["outcome"] in {"failed", "unverified"}]
    base = {
        "account_id": context.external_id,
        "currency": account_facts(context).currency,
        "status": status,
        "counts": {
            key: counts.get(key, 0) for key in ("added", "already_set", "failed", "unverified")
        },
    }
    return {
        "display_result": {**base, "keywords": keywords, "keywords_truncated": False},
        "model_result": {
            **base,
            "keywords": missed[:_MAX_MODEL_OUTCOMES],
            "keywords_truncated": len(missed) > _MAX_MODEL_OUTCOMES,
        },
    }


async def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds each account's facts, each ad group's bidding, and per keyword its problem."""
    request = GoogleAdsCreateKeywordsRequest.model_validate(args)
    by_account: dict[str, list[GoogleAdsKeywordAddition]] = defaultdict(list)
    for entry in request.entries:
        by_account[entry.ad_group.customer_id].append(entry)
    contexts = writable_entries(deps.active_context)
    checks: dict[str, dict[str, Any]] = {}
    ad_groups: dict[str, dict[str, Any]] = {}
    for customer_id, entries in by_account.items():
        account_checks, account_groups = await _account_checks(
            deps, contexts.get(customer_id), entries, request.status
        )
        checks.update(account_checks)
        ad_groups.update(account_groups)
    accounts = approval_accounts(contexts[item] for item in by_account if item in contexts)
    return {**args, "_accounts": accounts, "_ad_groups": ad_groups, "_checks": checks}


async def _account_checks(
    deps: RuntimeDeps,
    context: ResolvedContextEntry | None,
    entries: Sequence[GoogleAdsKeywordAddition],
    status: _Status,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Reads one account's ad groups and keywords and dry runs the rest; unreadable is unavailable."""
    try:
        if context is None:
            raise LookupError("Google Ads account not selected")
        client = await google_ads_client_for_principal(
            deps.db, actor=deps.user, workspace=deps.workspace, entry=context
        )
        login = login_customer_id(context)
        ids = [entry.ad_group.ad_group_id for entry in entries]
        live = await read_keyword_ad_groups(
            client, customer_id=context.external_id, login_customer_id=login, ad_group_ids=ids
        )
        existing = await read_ad_group_keywords(
            client, customer_id=context.external_id, login_customer_id=login, ad_group_ids=ids
        )
        problems: dict[str, str | None] = {}
        for entry in entries:
            ad_group = live.get(entry.resource_name)
            shared = _ad_group_problem(ad_group)
            for keyword in entry.keywords:
                problems[entry.key(keyword)] = shared or (
                    _keyword_problem(entry, keyword, ad_group, existing) if ad_group else None
                )
        google = await _dry_run(client, context, entries, status, problems)
    except (IntegrationError, LookupError):
        return {
            entry.card_key(keyword): {"unavailable": True}
            for entry in entries
            for keyword in entry.keywords
        }, {}
    checks = {
        entry.card_key(keyword): {
            "unavailable": False,
            "keyword": keyword.model_dump(mode="json"),
            "problem": problems[entry.key(keyword)] or google.get(entry.key(keyword)),
        }
        for entry in entries
        for keyword in entry.keywords
    }
    return checks, {
        entry.resource_name: _ad_group_view(entry, live.get(entry.resource_name))
        for entry in entries
    }


async def _dry_run(
    client: GoogleAdsClient,
    context: ResolvedContextEntry,
    entries: Sequence[GoogleAdsKeywordAddition],
    status: _Status,
    problems: Mapping[str, str | None],
) -> dict[str, str]:
    """Returns Google's rejection per keyword, asking only about keywords with no problem yet."""
    edits = [
        _edit(entry, keyword, status, None)
        for entry in entries
        for keyword in entry.keywords
        if problems[entry.key(keyword)] is None
    ]
    if not edits:
        return {}

    async def read(_edits: Sequence[Edit]) -> Mapping[str, Mapping[str, Any]]:
        return {}

    prepared = await prepare_edits(
        client,
        customer_id=context.external_id,
        login_customer_id=login_customer_id(context),
        edits=edits,
        read=read,
        operation=_OPERATION,
    )
    return {edit.key: f"Google says: {edit.refused}" for edit in prepared if edit.refused}


def _ad_group_view(entry: GoogleAdsKeywordAddition, ad_group: LiveAdGroup | None) -> dict[str, Any]:
    """The ad group as the card shows it: its names, its bidding, and why it can't take keywords."""
    if ad_group is None:
        return {
            "name": entry.ad_group.label,
            "campaign_name": entry.ad_group.scope_label or "",
            "problem": _MISSING,
        }
    return {
        "name": ad_group.name,
        "campaign_name": ad_group.campaign_name,
        "status": ad_group.status,
        "campaign_status": ad_group.campaign_status,
        "strategy_name": _strategy_name(ad_group),
        "uses_cpc_bid": ad_group.uses_cpc_bid,
        "default_bid": ad_group.default_bid,
        "problem": _ad_group_problem(ad_group),
    }


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_keywords",
    function=google_ads_create_keywords,
    description=(
        "Add keywords to Google Ads ad groups in one approval: up to 50 ad groups and 1,000 "
        "keywords per call. Each entry names one ad group (a google_ads_ad_group reference) "
        "and its own keywords, each with text (at most 10 words), match_type (EXACT, PHRASE, "
        "or BROAD), and optionally cpc_bid, a max CPC in the account currency that Google uses "
        "only when the campaign uses Manual CPC, and final_url. status is PAUSED by default; "
        "use ENABLED to add them live. A keyword the ad group already has, a bid the "
        "campaign's bidding ignores, and an ad group that can't take keywords are refused. "
        "To change existing keywords use google_ads_update_keywords."
    ),
    provider="google_ads",
    label="Add Google Ads Keywords",
    code_eligible=True,
    effect=TOOL_EFFECT_WRITE,
    effect_scope=TOOL_EFFECT_SCOPE_EXTERNAL,
    egress=TOOL_EGRESS_EXTERNAL_WRITE,
    default_policy=TOOL_POLICY_APPROVAL,
    supports_auto=False,
    takes_ctx=True,
    timeout=180,
    output_model=GoogleAdsCreateKeywordsOutput,
    max_public_result_chars=_MAX_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    approval_input_model=GoogleAdsCreateKeywordsRequest,
    # An edit changes what Google has to answer, so approval waits for a new check.
    approval_review_fields=("entries",),
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Adding Keywords",
        completed_label="Added Keywords",
        failed_label="Couldn't Add Keywords",
        approval_title="Add Keywords",
        approval_prompt="The agent wants to add these keywords to your ad groups.",
        approve_label="Approve & Add",
        arg_fields=(
            ToolFieldPresentation(
                key="entries",
                label="Keywords",
                editable=True,
                format="structured",
                entity_kinds=("google_ads_ad_group",),
            ),
            ToolFieldPresentation(
                key="status", label="Status", editable=True, options=("PAUSED", "ENABLED")
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
