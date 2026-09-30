# apps/api/tests/services/agents/runtime/test_tool_search.py

from collections.abc import Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from pydantic_ai.tools import ToolDefinition

from services.agents.runtime.tool_search import TOOL_SEARCH_MAX_RESULTS, search_deferred_tools
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG

CORPUS = [
    "create_artifact",
    "read_artifact",
    "update_artifact",
    "google_ads_update_campaign_status",
    "google_ads_create_campaign_budget",
    "google_ads_run_report",
    "outlook_mail_send_message",
    "gmail_send_message",
]


def _search(
    *queries: str,
    corpus: Sequence[str] = CORPUS,
    discovered: set[str] | None = None,
    workspace_definitions: Sequence[RuntimeToolDefinition] = (),
) -> list[str]:
    ctx: Any = SimpleNamespace(
        deps=SimpleNamespace(workspace_tool_definitions=workspace_definitions),
        discovered_tool_names=discovered or set(),
    )
    catalog = {**RUNTIME_TOOL_CATALOG, **{d.name: d for d in workspace_definitions}}
    tools = [ToolDefinition(name=name, description=catalog[name].description) for name in corpus]
    return search_deferred_tools(ctx, queries, tools)


def test_broad_noun_finds_every_action_on_it() -> None:
    assert set(_search("artifacts")) == {"create_artifact", "read_artifact", "update_artifact"}


def test_provider_limits_matches_to_its_tools() -> None:
    campaign_matches = _search("Google Ads campaigns")
    assert set(campaign_matches[:2]) == {
        "google_ads_update_campaign_status",
        "google_ads_create_campaign_budget",
    }
    assert "outlook_mail_send_message" not in campaign_matches
    assert set(_search("google ads")) == {
        "google_ads_update_campaign_status",
        "google_ads_create_campaign_budget",
        "google_ads_run_report",
    }
    assert _search("Outlook email") == ["outlook_mail_send_message"]


def test_known_provider_without_mounted_tools_matches_nothing() -> None:
    assert _search("Meta Ads campaign") == []


def test_capped_search_progresses_to_undiscovered_matches() -> None:
    corpus = [
        name
        for name, definition in RUNTIME_TOOL_CATALOG.items()
        if definition.provider in {"google_ads", "outlook_mail"}
    ]
    queries = ("Google Ads", "Outlook Mail")
    first = _search(*queries, corpus=corpus)[:TOOL_SEARCH_MAX_RESULTS]
    assert len(corpus) > TOOL_SEARCH_MAX_RESULTS == len(first)

    second = _search(*queries, corpus=corpus, discovered=set(first))[:TOOL_SEARCH_MAX_RESULTS]
    assert set(corpus) - set(first) <= set(second)


def test_platform_search_finds_workspace_classifiers() -> None:
    classifier = replace(
        RUNTIME_TOOL_CATALOG["create_artifact"],
        name="classifier_lead_quality",
        label="Lead quality classifier",
        provider="classifier",
    )
    matches = _search(
        "platform classifier",
        corpus=[*CORPUS, classifier.name],
        workspace_definitions=[classifier],
    )
    assert matches == ["classifier_lead_quality"]
