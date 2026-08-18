# apps/api/services/agents/runtime/tools/classifiers.py

"""Synthesize runtime tools from workspace classifier rows."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, cast
from uuid import UUID

from pydantic import Field
from pydantic_ai import ModelRetry, RunContext

from models.classifiers import Classifier
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.tools.contract import (
    TOOL_EFFECT_READ,
    TOOL_EFFECT_SCOPE_INTERNAL,
    TOOL_EGRESS_PROVIDER_QUERY,
    TOOL_POLICY_AUTO,
    RuntimeToolDefinition,
    ToolFieldColumn,
    ToolFieldPresentation,
    ToolPresentation,
    validate_definition,
)
from services.agents.runtime.tools.native.classifier import (
    ClassifierProvider,
    ClassifyOutput,
    _validate_items,
    resolve_classifier_model,
    run_native_classification,
)


def build_classifier_tool_definitions(
    rows: Sequence[Classifier],
) -> list[RuntimeToolDefinition]:
    """Build one available runtime definition per active classifier row."""
    definitions: list[RuntimeToolDefinition] = []
    for row in rows:
        if not row.is_active or row.deleted:
            continue
        try:
            model_spec = resolve_classifier_model(
                model_provider=row.model_provider,
                model=row.model,
            )
        except ModelRetry:
            continue

        labels = tuple(str(item["label"]) for item in row.labels)
        label_guidance = tuple(
            (str(item["label"]), str(item.get("description") or "").strip()) for item in row.labels
        )
        instructions = _classification_guidance(row.instructions, label_guidance)

        definition = RuntimeToolDefinition(
            name=f"classifier_{row.name}",
            function=_build_handler(
                labels=labels,
                instructions=instructions,
                model_spec=model_spec,
                classifier_id=row.id,
                classifier_name=row.name,
            ),
            description=_tool_description(row.description, label_guidance),
            provider="classifier",
            label=row.display_name,
            effect=TOOL_EFFECT_READ,
            effect_scope=TOOL_EFFECT_SCOPE_INTERNAL,
            egress=TOOL_EGRESS_PROVIDER_QUERY,
            code_eligible=True,
            takes_ctx=True,
            default_policy=TOOL_POLICY_AUTO,
            supports_auto=True,
            supports_approval=False,
            timeout=None,
            output_model=ClassifyOutput,
            configurable=True,
            presentation=_presentation(row.display_name),
        )
        validate_definition(definition)
        definition.serialized_input_schema()
        definitions.append(definition)
    return definitions


def _build_handler(
    *,
    labels: tuple[str, ...],
    instructions: str | None,
    model_spec: ResolvedModel,
    classifier_id: UUID,
    classifier_name: str,
) -> Callable[[RunContext[RuntimeDeps], list[str]], Awaitable[dict[str, object]]]:
    async def handler(
        ctx: RunContext[RuntimeDeps],
        items: Annotated[list[str], Field(description="Text items to classify in one batch.")],
    ) -> dict[str, object]:
        validated_items = _validate_items(items)
        results = await run_native_classification(
            ctx.deps,
            items=validated_items,
            labels=list(labels),
            instructions=instructions,
            model_spec=model_spec,
            event_details={
                "classifier_id": str(classifier_id),
                "classifier_name": classifier_name,
            },
        )
        return ClassifyOutput(
            results=results,
            model_provider=cast(ClassifierProvider, model_spec.provider),
            model=model_spec.model,
        ).model_dump()

    return handler


def _classification_guidance(
    instructions: str | None,
    labels: tuple[tuple[str, str], ...],
) -> str:
    descriptions = "\n".join(
        f"- {label}: {description}" if description else f"- {label}"
        for label, description in labels
    )
    prefix = instructions.strip() if instructions else "Use the most specific applicable category."
    return f"{prefix}\n\nCategory guidance:\n{descriptions}"


def _tool_description(description: str, labels: tuple[tuple[str, str], ...]) -> str:
    vocabulary = "; ".join(
        f"{label} — {label_description}" if label_description else label
        for label, label_description in labels
    )
    return (
        f"{description.strip()} Classify each supplied item into exactly one of these "
        f"operator-defined categories: {vocabulary}. Returns the assigned category verbatim. "
        "Classifier edits apply from the next agent run."
    )


def _presentation(display_name: str) -> ToolPresentation:
    return ToolPresentation(
        icon="sparkles",
        running_label=f"Classifying with {display_name}",
        completed_label=f"Classified with {display_name}",
        failed_label=f"Couldn't run {display_name}",
        approval_title=display_name,
        approval_prompt="The agent wants to classify these items with a helper model.",
        approve_label="Approve & Classify",
        arg_fields=(ToolFieldPresentation(key="items", label="Items", format="list"),),
        result_fields=(
            ToolFieldPresentation(
                key="results",
                label="Classifications",
                format="records",
                columns=(
                    ToolFieldColumn(key="index", label="Index"),
                    ToolFieldColumn(key="value", label="Classified value"),
                    ToolFieldColumn(key="label", label="Assigned label"),
                ),
            ),
            ToolFieldPresentation(key="model_provider", label="Provider"),
            ToolFieldPresentation(key="model", label="Model"),
        ),
    )
