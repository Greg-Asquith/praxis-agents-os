# apps/api/integrations/google_ads/tools/create_positive_keywords.py

"""Approval-only Google Ads positive-keyword creation tool."""

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.create_positive_keywords import (
    MAX_POSITIVE_KEYWORD_OPERATIONS,
    GoogleAdsPositiveKeywordCreate,
    create_positive_keywords,
    positive_keyword_creation_failure_ledger,
    positive_keyword_pair_key,
)
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.list_positive_keywords import list_positive_keyword_pairs
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsKeywordReference,
    positive_keyword_reference_from_row,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_SCOPE_EXTERNAL,
    TOOL_EFFECT_WRITE,
    TOOL_EGRESS_EXTERNAL_WRITE,
    TOOL_POLICY_APPROVAL,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    AuditStatus,
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    PendingIntegrationOperationDetail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.targeted import run_context_targets
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from .schemas import GoogleAdsCreatePositiveKeywordsOutput, GoogleAdsPositiveKeywordEntry
from .schemas.positive_keywords import money_bid_to_micros
from .utils import (
    GOOGLE_ADS_WRITE_BINDING,
    MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    RESULTS_FIELD,
    bounded_positive_keyword_result,
    display_positive_keyword_result,
    fan_out_tool_return,
    google_ads_available,
    google_ads_client,
    login_customer_id,
)
from .utils.money import micros_to_money
from .utils.mutation_evidence import (
    audit_status,
    google_ads_account_target,
    terminal_operation_detail,
)

_RESOURCE_PATTERN = re.compile(
    r"customers/\d{1,32}/adGroupCriteria/\d{1,32}~(?P<criterion>\d{1,32})"
)
_MAX_EXPANDED_CONFIGURATION_CHARS = 300_000


@dataclass(frozen=True, slots=True)
class _KeywordCreateContext:
    strategy: str
    channel: str
    ad_group_type: str
    display_custom_bid_dimension: str


@dataclass(frozen=True, slots=True)
class _PositiveKeywordEligibility:
    ad_group_type: str
    cpc_strategy: str
    cpc_custom_bid_dimension: str | None = None


# The Google Ads API v24 campaign structure and criterion-simulation references
# support keyword criteria for standard Search and Display ad groups. Google Ads
# permits keyword custom bids but not keyword bid adjustments, explicitly rejects
# keyword-level CPM, and uses CPV/Percent CPC with non-keyword campaign types.
_POSITIVE_KEYWORD_ELIGIBILITY = {
    "SEARCH": _PositiveKeywordEligibility(
        ad_group_type="SEARCH_STANDARD",
        cpc_strategy="MANUAL_CPC",
    ),
    "DISPLAY": _PositiveKeywordEligibility(
        ad_group_type="DISPLAY_STANDARD",
        cpc_strategy="MANUAL_CPC",
        cpc_custom_bid_dimension="KEYWORD",
    ),
}


async def google_ads_create_keywords(
    ctx: RunContext[RuntimeDeps],
    ad_groups: Annotated[
        list[GoogleAdsAdGroupReference],
        Field(min_length=1, max_length=50, description="Ad groups to receive the keywords."),
    ],
    keywords: Annotated[
        list[GoogleAdsPositiveKeywordEntry],
        Field(min_length=1, max_length=500, description="Positive keyword rows to add."),
    ],
) -> ToolReturn[dict[str, Any]]:
    selected_ad_groups, normalized_keywords = _validate_args(ad_groups, keywords)

    async def operation(
        entry: ResolvedContextEntry,
        references: Sequence[GoogleAdsAdGroupReference],
    ) -> Any:
        client = None
        live_references: list[GoogleAdsAdGroupReference] = []
        existing_rows: list[Mapping[str, Any]] = []
        creates: list[GoogleAdsPositiveKeywordCreate] = []
        pending_detail: PendingIntegrationOperationDetail | None = None

        async def prepare_pending_operation() -> PendingIntegrationOperationDetail:
            nonlocal client, live_references, existing_rows, creates, pending_detail
            client = await google_ads_client(ctx, entry)
            live_references, create_contexts = await _live_ad_groups(client, entry, references)
            _validate_bid_compatibility(create_contexts, normalized_keywords)
            creates = _expanded_creates(live_references, normalized_keywords)
            existing_rows = await list_positive_keyword_pairs(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                keyword_targets=[
                    (reference.ad_group_id, keyword.text, keyword.match_type)
                    for reference in live_references
                    for keyword in normalized_keywords
                ],
            )
            pending_detail = _pending_operation_detail(entry, live_references, normalized_keywords)
            return pending_detail

        async def execute() -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
            if client is None or pending_detail is None or not creates:
                raise RuntimeError("Positive keyword creation preparation did not complete")
            try:
                ledger = await create_positive_keywords(
                    client,
                    customer_id=entry.external_id,
                    login_customer_id=login_customer_id(entry),
                    creates=creates,
                    existing_rows=existing_rows,
                )
            except asyncio.CancelledError as exc:
                disposition = getattr(
                    exc,
                    "failure_disposition",
                    IntegrationFailureDisposition.NOT_DISPATCHED,
                )
                exception_outcome = _exception_outcome(
                    live_references,
                    creates,
                    existing_rows,
                    pending_detail,
                    exc,
                    currency_code=_currency_code(entry),
                    disposition=disposition,
                )
                exc.failure_disposition = disposition
                exc.operation_detail = exception_outcome.operation_detail
                raise
            except Exception as exc:
                disposition = getattr(exc, "failure_disposition", None)
                if disposition is None:
                    disposition = IntegrationFailureDisposition.AMBIGUOUS
                return _exception_outcome(
                    live_references,
                    creates,
                    existing_rows,
                    pending_detail,
                    exc,
                    currency_code=_currency_code(entry),
                    disposition=disposition,
                )
            detail = terminal_operation_detail(
                pending_detail,
                ledger,
                identity_keys=("ad_group_id", "text", "match_type"),
            )
            status = audit_status(detail)
            return IntegrationAuditOutcome(
                ledger,
                status=status,
                external_ref=",".join(ledger.external_refs) or None,
                operation_detail=detail,
                unverified_result=(
                    _split_result(entry, live_references, existing_rows, ledger)
                    if status is AuditStatus.UNVERIFIED
                    else None
                ),
            )

        ledger = await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_create_keywords",
            operation="create_positive_keywords",
            execute=execute,
            prepare_pending_operation=prepare_pending_operation,
        )
        return _split_result(entry, live_references, existing_rows, ledger)

    results = await run_context_targets(
        ctx,
        binding=GOOGLE_ADS_WRITE_BINDING,
        references=selected_ad_groups,
        operation=operation,
    )
    return fan_out_tool_return(results)


def _validate_args(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[GoogleAdsPositiveKeywordEntry],
) -> tuple[list[GoogleAdsAdGroupReference], list[GoogleAdsPositiveKeywordEntry]]:
    if not ad_groups:
        raise ModelRetry("Choose at least one Google Ads ad group.")
    if len(ad_groups) > 50:
        raise ModelRetry("Choose at most 50 Google Ads ad groups per call.")
    if not keywords:
        raise ModelRetry("Add at least one positive keyword row.")
    if len(keywords) > 500:
        raise ModelRetry("Add at most 500 positive keyword rows per call.")
    unique_ad_groups: dict[tuple[str, str], GoogleAdsAdGroupReference] = {}
    for reference in ad_groups:
        unique_ad_groups.setdefault((reference.customer_id, reference.ad_group_id), reference)
    if len(unique_ad_groups) != len(ad_groups):
        raise ModelRetry("Choose each Google Ads ad group only once.")
    normalized_keywords = list(keywords)
    keyword_keys = [
        positive_keyword_pair_key("", keyword.text, keyword.match_type)
        for keyword in normalized_keywords
    ]
    if len(set(keyword_keys)) != len(keyword_keys):
        raise ModelRetry("Each normalized keyword and match type can appear only once.")
    if len(unique_ad_groups) * len(normalized_keywords) > MAX_POSITIVE_KEYWORD_OPERATIONS:
        raise ModelRetry(
            "Ad groups multiplied by keyword rows must not exceed 2,500. "
            "Split the request into smaller groups."
        )
    configuration_chars = len(unique_ad_groups) * sum(
        len(
            json.dumps(
                keyword.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        for keyword in normalized_keywords
    )
    if configuration_chars > _MAX_EXPANDED_CONFIGURATION_CHARS:
        raise ModelRetry(
            "The expanded keyword configuration is too large to retain exact approval evidence. "
            "Split the request into smaller groups."
        )
    return list(unique_ad_groups.values()), normalized_keywords


async def _live_ad_groups(
    client,
    entry: ResolvedContextEntry,
    selected: Sequence[GoogleAdsAdGroupReference],
) -> tuple[list[GoogleAdsAdGroupReference], dict[str, _KeywordCreateContext]]:
    ids = [reference.ad_group_id for reference in selected]
    rows = await list_ad_groups(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        ad_group_ids=ids,
        limit=len(ids),
        exclude_removed=True,
    )
    live_by_id: dict[str, GoogleAdsAdGroupReference] = {}
    contexts: dict[str, _KeywordCreateContext] = {}
    for row in rows:
        campaign = row.get("campaign")
        ad_group = row.get("adGroup")
        if not isinstance(campaign, Mapping) or not isinstance(ad_group, Mapping):
            continue
        ad_group_id = str(ad_group.get("id", ""))
        campaign_id = str(campaign.get("id", ""))
        status = str(ad_group.get("status", ""))
        if ad_group_id.isdigit() and campaign_id.isdigit() and status != "REMOVED":
            live_by_id[ad_group_id] = GoogleAdsAdGroupReference(
                customer_id=entry.external_id,
                campaign_id=campaign_id,
                ad_group_id=ad_group_id,
                label=str(ad_group.get("name", "")).strip() or "(unnamed ad group)",
                description=status.title() if status else "Ad group",
                scope_label=str(campaign.get("name", "")).strip() or "(unnamed campaign)",
                status=status or None,
            )
            contexts[ad_group_id] = _KeywordCreateContext(
                strategy=str(campaign.get("biddingStrategyType", "")),
                channel=str(campaign.get("advertisingChannelType", "")),
                ad_group_type=str(ad_group.get("type", "")),
                display_custom_bid_dimension=str(ad_group.get("displayCustomBidDimension", "")),
            )
    if set(live_by_id) != set(ids):
        raise ModelRetry(
            "A selected Google Ads ad group is unavailable. Ask the user to choose it again."
        )
    return [live_by_id[reference.ad_group_id] for reference in selected], contexts


def _validate_bid_compatibility(
    contexts: Mapping[str, _KeywordCreateContext],
    keywords: Sequence[GoogleAdsPositiveKeywordEntry],
) -> None:
    requests_cpc_bid = any(keyword.cpc_bid is not None for keyword in keywords)
    for ad_group_id, context in contexts.items():
        eligibility = _POSITIVE_KEYWORD_ELIGIBILITY.get(context.channel)
        if eligibility is None or context.ad_group_type != eligibility.ad_group_type:
            raise ModelRetry(
                f"Ad group {ad_group_id} cannot accept positive keyword criteria with its live "
                f"{context.channel or 'unknown'} channel and "
                f"{context.ad_group_type or 'unknown'} ad-group type. Choose a Search standard "
                "or Display standard ad group."
            )
        cpc_compatible = context.strategy == eligibility.cpc_strategy and (
            eligibility.cpc_custom_bid_dimension is None
            or context.display_custom_bid_dimension == eligibility.cpc_custom_bid_dimension
        )
        if requests_cpc_bid and not cpc_compatible:
            dimension = context.display_custom_bid_dimension or "unknown"
            raise ModelRetry(
                f"Ad group {ad_group_id} cannot use the requested CPC bid with its live "
                f"{context.strategy or 'unknown'} bidding strategy, {context.channel} channel, "
                f"and {dimension} custom bid dimension. Remove the CPC bid or choose a compatible "
                "ad group."
            )


def _expanded_creates(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[GoogleAdsPositiveKeywordEntry],
) -> list[GoogleAdsPositiveKeywordCreate]:
    return [
        GoogleAdsPositiveKeywordCreate(
            ad_group_id=ad_group.ad_group_id,
            text=keyword.text,
            match_type=keyword.match_type,
            status=keyword.status,
            cpc_bid_micros=money_bid_to_micros(keyword.cpc_bid, label="CPC bid")
            if keyword.cpc_bid
            else None,
            final_urls=tuple(keyword.final_urls or ()),
            final_mobile_urls=tuple(keyword.final_mobile_urls or ()),
            final_url_suffix=keyword.final_url_suffix,
            tracking_url_template=keyword.tracking_url_template,
            url_custom_parameters=tuple(sorted((keyword.url_custom_parameters or {}).items())),
        )
        for ad_group in ad_groups
        for keyword in keywords
    ]


def _pending_operation_detail(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[GoogleAdsPositiveKeywordEntry],
) -> PendingIntegrationOperationDetail:
    return PendingIntegrationOperationDetail(
        target=google_ads_account_target(entry),
        intent_groups=[
            IntegrationOperationIntentGroup(
                key=f"ad-group:{ad_group.ad_group_id}:create-positive-keywords",
                action="create",
                entity_type="google_ads_positive_keyword_batch",
                external_id=ad_group.ad_group_id,
                display_name=ad_group.label,
                fields={
                    "ad_group_id": ad_group.ad_group_id,
                    "ad_group_name": ad_group.label,
                    "campaign_id": ad_group.campaign_id,
                    "campaign_name": ad_group.scope_label or "",
                },
                items=[
                    IntegrationOperationIntent(
                        fields={
                            "text": keyword.text,
                            "match_type": keyword.match_type,
                            **keyword.model_dump(
                                mode="json",
                                exclude={"text", "match_type"},
                                exclude_none=True,
                            ),
                        }
                    )
                    for keyword in keywords
                ],
            )
            for ad_group in ad_groups
        ],
    )


def _split_result(
    entry: ResolvedContextEntry,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    existing_rows: Sequence[Mapping[str, Any]],
    ledger: GoogleAdsMutationLedger,
) -> dict[str, Any]:
    rows = _result_rows(ad_groups, existing_rows, ledger)
    currency_code = _currency_code(entry)
    return {
        "model_result": bounded_positive_keyword_result(rows, currency_code=currency_code),
        "display_result": display_positive_keyword_result(rows, currency_code=currency_code),
    }


def _result_rows(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    existing_rows: Sequence[Mapping[str, Any]],
    ledger: GoogleAdsMutationLedger,
) -> list[dict[str, Any]]:
    ad_groups_by_id = {reference.ad_group_id: reference for reference in ad_groups}
    existing = _existing_references(existing_rows, ad_groups_by_id)
    rows: list[dict[str, Any]] = []
    for parent in ledger.parents:
        fields = thaw_fields(parent.identity)
        ad_group = ad_groups_by_id.get(fields["ad_group_id"])
        if ad_group is None:
            raise ValueError("Google Ads returned contradictory positive keyword accounting")
        key = positive_keyword_pair_key(ad_group.ad_group_id, fields["text"], fields["match_type"])
        requested_micros = fields.get("cpc_bid_micros")
        requested = {
            "text": fields["text"],
            "match_type": fields["match_type"],
            "status": fields["status"],
            "cpc_bid": micros_to_money(int(requested_micros)) if requested_micros else None,
            "cpc_bid_micros": requested_micros,
            "final_urls": json.loads(fields.get("final_urls", "[]")),
            "final_mobile_urls": json.loads(fields.get("final_mobile_urls", "[]")),
            "final_url_suffix": fields.get("final_url_suffix"),
            "tracking_url_template": fields.get("tracking_url_template"),
            "url_custom_parameters": [
                {"key": parameter_key, "value": value}
                for parameter_key, value in json.loads(
                    fields.get("url_custom_parameters", "{}")
                ).items()
            ],
        }
        row: dict[str, Any] = {
            "campaign_id": ad_group.campaign_id,
            "campaign_name": (ad_group.scope_label or "")[:80],
            "ad_group_id": ad_group.ad_group_id,
            "ad_group_name": ad_group.label[:80],
            "requested": requested,
        }
        if parent.decision == "skipped":
            keyword = existing.get(key)
            if keyword is None:
                raise ValueError("Google Ads skipped keyword evidence is unavailable")
            observed, observed_truncated = _requested_state_from_reference(keyword)
            row.update(
                previous_state="existing",
                outcome="skipped_existing",
                observed=observed,
                observed_truncated=observed_truncated,
                keyword=keyword,
                external_ref=(
                    f"customers/{keyword.customer_id}/adGroupCriteria/"
                    f"{keyword.ad_group_id}~{keyword.criterion_id}"
                ),
            )
        else:
            effect = parent.effects[0]
            outcome = "added" if effect.outcome == "applied" else effect.outcome
            row.update(
                previous_state="absent",
                outcome=outcome,
                external_ref=effect.external_ref,
                error_code=effect.error_code[:60] if effect.error_code else None,
                message=effect.message[:120] if effect.message else None,
            )
            if effect.outcome == "applied" and effect.external_ref:
                match = _RESOURCE_PATTERN.fullmatch(effect.external_ref)
                if match is None:
                    raise ValueError("Google Ads returned an invalid positive keyword reference")
                row["keyword"] = GoogleAdsKeywordReference(
                    customer_id=ad_group.customer_id,
                    campaign_id=ad_group.campaign_id,
                    ad_group_id=ad_group.ad_group_id,
                    criterion_id=match.group("criterion"),
                    text=fields["text"],
                    match_type=fields["match_type"],
                    status=fields["status"],
                    cpc_bid_micros=int(requested_micros) if requested_micros else None,
                    final_urls=requested["final_urls"],
                    final_mobile_urls=requested["final_mobile_urls"],
                    final_url_suffix=requested["final_url_suffix"],
                    tracking_url_template=requested["tracking_url_template"],
                    url_custom_parameters=requested["url_custom_parameters"],
                    label=fields["text"],
                    description=f"{fields['match_type'].title()} · {fields['status'].title()}",
                    scope_label=f"{ad_group.scope_label or ''} · {ad_group.label}".strip(" ·"),
                )
        rows.append(row)
    return rows


def _requested_state_from_reference(
    reference: GoogleAdsKeywordReference,
) -> tuple[dict[str, Any], bool]:
    final_urls = [value[:80] for value in reference.final_urls[:1]]
    truncated = (
        final_urls != reference.final_urls
        or bool(reference.final_mobile_urls)
        or reference.final_url_suffix is not None
        or reference.tracking_url_template is not None
        or bool(reference.url_custom_parameters)
    )
    return {
        "text": reference.text,
        "match_type": reference.match_type,
        "status": reference.status,
        "cpc_bid": (
            micros_to_money(reference.cpc_bid_micros)
            if reference.cpc_bid_micros is not None
            else None
        ),
        "cpc_bid_micros": (
            str(reference.cpc_bid_micros) if reference.cpc_bid_micros is not None else None
        ),
        "final_urls": final_urls,
        "final_mobile_urls": [],
        "final_url_suffix": None,
        "tracking_url_template": None,
        "url_custom_parameters": [],
    }, truncated


def _existing_references(
    rows: Sequence[Mapping[str, Any]],
    ad_groups: Mapping[str, GoogleAdsAdGroupReference],
) -> dict[tuple[str, str, str], GoogleAdsKeywordReference]:
    references: dict[tuple[str, str, str], GoogleAdsKeywordReference] = {}
    for row in rows:
        ad_group = row.get("adGroup")
        if not isinstance(ad_group, Mapping):
            continue
        ad_group_id = str(ad_group.get("id", ""))
        selected = ad_groups.get(ad_group_id)
        reference = (
            positive_keyword_reference_from_row(selected.customer_id, row)
            if selected is not None
            else None
        )
        if (
            reference is None
            or reference.campaign_id != selected.campaign_id
            or reference.ad_group_id != selected.ad_group_id
        ):
            continue
        references.setdefault(
            positive_keyword_pair_key(ad_group_id, reference.text, reference.match_type),
            reference,
        )
    return references


def _exception_outcome(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    creates: Sequence[GoogleAdsPositiveKeywordCreate],
    existing_rows: Sequence[Mapping[str, Any]],
    pending_detail: PendingIntegrationOperationDetail,
    exc: BaseException,
    *,
    currency_code: str,
    disposition: IntegrationFailureDisposition,
) -> IntegrationAuditOutcome[GoogleAdsMutationLedger]:
    ambiguous = disposition is IntegrationFailureDisposition.AMBIGUOUS
    raw_message = exc.user_message if isinstance(exc, IntegrationError) else str(exc)
    ledger = positive_keyword_creation_failure_ledger(
        creates,
        customer_id=ad_groups[0].customer_id,
        outcome="unverified" if ambiguous else "failed",
        error_code=exc.__class__.__name__[:100],
        message=" ".join(raw_message.split())[:1000] or "Positive keyword creation failed",
        existing_rows=existing_rows,
    )
    detail = terminal_operation_detail(
        pending_detail,
        ledger,
        identity_keys=("ad_group_id", "text", "match_type"),
    )
    rows = _result_rows(ad_groups, existing_rows, ledger)
    return IntegrationAuditOutcome(
        ledger,
        status=audit_status(detail),
        operation_detail=detail,
        unverified_result=(
            {
                "model_result": bounded_positive_keyword_result(
                    rows,
                    currency_code=currency_code,
                ),
                "display_result": display_positive_keyword_result(
                    rows,
                    currency_code=currency_code,
                ),
            }
            if ambiguous
            else None
        ),
    )


def _currency_code(entry: ResolvedContextEntry) -> str:
    currency_code = str(entry.permissions_metadata.get("currency_code", "")).strip()
    if not currency_code:
        raise ValueError("Google Ads positive keyword result requires an account currency")
    return currency_code


def _approval_display_args(deps: RuntimeDeps, args: dict[str, Any]) -> dict[str, Any]:
    """Adds trusted account currencies to the approval argument projection."""
    selected = args.get("ad_groups")
    customer_ids = (
        {
            str(value.get("customer_id"))
            for value in selected
            if isinstance(selected, list) and isinstance(value, Mapping)
        }
        if isinstance(selected, list)
        else set()
    )
    entries = (
        deps.active_context.compatible_entries(GOOGLE_ADS_WRITE_BINDING)
        if deps.active_context
        else ()
    )
    accounts = [
        {
            "customer_id": entry.external_id,
            "label": entry.display_name,
            "currency_code": str(entry.permissions_metadata["currency_code"]).strip(),
        }
        for entry in entries
        if entry.external_id in customer_ids
        and entry.write_allowed
        and isinstance(entry.permissions_metadata.get("currency_code"), str)
        and str(entry.permissions_metadata["currency_code"]).strip()
    ]
    if customer_ids and {account["customer_id"] for account in accounts} != customer_ids:
        raise RuntimeError("Google Ads positive keyword approval requires account currencies")
    keywords = args.get("keywords")
    optional_defaults: dict[str, object] = {
        "status": "ENABLED",
        "cpc_bid": "",
        "final_urls": [],
        "final_mobile_urls": [],
        "final_url_suffix": "",
        "tracking_url_template": "",
        "url_custom_parameters": {},
    }
    display_keywords = (
        [
            {**optional_defaults, **keyword} if isinstance(keyword, Mapping) else keyword
            for keyword in keywords
        ]
        if isinstance(keywords, list)
        else keywords
    )
    return {**args, "keywords": display_keywords, "_account_currencies": accounts}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_create_keywords",
    function=google_ads_create_keywords,
    description=(
        "Add operator-selected positive keywords to selected Google Ads ad groups. "
        "This tool does not select, recommend, or classify keywords or match types."
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
    timeout=60,
    output_model=GoogleAdsCreatePositiveKeywordsOutput,
    max_public_result_chars=MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS,
    integration_binding=GOOGLE_ADS_WRITE_BINDING,
    availability_check=google_ads_available,
    approval_display_args=_approval_display_args,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Adding Keywords",
        completed_label="Added Keywords",
        failed_label="Couldn't Add Keywords",
        approval_title="Add Google Ads Keywords",
        approval_prompt=(
            "The agent wants to add these keywords to live ad groups. Review every ad group, "
            "keyword, match type, bid setting, and URL setting before changing ad delivery."
        ),
        approve_label="Approve & Add",
        arg_fields=(
            ToolFieldPresentation(
                key="ad_groups",
                label="Ad Groups",
                format="entity_list",
                editable=True,
                entity_kind="google_ads_ad_group",
            ),
            ToolFieldPresentation(
                key="keywords",
                label="Keywords",
                format="records",
                editable=True,
                min_rows=1,
                columns=(
                    ToolFieldColumn(key="text", label="Keyword", required=True),
                    ToolFieldColumn(
                        key="match_type",
                        label="Match Type",
                        options=("EXACT", "PHRASE", "BROAD"),
                        required=True,
                    ),
                    ToolFieldColumn(
                        key="status",
                        label="Status",
                        options=("ENABLED", "PAUSED"),
                        default_value="ENABLED",
                    ),
                    ToolFieldColumn(key="cpc_bid", label="CPC Bid", secondary=True),
                    ToolFieldColumn(
                        key="final_urls", label="Final URLs", format="list", secondary=True
                    ),
                    ToolFieldColumn(
                        key="final_mobile_urls",
                        label="Final Mobile URLs",
                        format="list",
                        secondary=True,
                    ),
                    ToolFieldColumn(
                        key="final_url_suffix", label="Final URL Suffix", secondary=True
                    ),
                    ToolFieldColumn(
                        key="tracking_url_template",
                        label="Tracking URL Template",
                        secondary=True,
                    ),
                    ToolFieldColumn(
                        key="url_custom_parameters",
                        label="URL Custom Parameters",
                        format="keyvalue",
                        secondary=True,
                        max_entries=8,
                    ),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
