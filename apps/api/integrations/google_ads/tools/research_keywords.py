# apps/api/integrations/google_ads/tools/research_keywords.py

"""Finds keyword ideas and search volumes with Keyword Planner, and places keywords into existing
ad groups."""

from collections.abc import Sequence
from typing import Annotated, Any
from urllib.parse import urlsplit

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
from ..operations.keyword_research import (
    KeywordMetrics,
    ad_group_placements,
    generate_keyword_ideas,
    keyword_historical_metrics,
)
from ..operations.search_targeting import read_languages, read_locations
from ..references import GoogleAdsAdGroupReference
from .schemas.keyword_research import (
    MAX_RESEARCH_AD_GROUPS,
    MAX_RESEARCH_LOCATIONS,
    MAX_RESEARCH_ROWS,
    GoogleAdsKeywordResearchOutput,
)
from .schemas.positive_keywords import GoogleAdsFinalUrl
from .utils.accounts import account_facts
from .utils.bindings import GOOGLE_ADS_BINDING, RESULTS_FIELD, active_google_ads_entries
from .utils.client import google_ads_available, google_ads_client
from .utils.money import micros_to_money
from .utils.routing import login_customer_id

_TOOL = "google_ads_research_keywords"
# Google's limit on keywords in one idea seed.
_MAX_SEEDS = 20
type _Key = Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
type _Keyword = Annotated[str, Field(min_length=1, max_length=80)]


async def google_ads_research_keywords(
    ctx: RunContext[RuntimeDeps],
    seeds: Annotated[
        list[_Keyword],
        Field(max_length=_MAX_SEEDS, description="Up to 20 words or phrases to find ideas from."),
    ] = [],  # noqa: B006 -- pydantic copies defaults
    url: Annotated[
        GoogleAdsFinalUrl | None,
        Field(
            description=(
                "A page to find ideas from, or a site's home page for ideas from the whole site."
            )
        ),
    ] = None,
    keywords: Annotated[
        list[_Keyword],
        Field(
            max_length=MAX_RESEARCH_ROWS,
            description="Exact keywords to get search volumes and bids for, with no ideas added.",
        ),
    ] = [],  # noqa: B006 -- pydantic copies defaults
    locations: Annotated[
        list[_Key],
        Field(
            max_length=MAX_RESEARCH_LOCATIONS,
            description="Up to 10 location keys from google_ads_search_targeting.",
        ),
    ] = [],  # noqa: B006 -- pydantic copies defaults
    language: Annotated[
        _Key | None, Field(description="One language key from google_ads_search_targeting.")
    ] = None,
    ad_groups: Annotated[
        list[GoogleAdsAdGroupReference],
        Field(
            max_length=MAX_RESEARCH_AD_GROUPS,
            description="Existing Search ad groups to sort the keywords into.",
        ),
    ] = [],  # noqa: B006 -- pydantic copies defaults
    limit: Annotated[int, Field(ge=1, le=MAX_RESEARCH_ROWS)] = 200,
) -> dict[str, Any]:
    if not seeds and url is None and not keywords:
        raise ModelRetry("Give seeds, a url, or keywords to research.")
    entry = _account(ctx, ad_groups)

    async def operation(entry: ResolvedContextEntry) -> Any:
        async def execute() -> IntegrationAuditOutcome:
            client = await google_ads_client(ctx, entry)
            data = await _research(
                client,
                entry,
                seed=_seed(seeds, url),
                keywords=keywords,
                locations=locations,
                language=language,
                ad_groups=ad_groups,
                limit=limit,
            )
            return IntegrationAuditOutcome(
                data,
                operation_detail=_audit_detail(
                    entry.external_id,
                    seeds=len(seeds),
                    url=url is not None,
                    keywords=len(keywords),
                    rows=len(data["ideas"]),
                ),
            )

        return await run_audited_integration_operation(
            ctx, entry, tool_name=_TOOL, operation="research_keywords", execute=execute
        )

    results = await run_context_scope(
        ctx, binding=GOOGLE_ADS_BINDING, provider_scope_id=entry.external_id, operation=operation
    )
    return {"results": serialize_fan_out_results(results)}


def _account(
    ctx: RunContext[RuntimeDeps], ad_groups: Sequence[GoogleAdsAdGroupReference]
) -> ResolvedContextEntry:
    """Picks the ad groups' account, or the first selected one, whose currency prices the bids."""
    entries = active_google_ads_entries(ctx)
    wanted = {reference.customer_id for reference in ad_groups}
    if len(wanted) > 1:
        raise ModelRetry("Pass ad groups from one Google Ads account.")
    match = [entry for entry in entries if not wanted or entry.external_id in wanted]
    if not match:
        raise ModelRetry("Those ad groups' Google Ads account isn't in the selected context.")
    return match[0]


def _seed(seeds: Sequence[str], url: str | None) -> dict[str, Any] | None:
    if url is None:
        return {"keywordSeed": {"keywords": list(seeds)}} if seeds else None
    if seeds:
        return {"keywordAndUrlSeed": {"url": url, "keywords": list(seeds)}}
    parts = urlsplit(url)
    if parts.path in ("", "/") and not parts.query:
        return {"siteSeed": {"site": parts.hostname}}
    return {"urlSeed": {"url": url}}


async def _research(
    client: GoogleAdsClient,
    entry: ResolvedContextEntry,
    *,
    seed: dict[str, Any] | None,
    keywords: Sequence[str],
    locations: Sequence[str],
    language: str | None,
    ad_groups: Sequence[GoogleAdsAdGroupReference],
    limit: int,
) -> dict[str, Any]:
    facts = account_facts(entry)
    routing = {"customer_id": entry.external_id, "login_customer_id": login_customer_id(entry)}
    places = await _places(client, routing, locations, language)
    targeting = {"locations": locations, "language": language}
    requested = (
        await keyword_historical_metrics(client, **routing, keywords=keywords, **targeting)
        if keywords
        else []
    )
    ideas, total = (
        await generate_keyword_ideas(client, **routing, seed=seed, **targeting) if seed else ([], 0)
    )
    fetched = len(ideas)
    seen = {row.text.casefold() for row in requested}
    ideas = sorted(
        (idea for idea in ideas if idea.text.casefold() not in seen),
        key=lambda idea: idea.avg_monthly_searches or 0,
        reverse=True,
    )
    room = max(limit - len(requested), 0)
    rows = [(row, True) for row in requested[:limit]] + [(idea, False) for idea in ideas[:room]]
    rows.sort(key=lambda pair: pair[0].avg_monthly_searches or 0, reverse=True)
    placements, unusable = (
        await ad_group_placements(
            client,
            **routing,
            keywords=[row.text for row, _ in rows],
            ad_group_ids=[reference.ad_group_id for reference in ad_groups],
        )
        if ad_groups and rows
        else ({}, set())
    )
    return {
        "account_id": entry.external_id,
        "currency": facts.currency,
        **places,
        "ideas": [_idea(row, requested_row, placements) for row, requested_row in rows],
        "total_ideas": total,
        "truncated": len(requested) > limit or len(ideas) > room or total > fetched,
        "ad_groups": [
            {
                "ad_group_id": reference.ad_group_id,
                "campaign_id": reference.campaign_id,
                "name": reference.label,
                "usable": reference.ad_group_id not in unusable,
            }
            for reference in ad_groups
        ],
    }


async def _places(
    client: GoogleAdsClient,
    routing: dict[str, str],
    locations: Sequence[str],
    language: str | None,
) -> dict[str, Any]:
    """Checks the location and language keys exist and returns their names for the card."""
    found = await read_locations(client, **routing, keys=locations) if locations else {}
    missing = [key for key in locations if key not in found]
    if missing:
        raise ModelRetry(
            f"Unknown location keys: {', '.join(missing)}. Find keys with "
            "google_ads_search_targeting."
        )
    chosen = None
    if language is not None:
        languages = {option.key: option for option in await read_languages(client, **routing)}
        if language not in languages:
            raise ModelRetry(
                f"Unknown language key {language}. Find keys with google_ads_search_targeting."
            )
        chosen = {"key": language, "name": languages[language].name}
    return {
        "locations": [{"key": key, "name": found[key].name} for key in dict.fromkeys(locations)],
        "language": chosen,
    }


def _idea(row: KeywordMetrics, requested: bool, placements: dict[str, Any]) -> dict[str, Any]:
    placement = placements.get(row.text.casefold())
    return {
        "text": row.text,
        "requested": requested,
        "avg_monthly_searches": row.avg_monthly_searches,
        "competition": row.competition,
        "low_bid": _money(row.low_bid_micros),
        "high_bid": _money(row.high_bid_micros),
        "trend": list(row.trend),
        "themes": list(row.themes),
        "close_variants": list(row.close_variants[:50]),
        "ad_group_id": placement.ad_group_id if placement else None,
        "match_type": placement.match_type if placement else None,
    }


def _money(micros: int | None) -> str | None:
    return None if micros is None else micros_to_money(micros)


def _audit_detail(account_id: str, *, seeds: int, url: bool, keywords: int, rows: int):
    """Records counts, without the agent's search text."""
    return terminal_applied_operation_detail(
        PendingIntegrationOperationDetail(
            target=IntegrationOperationTarget(entity_type="customer", external_id=account_id),
            intent_groups=[
                IntegrationOperationIntentGroup(
                    key="keyword_research",
                    action="read",
                    entity_type="customer",
                    items=[
                        IntegrationOperationIntent(
                            fields={
                                "seed_count": seeds,
                                "has_url": url,
                                "keyword_count": keywords,
                                "row_count": rows,
                            }
                        )
                    ],
                )
            ],
        )
    )


DEFINITION = RuntimeToolDefinition(
    name=_TOOL,
    function=google_ads_research_keywords,
    description=(
        "Find keyword ideas with Google's Keyword Planner, with average monthly searches, the "
        "12-month trend, competition, and the low and high top-of-page bid in the account "
        "currency. Give seeds (up to 20 words or phrases), a url (a page, or a home page for "
        "the whole site), or both, for ideas; give keywords for metrics on exact keywords only. "
        "Pass the campaign's location keys and one language key from "
        "google_ads_search_targeting; without them Google counts every location and language. "
        "Ideas come back sorted by searches, up to limit rows, each with Google's themes (such "
        "as a brand or product type) for grouping. To sort keywords into existing Search ad "
        "groups, pass ad_groups: each row then has the suggested ad_group_id and match_type. "
        "To build from the result, pass each chosen row's text with a match type to "
        "google_ads_create_ad_groups or google_ads_create_keywords. Searches and bids are "
        "Google's estimates; present them as estimates, never as commitments. Research runs "
        "in the ad groups' account, or else the first selected account, and prices bids in "
        "its currency."
    ),
    provider="google_ads",
    label="Research Google Ads Keywords",
    takes_ctx=True,
    code_eligible=True,
    effect=TOOL_EFFECT_READ,
    egress=TOOL_EGRESS_PROVIDER_QUERY,
    timeout=90,
    output_model=GoogleAdsKeywordResearchOutput,
    max_public_result_chars=settings.AGENT_STRUCTURED_RESULT_MAX_CHARS,
    preview_list_path="results.*.data.ideas",
    integration_binding=GOOGLE_ADS_BINDING,
    availability_check=google_ads_available,
    presentation=ToolPresentation(
        icon="google_ads",
        running_label="Researching Google Ads Keywords",
        completed_label="Researched Google Ads Keywords",
        failed_label="Couldn't Research Google Ads Keywords",
        arg_fields=(
            ToolFieldPresentation(key="seeds", label="Seeds", format="list"),
            ToolFieldPresentation(key="url", label="Website"),
            ToolFieldPresentation(key="keywords", label="Keywords", format="list"),
        ),
        result_fields=RESULTS_FIELD,
    ),
)
