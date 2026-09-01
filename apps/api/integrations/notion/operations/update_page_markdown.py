# apps/api/integrations/notion/operations/update_page_markdown.py

"""Prepare an exact-text Notion page update against live page state."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic_ai import ModelRetry

from services.integrations.context.domain import ResolvedContextEntry

from ..client import NotionClient
from ..references import NotionPageReference
from .properties import NotionMutationTarget, get_page_mutation_target, validate_mutation_scope


class NotionReplacementRecordLike(Protocol):
    """Describes one normalized exact-text replacement."""

    old_text: str
    new_text: str
    replace_all: str


@dataclass(frozen=True)
class UpdatePageMarkdownPreparation:
    """Carries the live page and normalized replacement records."""

    page: NotionMutationTarget
    replacements: tuple[NotionReplacementRecordLike, ...]


async def prepare_update_page_markdown(
    client: NotionClient,
    entry: ResolvedContextEntry,
    *,
    page: NotionPageReference,
    replacements: Sequence[NotionReplacementRecordLike],
) -> UpdatePageMarkdownPreparation:
    """Validates an exact-text update against the live target page."""
    validate_mutation_scope(entry, page.provider_scope_id, reference_label="page")
    if not replacements:
        raise ModelRetry("Add at least one exact-text replacement.")
    target = await get_page_mutation_target(client, page)
    return UpdatePageMarkdownPreparation(page=target, replacements=tuple(replacements))
