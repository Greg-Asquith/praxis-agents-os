# apps/api/integrations/google_ads/tools/add_positive_keywords.py

"""Approval-only Google Ads positive-keyword creation tool."""

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext, ToolReturn

from core.exceptions.integration import IntegrationError, IntegrationFailureDisposition
from integrations.google_ads.operations.add_positive_keywords import (
    MAX_POSITIVE_KEYWORD_OPERATIONS,
    GoogleAdsPositiveKeywordCreate,
    add_positive_keywords,
    positive_keyword_creation_failure_ledger,
)
from integrations.google_ads.operations.list_ad_groups import list_ad_groups
from integrations.google_ads.operations.list_positive_keywords import list_positive_keyword_pairs
from integrations.google_ads.operations.mutation_outcomes import (
    GoogleAdsMutationLedger,
    thaw_fields,
)
from integrations.google_ads.operations.utils import nonnegative_int
from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsKeywordReference,
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

from .schemas import GoogleAdsAddPositiveKeywordsOutput, GoogleAdsPositiveKeywordEntry
from .schemas.positive_keywords import cpc_bid_to_micros
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


async def google_ads_add_keywords(
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
            live_references = await _live_ad_groups(client, entry, references)
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
                ledger = await add_positive_keywords(
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
            tool_name="google_ads_add_keywords",
            operation="add_positive_keywords",
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
        (keyword.text.casefold(), keyword.match_type) for keyword in normalized_keywords
    ]
    if len(set(keyword_keys)) != len(keyword_keys):
        raise ModelRetry("Each normalized keyword and match type can appear only once.")
    if len(unique_ad_groups) * len(normalized_keywords) > MAX_POSITIVE_KEYWORD_OPERATIONS:
        raise ModelRetry(
            "Ad groups multiplied by keyword rows must not exceed 2,500. "
            "Split the request into smaller groups."
        )
    return list(unique_ad_groups.values()), normalized_keywords


async def _live_ad_groups(
    client,
    entry: ResolvedContextEntry,
    selected: Sequence[GoogleAdsAdGroupReference],
) -> list[GoogleAdsAdGroupReference]:
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
    if set(live_by_id) != set(ids):
        raise ModelRetry(
            "A selected Google Ads ad group is unavailable. Ask the user to choose it again."
        )
    return [live_by_id[reference.ad_group_id] for reference in selected]


def _expanded_creates(
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    keywords: Sequence[GoogleAdsPositiveKeywordEntry],
) -> list[GoogleAdsPositiveKeywordCreate]:
    return [
        GoogleAdsPositiveKeywordCreate(
            ad_group_id=ad_group.ad_group_id,
            text=keyword.text,
            match_type=keyword.match_type,
            cpc_bid_micros=(
                cpc_bid_to_micros(keyword.cpc_bid) if keyword.cpc_bid is not None else None
            ),
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
                key=f"ad-group:{ad_group.ad_group_id}:add-positive-keywords",
                action="add",
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
                            **({"cpc_bid": keyword.cpc_bid} if keyword.cpc_bid else {}),
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
        key = (ad_group.ad_group_id, fields["text"].casefold(), fields["match_type"])
        requested_micros = fields.get("cpc_bid_micros")
        row: dict[str, Any] = {
            "campaign_id": ad_group.campaign_id,
            "campaign_name": (ad_group.scope_label or "")[:100],
            "ad_group_id": ad_group.ad_group_id,
            "ad_group_name": ad_group.label[:100],
            "text": fields["text"],
            "match_type": fields["match_type"],
            "cpc_bid": micros_to_money(int(requested_micros)) if requested_micros else None,
            "cpc_bid_micros": requested_micros,
        }
        if parent.decision == "skipped":
            keyword = existing.get(key)
            if keyword is None:
                raise ValueError("Google Ads skipped keyword evidence is unavailable")
            row.update(
                previous_state="existing",
                outcome="skipped_existing",
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
                error_code=effect.error_code[:100] if effect.error_code else None,
                message=effect.message[:200] if effect.message else None,
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
                    status="ENABLED",
                    cpc_bid_micros=int(requested_micros) if requested_micros else None,
                    label=fields["text"],
                    description=f"{fields['match_type'].title()} · Enabled",
                    scope_label=f"{ad_group.scope_label or ''} · {ad_group.label}".strip(" ·"),
                )
        rows.append(row)
    return rows


def _existing_references(
    rows: Sequence[Mapping[str, Any]],
    ad_groups: Mapping[str, GoogleAdsAdGroupReference],
) -> dict[tuple[str, str, str], GoogleAdsKeywordReference]:
    references: dict[tuple[str, str, str], GoogleAdsKeywordReference] = {}
    for row in rows:
        ad_group = row.get("adGroup")
        criterion = row.get("adGroupCriterion")
        campaign = row.get("campaign")
        if not all(isinstance(value, Mapping) for value in (ad_group, criterion, campaign)):
            continue
        keyword = criterion.get("keyword")
        if not isinstance(keyword, Mapping):
            continue
        ad_group_id = str(ad_group.get("id", ""))
        selected = ad_groups.get(ad_group_id)
        text = str(keyword.get("text", ""))
        match_type = str(keyword.get("matchType", ""))
        criterion_id = str(criterion.get("criterionId", ""))
        status = str(criterion.get("status", ""))
        if (
            selected is None
            or not criterion_id.isdigit()
            or match_type not in {"EXACT", "PHRASE", "BROAD"}
            or status not in {"ENABLED", "PAUSED"}
        ):
            continue
        reference = GoogleAdsKeywordReference(
            customer_id=selected.customer_id,
            campaign_id=selected.campaign_id,
            ad_group_id=selected.ad_group_id,
            criterion_id=criterion_id,
            text=text,
            match_type=match_type,
            status=status,
            cpc_bid_micros=nonnegative_int(criterion.get("cpcBidMicros")),
            label=text,
            description=f"{match_type.title()} · {status.title()}",
            scope_label=f"{selected.scope_label or ''} · {selected.label}".strip(" ·"),
        )
        references.setdefault((ad_group_id, text.casefold(), match_type), reference)
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
    return IntegrationAuditOutcome(
        ledger,
        status=audit_status(detail),
        operation_detail=detail,
        unverified_result=(
            {
                "model_result": bounded_positive_keyword_result(
                    _result_rows(ad_groups, existing_rows, ledger),
                    currency_code=currency_code,
                ),
                "display_result": display_positive_keyword_result(
                    _result_rows(ad_groups, existing_rows, ledger),
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
    display_keywords = (
        [
            {**keyword, "cpc_bid": keyword.get("cpc_bid") or ""}
            if isinstance(keyword, Mapping)
            else keyword
            for keyword in keywords
        ]
        if isinstance(keywords, list)
        else keywords
    )
    return {**args, "keywords": display_keywords, "_account_currencies": accounts}


DEFINITION = RuntimeToolDefinition(
    name="google_ads_add_keywords",
    function=google_ads_add_keywords,
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
    output_model=GoogleAdsAddPositiveKeywordsOutput,
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
            "match type, and optional CPC bid before changing ad delivery."
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
                    ToolFieldColumn(key="cpc_bid", label="CPC Bid"),
                ),
            ),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
