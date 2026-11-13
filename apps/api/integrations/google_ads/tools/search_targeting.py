# apps/api/integrations/google_ads/tools/search_targeting.py

"""Finds Google Ads locations, languages, and audiences by name and returns the keys other tools
take."""

from dataclasses import asdict
from typing import Annotated, Any

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EGRESS_PROVIDER_QUERY,
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.audit_events import (
    IntegrationOperationIntent,
    IntegrationOperationIntentGroup,
    IntegrationOperationTarget,
    PendingIntegrationOperationDetail,
    terminal_applied_operation_detail,
)
from services.integrations.context.domain import ResolvedContextEntry
from services.integrations.context.results import serialize_fan_out_results
from services.integrations.context.targeted import run_context_scope
from services.integrations.operations import (
    IntegrationAuditOutcome,
    run_audited_integration_operation,
)

from ..client import GoogleAdsClient
from ..operations.search_targeting import (
    MAX_LOCATION_NAMES,
    matching_languages,
    read_languages,
    search_audiences,
    search_locations,
)
from .schemas.targeting import (
    MAX_TARGETING_RESULTS,
    GoogleAdsTargetingKind,
    GoogleAdsTargetingSearchOutput,
)
from .utils.bindings import GOOGLE_ADS_BINDING, RESULTS_FIELD, active_google_ads_entries
from .utils.client import google_ads_available, google_ads_client
from .utils.routing import login_customer_id

_OPERATION = "search_targeting"
# Each audience name searches four lists, so a call takes fewer of them.
_MAX_AUDIENCE_NAMES = 5


async def google_ads_search_targeting(
    ctx: RunContext[RuntimeDeps],
    kind: GoogleAdsTargetingKind,
    names: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]],
        Field(
            min_length=1,
            max_length=MAX_LOCATION_NAMES,
            description=(
                "Up to 25 place or language names, or 5 audience names, to find in one call."
            ),
        ),
    ],
    country_code: Annotated[
        str | None,
        Field(pattern=r"^[A-Z]{2}$", description="Limits locations to one country, such as GB."),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_TARGETING_RESULTS)] = 25,
) -> dict[str, Any]:
    entries = active_google_ads_entries(ctx)
    if kind == "audience" and len(entries) != 1:
        raise ModelRetry(
            "Audience lists belong to one account. Ask the user to select only the account "
            "whose audiences you need."
        )

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            client = await google_ads_client(ctx, entry)
            options = await _options(client, entry, kind, names, country_code)
            data = {"options": options[:limit], "truncated": len(options) > limit}
            return IntegrationAuditOutcome(
                data, operation_detail=_audit_detail(entry.external_id, kind, len(options))
            )

        return await run_audited_integration_operation(
            ctx,
            entry,
            tool_name="google_ads_search_targeting",
            operation=_OPERATION,
            execute=execute,
        )

    # Google's constants are the same for every account, so one account searches; audiences
    # are searched in the only selected account.
    results = await run_context_scope(
        ctx,
        binding=GOOGLE_ADS_BINDING,
        provider_scope_id=entries[0].external_id,
        operation=operation,
    )
    return {"results": serialize_fan_out_results(results)}


async def _options(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    kind: GoogleAdsTargetingKind,
    names: list[str],
    country_code: str | None,
) -> list[dict[str, Any]]:
    if kind == "location":
        locations = await search_locations(client, names=names, country_code=country_code)
        return [{"kind": kind, **asdict(option)} for option in locations]
    if country_code is not None:
        raise ModelRetry("country_code only applies to locations.")
    if kind == "audience":
        if len(names) > _MAX_AUDIENCE_NAMES:
            raise ModelRetry(f"Search for at most {_MAX_AUDIENCE_NAMES} audience names at once.")
        audiences = {
            (option.kind, option.key): option
            for name in names
            for option in await search_audiences(
                client,
                customer_id=entry.external_id,
                login_customer_id=login_customer_id(entry),
                name=name,
            )
        }
        return [asdict(option) for option in audiences.values()]
    languages = await read_languages(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry)
    )
    found = {option.key: option for name in names for option in matching_languages(languages, name)}
    return [{"kind": kind, "key": option.key, "name": option.name} for option in found.values()]


def _audit_detail(account_id: str, kind: str, option_count: int):
    """Records the kind and count, without the agent's search text."""
    return terminal_applied_operation_detail(
        PendingIntegrationOperationDetail(
            target=IntegrationOperationTarget(entity_type="customer", external_id=account_id),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key="targeting_search",
                    action="read",
                    entity_type="customer",
                    items=[
                        IntegrationOperationIntent(
                            fields={"kind": kind, "option_count": option_count}
                        )
                    ],
                )
            ],
        )
    )


DEFINITION = RuntimeToolDefinition(
    name="google_ads_search_targeting",
    function=google_ads_search_targeting,
    description=(
        "Find Google Ads locations, languages, and audiences by name and get the keys "
        "google_ads_update_targeting takes. kind is location, language, or audience. names "
        "takes up to 25 names, so look up every place in one call, or up to 5 audience names. "
        "Use country_code to limit locations to one country. Each option has its key, a name "
        "for display, and, for locations, its type, region, and Google's estimated reach. A "
        "name can match several places, so compare region before choosing. "
        "eu_political_declaration is true for a location Google wants a campaign's EU "
        "political answer for. Audiences match "
        "any part of the name, ignoring case, across the account's own lists (user_list), "
        "Google's in-market and affinity audiences (user_interest), and custom and combined "
        "audiences; each has its kind, key, and category. Audiences belong to one account, so "
        "only one may be selected. Never invent keys. Location and language keys don't depend "
        "on the account, so one selected account runs those searches."
    ),
    provider="google_ads",
    label="Search Google Ads Targeting",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=60,
    output_model=GoogleAdsTargetingSearchOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Searching Google Ads Targeting",
        completed_label="Searched Google Ads Targeting",
        failed_label="Couldn't Search Google Ads Targeting",
        arg_fields=(
            ToolFieldPresentation(key="kind", label="Kind"),
            ToolFieldPresentation(key="names", label="Search", format="list"),
            ToolFieldPresentation(key="country_code", label="Country"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
