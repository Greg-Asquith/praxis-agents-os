# apps/api/services/agents/runtime/tool_search.py

"""Provider-aware discovery of deferred runtime tools."""

import re
from collections.abc import Sequence

from pydantic_ai import RunContext
from pydantic_ai.capabilities import ToolSearch
from pydantic_ai.tools import ToolDefinition

from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import RuntimeToolDefinition
from services.agents.runtime.tools.registry import resolve_runtime_tool_definition
from services.integrations.manifest import PROVIDER_MANIFESTS

PLATFORM_PROVIDER = "platform"
_PLATFORM_TOOL_PROVIDERS = frozenset({"core", "native", "kb", "classifier"})
_PLATFORM_NAMES = ({"platform"}, {"internal"}, {"builtin"})
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Enough to return every tool of the largest provider in one search.
TOOL_SEARCH_MAX_RESULTS = 30

TOOL_SEARCH_DESCRIPTION = """\
Find tools that are not loaded yet. Up to 30 matching tools load per search, \
tools not loaded yet first, so one broad search is better than several narrow \
ones. If a search fills all 30, repeat it to load the rest.

Write each query as the provider, then one broad word for what you work on:
- Provider: a connected service such as "Google Ads" or "Outlook", or \
"platform" for built-in tools.
- Name: a broad noun such as "campaign", "email", or "artifact". Leave out \
verbs like create, read, list, or update.

Search "platform artifact" once, not "create artifact", "read artifact", and \
"update artifact" separately. A provider on its own finds all of its tools. \
Put every need into one call. If nothing is found, don't retry with similar words.\
"""

TOOL_SEARCH_QUERIES_DESCRIPTION = (
    'Short queries, each "<provider> <broad noun>", such as "Google Ads campaign" '
    'or "platform artifact". Matches across queries are combined.'
)


def build_tool_search_capability() -> ToolSearch[RuntimeDeps]:
    """Return tool search with our guidance and provider-aware matching.

    A callable strategy keeps the provider's client-executed search, so
    discovery still preserves the prompt cache on Anthropic and OpenAI.
    """
    return ToolSearch(
        strategy=search_deferred_tools,
        max_results=TOOL_SEARCH_MAX_RESULTS,
        tool_description=TOOL_SEARCH_DESCRIPTION,
        parameter_description=TOOL_SEARCH_QUERIES_DESCRIPTION,
    )


def search_deferred_tools(
    ctx: RunContext[RuntimeDeps],
    queries: Sequence[str],
    tools: Sequence[ToolDefinition],
) -> list[str]:
    """Rank deferred tools against provider-first queries.

    A query that names a provider only matches that provider's tools, even
    when none of them are mounted; its remaining words match tool names,
    labels, and descriptions. A provider on its own matches all of its tools.
    Tools not yet discovered rank first so a repeated capped search progresses.
    """
    workspace_definitions = ctx.deps.workspace_tool_definitions if ctx.deps else ()
    indexed = [
        _IndexedTool.build(tool, resolve_runtime_tool_definition(tool.name, workspace_definitions))
        for tool in tools
    ]
    vocabulary = _provider_vocabulary()
    scores: dict[str, int] = {}
    for query in queries:
        providers, terms = _split_query(_tokens(query), vocabulary)
        for tool in indexed:
            score = tool.score(providers, terms)
            if score > 0:
                scores[tool.name] = max(scores.get(tool.name, 0), score)
    discovered = ctx.discovered_tool_names
    return sorted(scores, key=lambda name: (name not in discovered, scores[name]), reverse=True)


class _IndexedTool:
    def __init__(self, name: str, provider: str, title_terms: set[str], body_terms: set[str]):
        self.name = name
        self.provider = provider
        self.title_terms = title_terms
        self.body_terms = body_terms

    @classmethod
    def build(
        cls, tool: ToolDefinition, definition: RuntimeToolDefinition | None
    ) -> "_IndexedTool":
        provider = definition.provider if definition else PLATFORM_PROVIDER
        if provider in _PLATFORM_TOOL_PROVIDERS:
            provider = PLATFORM_PROVIDER
        label = definition.label if definition else ""
        return cls(
            name=tool.name,
            provider=provider,
            title_terms=_tokens(f"{tool.name} {label}"),
            body_terms=_tokens(tool.description or ""),
        )

    def score(self, providers: frozenset[str] | None, terms: set[str]) -> int:
        if providers is not None and self.provider not in providers:
            return 0
        if not terms:
            return 1 if providers is not None else 0
        return 2 * len(terms & self.title_terms) + len(terms & self.body_terms)


def _split_query(
    terms: set[str], vocabulary: list[tuple[str, set[str]]]
) -> tuple[frozenset[str] | None, set[str]]:
    """Pull the most specific provider names in a query out of its terms.

    Equally specific names all apply, so "Outlook" means both Outlook providers.
    """
    matches = [(provider, names) for provider, names in vocabulary if names <= terms]
    if not matches:
        return None, terms
    longest = max(len(names) for _, names in matches)
    best = [(provider, names) for provider, names in matches if len(names) == longest]
    named = set().union(*(names for _, names in best))
    return frozenset(provider for provider, _ in best), terms - named


def _provider_vocabulary() -> list[tuple[str, set[str]]]:
    """Name every known provider by key, display name, and display name's first word."""
    vocabulary = [(PLATFORM_PROVIDER, names) for names in _PLATFORM_NAMES]
    for key, manifest in PROVIDER_MANIFESTS.items():
        display_words = _TOKEN_RE.findall(manifest.display_name.lower())
        names = (key, manifest.display_name, display_words[0])
        vocabulary.extend((key, _tokens(text)) for text in names)
    return vocabulary


def _tokens(text: str) -> set[str]:
    return {_singular(token) for token in _TOKEN_RE.findall(text.lower())}


def _singular(token: str) -> str:
    """Fold simple plurals so "campaigns" matches "campaign"."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token
