# apps/api/integrations/google_ads/entity_resolvers/conversion_action.py

"""Google Ads conversion action and account goal lookup for runtime entity selectors."""

from collections.abc import Sequence
from typing import Any

from integrations.google_ads.operations.conversion_settings import (
    MAX_CONVERSION_ACTION_LOOKUP,
    LiveAccountGoal,
    LiveConversionAction,
    list_conversion_actions,
    read_account_goals,
)
from integrations.google_ads.references import (
    GoogleAdsConversionActionReference,
    GoogleAdsConversionGoalReference,
)
from integrations.google_ads.tools.utils import (
    GOOGLE_ADS_BINDING,
    google_ads_client_for_principal,
    login_customer_id,
)
from services.integrations.context.schemas import MAX_ACTIVE_CONTEXT_TARGETS
from services.integrations.entity_references import (
    EntityChoice,
    EntityResolverDefinition,
    EntityResolverPage,
)

from .utils import group_scoped_references, search_scoped_entities


def _choice(entry, action: LiveConversionAction) -> EntityChoice:
    role = "Primary" if action.values.get("primaryForGoal") else "Secondary"
    category = action.category.replace("_", " ").capitalize() or "Conversion"
    return EntityChoice.from_reference(
        GoogleAdsConversionActionReference(
            customer_id=entry.external_id,
            conversion_action_id=action.conversion_action_id,
            label=action.name,
            description=f"{category} · {role}",
            scope_label=entry.display_name,
        ),
        icon="google_ads",
    )


async def _query(ctx, entry, **filters: Any) -> list[LiveConversionAction]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    return await list_conversion_actions(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry), **filters
    )


async def search_google_ads_conversion_actions(ctx, search, _dependent_args, page_size, cursor):
    normalized_search = search.strip()

    async def query_entry(entry, minimum_id, _minimum_secondary_id, inclusive, limit):
        return await _query(
            ctx,
            entry,
            search=normalized_search or None,
            minimum_id=minimum_id,
            minimum_id_inclusive=inclusive,
            limit=limit,
        )

    return await search_scoped_entities(
        ctx,
        GOOGLE_ADS_BINDING,
        search=normalized_search,
        page_size=page_size,
        cursor=cursor,
        query_entry=query_entry,
        choice_for_row=_choice,
    )


async def resolve_google_ads_conversion_actions(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    grouped = group_scoped_references(
        ctx,
        GOOGLE_ADS_BINDING,
        values,
        GoogleAdsConversionActionReference,
        max_references=MAX_CONVERSION_ACTION_LOOKUP - 1,
    )
    for entry, references in grouped:
        ids = [reference.conversion_action_id for reference in references]
        actions = await _query(ctx, entry, conversion_action_ids=ids, limit=len(ids))
        choices.extend(_choice(entry, action) for action in actions)
    return tuple(choices)


GOOGLE_ADS_CONVERSION_ACTION_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_conversion_action",
    reference_type=GoogleAdsConversionActionReference,
    search=search_google_ads_conversion_actions,
    resolve=resolve_google_ads_conversion_actions,
    max_page_size=25,
    max_exact_values=MAX_CONVERSION_ACTION_LOOKUP - 1,
    requires_active_context=True,
    provider_key="google_ads",
)


def _words(token: str) -> str:
    return token.replace("_", " ").capitalize()


def _goal_choice(entry, goal: LiveAccountGoal) -> EntityChoice:
    bidding = "Counts for bidding" if goal.values.get("biddable") else "Doesn't count for bidding"
    return EntityChoice.from_reference(
        GoogleAdsConversionGoalReference(
            customer_id=entry.external_id,
            category=goal.category,
            origin=goal.origin,
            label=f"{_words(goal.category)} from {_words(goal.origin).lower()}",
            description=bidding,
            scope_label=entry.display_name,
        ),
        icon="google_ads",
    )


async def _goals(ctx, entry) -> list[LiveAccountGoal]:
    client = await google_ads_client_for_principal(
        ctx.db, actor=ctx.actor, workspace=ctx.workspace, entry=entry
    )
    goals = await read_account_goals(
        client, customer_id=entry.external_id, login_customer_id=login_customer_id(entry)
    )
    return sorted(goals.values(), key=lambda goal: goal.resource_name)


async def search_google_ads_conversion_goals(ctx, search, _dependent_args, page_size, _cursor):
    """Accounts hold a few dozen goals at most, so one page lists every match."""
    words = search.strip().lower().split()
    choices: list[EntityChoice] = []
    for entry in ctx.active_context.compatible_entries(GOOGLE_ADS_BINDING)[
        :MAX_ACTIVE_CONTEXT_TARGETS
    ]:
        for goal in await _goals(ctx, entry):
            choice = _goal_choice(entry, goal)
            if all(word in choice.label.lower() for word in words):
                choices.append(choice)
    return EntityResolverPage(choices=tuple(choices[:page_size]))


async def resolve_google_ads_conversion_goals(ctx, values: Sequence[Any], _dependent_args):
    choices: list[EntityChoice] = []
    for entry, references in group_scoped_references(
        ctx, GOOGLE_ADS_BINDING, values, GoogleAdsConversionGoalReference
    ):
        wanted = {reference.provider_entity_id for reference in references}
        choices.extend(
            _goal_choice(entry, goal)
            for goal in await _goals(ctx, entry)
            if f"{goal.category}~{goal.origin}" in wanted
        )
    return tuple(choices)


GOOGLE_ADS_CONVERSION_GOAL_RESOLVER = EntityResolverDefinition(
    entity_kind="google_ads_conversion_goal",
    reference_type=GoogleAdsConversionGoalReference,
    search=search_google_ads_conversion_goals,
    resolve=resolve_google_ads_conversion_goals,
    max_page_size=50,
    requires_active_context=True,
    provider_key="google_ads",
)
