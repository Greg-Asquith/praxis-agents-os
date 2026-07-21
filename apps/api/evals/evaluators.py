# apps/api/evals/evaluators.py

"""Shared programmatic evaluators for agent-behavior datasets."""

import json
from dataclasses import dataclass

from pydantic_evals.evaluators import Evaluator, EvaluatorContext


@dataclass(frozen=True)
class EvalOutput:
    text: str
    called_tools: tuple[str, ...] = ()
    tool_arguments: tuple[str, ...] = ()


@dataclass
class ExpectedTools(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        expected = set((ctx.metadata or {}).get("expected_tools", []))
        return expected.issubset(ctx.output.called_tools)


@dataclass
class ForbiddenTools(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        forbidden = set((ctx.metadata or {}).get("forbidden_tools", []))
        return forbidden.isdisjoint(ctx.output.called_tools)


@dataclass
class RequiredText(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        required = (ctx.metadata or {}).get("required_text", [])
        lowered = ctx.output.text.lower()
        return all(str(value).lower() in lowered for value in required)


@dataclass
class ForbiddenArgumentText(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        forbidden = (ctx.metadata or {}).get("forbidden_argument_text", [])
        arguments = "\n".join(ctx.output.tool_arguments).lower()
        return all(str(value).lower() not in arguments for value in forbidden)


@dataclass
class OutputFormat(Evaluator[dict, EvalOutput, dict]):
    def evaluate(self, ctx: EvaluatorContext[dict, EvalOutput, dict]) -> bool:
        expected = (ctx.metadata or {}).get("output_format")
        if not expected:
            return True
        if expected.get("kind") == "json_object":
            try:
                parsed = json.loads(ctx.output.text)
            except (TypeError, json.JSONDecodeError):
                return False
            return parsed == expected.get("value")
        if expected.get("kind") == "markdown_bullets":
            lines = [line.strip() for line in ctx.output.text.splitlines() if line.strip()]
            return len(lines) == expected.get("count") and all(
                line.startswith("- ") for line in lines
            )
        return False
